import Cocoa
import UserNotifications
import WebKit

final class Delegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let center = UNUserNotificationCenter.current()
    var panel:NSPanel?
    lazy var observer=PronoteObserver(tokenPath:URL(fileURLWithPath:statusPath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("credentials/pronote-bridge-token").path)
    var booted=false
    var timer: Timer?
    var seen = Set<String>()
    let started = Date()
    let statusPath = CommandLine.arguments.dropFirst().first ?? "/tmp/h-parallel-status.json"
    func status(_ value: String) {
        let data = try? JSONSerialization.data(withJSONObject: ["status":value,"updated_at":ISO8601DateFormatter().string(from:Date())])
        try? data?.write(to:URL(fileURLWithPath:statusPath),options:.atomic)
    }
    func applicationDidFinishLaunching(_ notification: Notification) { start() }
    func start() {
        guard !booted else { return };booted=true
        NSApp.setActivationPolicy(.accessory)
        center.delegate=self
        observer.onPanel={self.showPanel()}
        timer=Timer.scheduledTimer(withTimeInterval:4,repeats:true){_ in self.poll();self.observer.tick()}
        observer.tick()
        let keep = UNNotificationAction(identifier:"keep",title:"Keep",options:[])
        let dismiss = UNNotificationAction(identifier:"dismiss",title:"Dismiss",options:[])
        let open = UNNotificationAction(identifier:"open",title:"Voir le rapport",options:[.foreground])
        center.setNotificationCategories([UNNotificationCategory(identifier:"H_REPORT",actions:[keep,dismiss,open],intentIdentifiers:[],options:[.customDismissAction])])
        status("requesting")
        center.requestAuthorization(options:[.alert,.badge]) { allowed,error in
            self.status(allowed ? "authorized" : "denied")
            guard allowed else { return }
            DispatchQueue.main.async {
                self.poll()
            }
        }
    }
    func showPanel() {
        if panel==nil {
            let screen=NSScreen.main?.visibleFrame ?? NSRect(x:0,y:0,width:1440,height:900)
            let frame=NSRect(x:screen.maxX-435,y:screen.maxY-735,width:415,height:710)
            let window=NSPanel(contentRect:frame,styleMask:[.titled,.closable,.resizable,.utilityWindow,.nonactivatingPanel],backing:.buffered,defer:false)
            window.title="Parallèle · PRONOTE";window.level = .floating;window.isFloatingPanel=true;window.hidesOnDeactivate=false;window.collectionBehavior=[.canJoinAllSpaces,.fullScreenAuxiliary]
            let web=WKWebView(frame:NSRect(origin:.zero,size:frame.size))
            window.contentView=web;web.load(URLRequest(url:URL(string:"http://127.0.0.1:8000/native")!));panel=window
        }
        panel?.orderFrontRegardless()
    }
    func poll() {
        center.getNotificationSettings { settings in
            self.status(settings.authorizationStatus == .authorized ? "authorized" : settings.authorizationStatus == .denied ? "denied" : "requesting")
        }
        guard let url=URL(string:"http://127.0.0.1:8000/api/notifications/feed") else { return }
        URLSession.shared.dataTask(with:url) { data,_,_ in
            guard let data=data,let items=(try? JSONSerialization.jsonObject(with:data)) as? [[String:Any]] else { return }
            for item in items {
                guard let id=item["id"] as? String,let phase=item["phase"] as? String,let at=item["at"] as? String else { continue }
                let formatter=ISO8601DateFormatter();formatter.formatOptions=[.withInternetDateTime,.withFractionalSeconds]
                guard let date=formatter.date(from:at),date>=self.started.addingTimeInterval(-2) else { continue }
                let key=id+"-"+phase
                DispatchQueue.main.async {
                    guard !self.seen.contains(key) else { return };self.seen.insert(key)
                    let content=UNMutableNotificationContent()
                    content.title="Parallèle"
                    content.subtitle=(item["label"] as? String) ?? (id.hasPrefix("native-") ? "PRONOTE · rapport de contexte" : "Préparation du rendez-vous")
                    content.body=phase=="native-ready" ? "J’ai lu le contexte du vrai PRONOTE et préparé le rapport. Les pièces non lisibles sont signalées." : phase=="ready" ? "La capsule et les preuves sont prêtes. Vous pouvez continuer votre travail." : "J’ai rapproché la question des parents et les pièces scolaires. Le rapport avance."
                    let path=(item["source_kind"] as? String)=="pronote_native_dossier" ? "/native?job=\(id)" : id.hasPrefix("native-") ? "/native" : "/?job=\(id)"
                    content.categoryIdentifier="H_REPORT";content.threadIdentifier=id;content.userInfo=["job":id,"path":path]
                    self.center.add(UNNotificationRequest(identifier:key,content:content,trigger:nil)) { error in
                        if error != nil {self.status("delivery_error")}
                    }
                }
            }
        }.resume()
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter,willPresent notification: UNNotification,withCompletionHandler complete: @escaping (UNNotificationPresentationOptions)->Void) { complete([.banner,.list]) }
    func userNotificationCenter(_ center: UNUserNotificationCenter,didReceive response: UNNotificationResponse,withCompletionHandler complete: @escaping ()->Void) {
        guard let id=response.notification.request.content.userInfo["job"] as? String else {complete();return}
        let action=response.actionIdentifier
        if action=="keep" || action=="dismiss" || action==UNNotificationDismissActionIdentifier {
            let choice=action=="keep" ? "keep" : "dismiss"
            let endpoint=id.hasPrefix("native-") ? "http://127.0.0.1:8000/api/native/decision" : "http://127.0.0.1:8000/api/jobs/\(id)/decision"
            var request=URLRequest(url:URL(string:endpoint)!)
            request.httpMethod="POST";request.setValue("application/json",forHTTPHeaderField:"Content-Type")
            var payload=["decision":choice]
            if id.hasPrefix("native-"){payload["context_id"]=String(id.dropFirst(7))}
            request.httpBody=try? JSONSerialization.data(withJSONObject:payload)
            URLSession.shared.dataTask(with:request) { _,_,_ in complete() }.resume()
        } else {
            let path=(response.notification.request.content.userInfo["path"] as? String) ?? (id.hasPrefix("native-") ? "/native" : "/?job=\(id)")
            let target="http://127.0.0.1:8000"+path
            NSWorkspace.shared.open(URL(string:target)!);complete()
        }
    }
}
@main
struct Launcher {
    static func main() {
        let app=NSApplication.shared
        let delegate=Delegate();app.delegate=delegate
        app.finishLaunching();delegate.start();app.run()
    }
}
