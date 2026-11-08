import Cocoa
import ApplicationServices
import Vision
import ScreenCaptureKit

final class PronoteObserver {
    var busy=false
    var promptedAX=false
    var promptedScreen=false
    var lastDigest=""
    var onPanel:(()->Void)?
    var lastPanelRequest=""
    let tokenPath:String
    init(tokenPath:String){self.tokenPath=tokenPath}
    func tick() {
        guard !busy else{return}
        guard let url=URL(string:"http://127.0.0.1:8000/api/native/settings") else{return}
        URLSession.shared.dataTask(with:url){data,_,_ in
            guard let data=data,let config=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any],config["enabled"] as? Bool == true else{return}
            if let request=config["panel_request"] as? String,request != self.lastPanelRequest {
                self.lastPanelRequest=request;DispatchQueue.main.async{self.onPanel?()}
            }
            self.busy=true
            Task {
                await self.observe(allowOCR:config["allow_ocr"] as? Bool == true, targetPath:config["target_bundle_path"] as? String)
                self.busy=false
            }
        }.resume()
    }
    func post(_ values:[String:Any]) {
        var payload=values
        payload["observed_at"]=ISO8601DateFormatter().string(from:Date())
        payload["source_kind"]="pronote_macos"
        let token=(try? String(contentsOfFile:tokenPath,encoding:.utf8))?.trimmingCharacters(in:.whitespacesAndNewlines) ?? ""
        guard !token.isEmpty else{return}
        var request=URLRequest(url:URL(string:"http://127.0.0.1:8000/api/native/context")!)
        request.httpMethod="POST";request.setValue("application/json",forHTTPHeaderField:"Content-Type");request.setValue("Bearer "+token,forHTTPHeaderField:"Authorization")
        request.httpBody=try? JSONSerialization.data(withJSONObject:payload)
        URLSession.shared.dataTask(with:request).resume()
    }
    func appMatches(_ app:NSRunningApplication)->Bool {
        let name=(app.localizedName ?? "").lowercased(),id=(app.bundleIdentifier ?? "").lowercased()
        return name.contains("pronote") || id.hasPrefix("com.index-education.pronote")
    }
    func observe(allowOCR:Bool, targetPath:String?) async {
        guard let app=NSWorkspace.shared.runningApplications.first(where:{ candidate in
            if let target=targetPath { return candidate.bundleURL?.resolvingSymlinksInPath().path == target }
            return self.appMatches(candidate)
        }) else {
            post(["state":"app_not_running","message":"Le client Pronote Mac n’est pas ouvert."]);return
        }
        let meta:[String:Any]=["app_name":app.localizedName ?? "Client PRONOTE","bundle_id":app.bundleIdentifier ?? "","pid":Int(app.processIdentifier)]
        var payload=meta
        let trusted=AXIsProcessTrusted()
        payload["accessibility_authorized"]=trusted
        if trusted {
            let element=AXUIElementCreateApplication(app.processIdentifier)
            AXUIElementSetMessagingTimeout(element,0.25)
            var budget=150
            let text=read(element,depth:0,budget:&budget).joined(separator:"\n")
            if text.count>100 {
                payload["state"]="observed";payload["method"]="macos_accessibility";payload["visible_text"]=String(text.prefix(16000));post(payload);return
            }
        }
        if !allowOCR {
            payload["state"]="visual_permission_required"
            payload["message"]="Pronote est ouvert. Ses contrôles Windows/CrossOver ne fournissent pas encore de texte exploitable. Autoriser la lecture visuelle de sa seule fenêtre pour poursuivre."
            post(payload);return
        }
        if !CGPreflightScreenCaptureAccess() {
            if !promptedScreen {
                promptedScreen=true
                DispatchQueue.main.async{_ = CGRequestScreenCaptureAccess()}
            }
            payload["state"]="screen_capture_permission_required";payload["message"]="macOS doit autoriser H Parallel à lire la fenêtre Pronote. Aucun écran n’a été lu.";post(payload);return
        }
        do {
            let shareable=try await SCShareableContent.excludingDesktopWindows(true,onScreenWindowsOnly:true)
            guard let window=shareable.windows.first(where:{w in
                let title=(w.title ?? "").lowercased()
                return w.owningApplication?.processID==app.processIdentifier || (targetPath == nil && title.contains("client pronote"))
            }) else {
                payload["state"]="window_not_found";payload["message"]="Pronote est lancé, mais aucune fenêtre lisible n’est actuellement visible.";post(payload);return
            }
            let config=SCStreamConfiguration();config.width=Int(window.frame.width)*2;config.height=Int(window.frame.height)*2;config.showsCursor=false
            let image=try await SCScreenshotManager.captureImage(contentFilter:SCContentFilter(desktopIndependentWindow:window),configuration:config)
            let request=VNRecognizeTextRequest();request.recognitionLevel = .accurate;request.recognitionLanguages=["fr-FR","en-US"];request.usesLanguageCorrection=true
            try VNImageRequestHandler(cgImage:image).perform([request])
            let lines=(request.results ?? []).compactMap{$0.topCandidates(1).first?.string}
            payload["state"]="observed";payload["method"]="window_ocr";payload["window_title"]=window.title ?? "Client PRONOTE";payload["visible_text"]=String(lines.joined(separator:"\n").prefix(16000))
            post(payload)
        } catch {
            payload["state"]="read_error";payload["message"]="La fenêtre Pronote n’a pas pu être lue : \(error.localizedDescription)";post(payload)
        }
    }
    func read(_ element:AXUIElement,depth:Int,budget:inout Int)->[String] {
        guard depth<7,budget>0 else{return []};budget-=1
        var role:CFTypeRef?;AXUIElementCopyAttributeValue(element,kAXRoleAttribute as CFString,&role)
        let kind=role as? String ?? ""
        // Never collect text input values, usernames or password fields.
        if kind==kAXTextFieldRole || kind==kAXTextAreaRole || kind=="AXSecureTextField" {return []}
        var values=[String]()
        if kind==kAXStaticTextRole || kind==kAXWindowRole || kind==kAXButtonRole {
            for name in [kAXTitleAttribute,kAXDescriptionAttribute,kAXValueAttribute] {
                var value:CFTypeRef?
                if AXUIElementCopyAttributeValue(element,name as CFString,&value) == .success,let text=value as? String,!text.isEmpty {values.append(text)}
            }
        }
        var children:CFTypeRef?
        if AXUIElementCopyAttributeValue(element,kAXChildrenAttribute as CFString,&children) == .success,let items=children as? [AXUIElement] {
            for child in items {values += read(child,depth:depth+1,budget:&budget)}
        }
        return values
    }
}
