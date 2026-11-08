"""Verified H session links and a gated, bounded native PRONOTE demonstration.

Agent View is H's actual live view/replay, not a locally generated MP4. A browser
session is never described as a recording of the native PRONOTE client. This
module neither requests macOS permissions nor substitutes a rendered mock video.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import fcntl
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from .engine import DATA
from .integrations import CONFIG, key

STATUS_FILE = DATA / "native-recording-status.json"
INDEX_FILE = DATA / "h-session-recordings.json"
RUNNING = threading.Lock()
NATIVE_STOP = threading.Event()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def _process_parent_and_executable(pid):
    # Read only this process's ancestry, without command arguments or environment
    # variables. In particular, do not inspect macOS's private TCC database.
    result = subprocess.run(["ps", "-p", str(int(pid)), "-o", "ppid=,comm="],
                            check=True, capture_output=True, text=True, timeout=2)
    parent, executable = result.stdout.strip().split(None, 1)
    return int(parent), executable


def _application_for_executable(executable):
    try:
        binary = Path(executable).resolve(strict=True)
        if not binary.is_file():
            return None
        # A helper may itself be in Nested.app inside the actual host app. Pick
        # the outer bundle that owns that executable, not the embedded helper.
        for parent in reversed(binary.parents):
            if parent.suffix != ".app":
                continue
            info = plistlib.loads((parent / "Contents/Info.plist").read_bytes())
            main = info.get("CFBundleExecutable", "")
            if not main or Path(main).name != main or not (parent / "Contents/MacOS" / main).is_file():
                continue
            return {"path": str(parent),
                    "name": info.get("CFBundleDisplayName") or info.get("CFBundleName") or parent.stem,
                    "bundle_identifier": info.get("CFBundleIdentifier")}
    except (OSError, ValueError, plistlib.InvalidFileException):
        pass
    return None


def discover_host_application(pid=None, read_process=None):
    """Find the outer application in this PID's actual process ancestry.

    This is a supported process/filesystem observation, not a claim to read
    TCC's responsible-code attribution. AX/ScreenCapture preflight stays final.
    """
    current = os.getpid() if pid is None else pid
    read_process = read_process or _process_parent_and_executable
    seen, interpreter, host = set(), None, None
    while current > 1 and current not in seen and len(seen) < 12:
        seen.add(current)
        try:
            parent, executable = read_process(current)
        except (OSError, ValueError, subprocess.SubprocessError):
            break
        application = _application_for_executable(executable)
        if len(seen) == 1:
            interpreter = application
        elif application and application != interpreter:
            host = application
        current = parent
    return host


def desktop_preflight():
    """Read-only checks: no permission dialog, screenshot or synthetic input."""
    application=Path(sys.base_prefix)/"Resources/Python.app"
    host = discover_host_application() if sys.platform == "darwin" else None
    application_path = str(application.resolve()) if application.is_dir() else None
    result = {"checked_at": _now(), "scope": "full_desktop", "process_path": sys.executable,
              "application_path": application_path,
              "host_application_path": host["path"] if host else None,
              "host_application_name": host["name"] if host else None,
              "host_bundle_identifier": host.get("bundle_identifier") if host else None,
              "authorization_target_path": host["path"] if host else application_path,
              "authorization_target_name": host["name"] if host else "Python",
              "authorization_target_basis": "host_process_ancestry" if host else "python_application_fallback",
              "authorization_attribution_verified": False,
              "window_restriction_available": False, "missing": []}
    if sys.platform != "darwin":
        return {**result, "state": "blocked", "missing": ["macos"],
                "message": "Ce lanceur natif est prévu pour le client PRONOTE Mac."}
    dependencies = ("hai_drivers.desktop.local", "ApplicationServices", "Quartz", "pyautogui")
    for dependency in dependencies:
        try:
            found = importlib.util.find_spec(dependency)
        except ImportError:
            found = None
        if found is None:
            result["missing"].append(dependency)
    if result["missing"]:
        return {**result, "state": "blocked", "message": "L’extra SDK H desktop est absent."}
    from ApplicationServices import AXIsProcessTrusted
    from Quartz import CGPreflightScreenCaptureAccess
    result["accessibility_authorized"] = bool(AXIsProcessTrusted())
    result["screen_recording_authorized"] = bool(CGPreflightScreenCaptureAccess())
    if not result["accessibility_authorized"]:
        result["missing"].append("accessibility")
    if not result["screen_recording_authorized"]:
        result["missing"].append("screen_recording")
    result["state"] = "blocked" if result["missing"] else "ready"
    result["message"] = ("macOS n’autorise pas encore ce processus Python à lire et contrôler le bureau."
                         if result["missing"] else "Les deux autorisations macOS sont déjà accordées.")
    return result


def _client():
    from hai_agents import Client
    return Client(api_key=key("H_COMPANY_API_KEY"), base_url=CONFIG.get("H_COMPANY_BASE_URL"))


def session_evidence(client, session_id):
    """Fetch the authenticated provider record; never manufacture a replay URL."""
    record = client.sessions.get_session(session_id).model_dump(mode="json")
    agent = record.get("request", {}).get("agent", {})
    environments = agent.get("environments", []) if isinstance(agent, dict) else []
    environments = [{k: item.get(k) for k in ("id", "kind", "host", "mode")}
                    for item in environments if isinstance(item, dict)]
    desktop = any(item.get("kind") == "desktop" and item.get("host") == "user_device"
                  for item in environments)
    browser = any(item.get("kind") == "web" for item in environments)
    url = record.get("agent_view_url")
    if url:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.hostname != "platform.hcompany.ai"):
            url = None
    status = record.get("status", {})
    status = status.get("status") if isinstance(status, dict) else status
    answer_available = record.get("latest_answer") is not None
    detail = ("Vue et replay réels fournis par H. La présence de PRONOTE doit être vérifiée dans les images."
              if desktop else "Cette session ne prouve pas une manipulation du client PRONOTE natif.")
    if url:
        detail += " Agent View et replay accessibles."
    if status == "interrupted" and answer_available:
        detail += " Une réponse est conservée ; l’état fournisseur est interrupted."
    return {"session_id": record["id"], "provider": "H Company",
            "verified_at": _now(), "status": status, "provider_status": status,
            "answer_available": answer_available, "agent_view_url": url,
            "environments": environments,
            "kind": "h_desktop_session" if desktop else "h_browser_session" if browser else "h_tool_session",
            "label": "Session H sur le bureau local" if desktop else "Navigation H du portail scolaire local" if browser else "Session H avec outils",
            "is_video_file": False, "native_pronote_recording_verified": False,
            "detail": detail}


def refresh_session_index(job_ids=None):
    """Index existing sessions without running, sharing or modifying them."""
    requested = set(job_ids or [])
    sessions = {}
    for path in DATA.glob("*/state.json"):
        try:
            job = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if (not requested or job.get("id") in requested) and job.get("session_id"):
            sessions[job["session_id"]] = job.get("id")
    if not requested and STATUS_FILE.exists():
        native = json.loads(STATUS_FILE.read_text())
        if native.get("session_id"):
            sessions[native["session_id"]] = None
    index = {"updated_at": _now(), "sessions": [], "errors": [],
             "native_video_files": [], "native_video_available": False}
    with _client() as client:
        for session_id, job_id in sessions.items():
            try:
                index["sessions"].append({**session_evidence(client, session_id), "job_id": job_id})
            except Exception as exc:
                # Provider errors can contain request information. Keep only a
                # class name in the public index, never credentials or text.
                index["errors"].append({"session_id": session_id, "error": type(exc).__name__})
    _write(INDEX_FILE, index)
    return index


def status():
    result = json.loads(STATUS_FILE.read_text()) if STATUS_FILE.exists() else {
        "state": "not_started", "message": "Aucun enregistrement natif H n’a été lancé."}
    return {**result, "launch_preflight": result.get("preflight"), "preflight": desktop_preflight()}


def wait_for_pronote_foreground(timeout_seconds=90, *, check=None, on_wait=None):
    """Wait for the actual Mac app; Wine's foreground flag is insufficient."""
    if check is None:
        from .native.foreground import frontmost_pronote_state
        check=frontmost_pronote_state
    deadline=time.monotonic()+max(0,timeout_seconds)
    consecutive=0
    while True:
        if NATIVE_STOP.is_set():raise InterruptedError('Session annulée avant toute capture.')
        observed=check()
        consecutive=consecutive+1 if observed.get("state")=="ready" else 0
        if consecutive>=2:
            return observed
        if time.monotonic()>=deadline:
            raise RuntimeError("PRONOTE n’est pas au premier plan macOS. Sélectionnez PRONOTE Démo locale dans le Dock puis relancez la capture. Aucune session H créée.")
        if on_wait:on_wait(observed)
        time.sleep(min(.4,max(0,deadline-time.monotonic())))


def _real_video(path):
    if not path.is_file() or path.stat().st_size < 1000:
        return False
    try:
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)],
            check=True, capture_output=True, timeout=10)
        data = json.loads(probe.stdout)
        return bool(data.get("streams")) and float(data.get("format", {}).get("duration", 0)) > 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def get_recordings():
    """UI index; only point to an MP4 when an actual video stream exists."""
    native = status()
    native_state = native.get("state", "not_started")
    if native["preflight"]["state"] == "blocked" and native_state in ("not_started", "blocked"):
        native_state = "blocked"
    records = [{"id": "native-pronote", "title": "PRONOTE Mac · session native",
        "kind": "native_pronote", "status": native_state,
        "created_at": native.get("created_at"), "actions": native.get("actions", []),
        "source_detail": "Client PRONOTE Mac réel. " + native.get("message", "") +
            " Le pilote desktop H standard voit tout le bureau ; aucune vidéo native n’est disponible.",
        "preflight": native["preflight"], "launch_preflight": native.get("launch_preflight"),
        "agent_view_url": native.get("agent_view_url")}]
    if native.get('reason') in ('pronote_not_foreground','pronote_focus_lost'):
        records[0]['status_label']='PRONOTE à afficher'
    elif native_state=='waiting_for_pronote':
        records[0]['status_label']='En attente de PRONOTE'
    if INDEX_FILE.exists():
        index = json.loads(INDEX_FILE.read_text())
        for evidence in index.get("sessions", []):
            if evidence.get("kind") != "h_browser_session":
                continue
            records.append({"id": "h-" + evidence["session_id"],
                "title": "Navigation H · portail scolaire local", "kind": "h_web_session",
                "status": evidence["status"], "agent_view_url": evidence.get("agent_view_url"),
                "provider_status": evidence.get("provider_status", evidence["status"]),
                "answer_available": evidence.get("answer_available", False),
                "source_detail": evidence["detail"], "actions": [],
                "created_at": evidence.get("verified_at"), "session_id": evidence["session_id"],
                "job_id": evidence.get("job_id")})
    # The official PRONOTE Web run is produced by the separate legacy_web module.
    # Its media and provenance remain distinct from the Mac client and local demo.
    legacy = DATA / "recordings/legacy-web"
    if (legacy / "state.json").is_file():
        value = json.loads((legacy / "state.json").read_text())
        record = {"id": "legacy-web", "title": value.get("title", "PRONOTE Web officiel · navigation H"),
            "kind": "h_web_session", "status": value.get("status", value.get("state", "not_started")),
            "created_at": value.get("created_at"), "actions": value.get("actions", []),
            "agent_view_url": value.get("agent_view_url"), "session_id": value.get("session_id"),
            "source_detail": value.get("source_detail", "Démo PRONOTE Web officielle. Cette session ne montre pas le client Mac.")}
        if value.get("capture_kind")=="h_observation_replay":
            record["source_detail"] += " Relecture chronologique des captures réelles de H, avec les pauses condensées."
        # The state publishes these media only after its own H run produced
        # them. An older attempt's files must not appear under a new session.
        if value.get("local_video") and _real_video(legacy / "capture.mp4"):
            record["video_url"] = "/recordings/legacy-web/capture.mp4"
            if record["status"] not in ("ready", "completed", "idle"):
                record["source_detail"] += " Enregistrement partiel : la session n’a pas terminé le parcours."
        if value.get("frame_count",0)>0 and (legacy / "preview.png").is_file():
            record["preview_url"] = "/recordings/legacy-web/preview.png?v="+str((legacy/"preview.png").stat().st_mtime_ns)
        records.append(record)
    product = DATA / "product-demo-v2/h-parallel-demo.mp4"
    if _real_video(product):
        records.append({"id": "product-demo", "title": "Film du prototype · données fictives",
            "kind": "product_demo", "status": "ready", "video_url": "/demo-video",
            "created_at": datetime.fromtimestamp(product.stat().st_mtime, timezone.utc).isoformat(),
            "actions": [], "source_detail": "Film DemoBro du prototype local. Ce film ne montre pas une manipulation du client PRONOTE natif."})
    modern = DATA / "recordings/product-workspace"
    if (modern / "manifest.json").is_file() and _real_video(modern / "capture.mp4"):
        manifest = json.loads((modern / "manifest.json").read_text())
        records.append({"id": "product-workspace", "title": "New PRONOTE · film de l’interface",
            "kind": "product_demo", "status": "ready", "video_url": "/recordings/product-workspace/capture.mp4",
            "created_at": manifest.get("created_at"), "actions": [],
            "source_detail": "Film DemoBro de l’interface moderne avant changement de marque. Données fictives ; replay condensé d’une exécution H, Gladia et Linkup enregistrée. Ce film ne montre pas PRONOTE natif."})
    return records


def register_workspace_product_video(source: Path):
    """Expose a finished local DemoBro film without calling it a native run."""
    source = source.resolve(strict=True)
    if source.name != "new-pronote-demo.mp4" or source.parent.parent != DATA.resolve():
        raise ValueError("Expected a known workspace DemoBro output")
    if not source.parent.name.startswith("workspace-demo-") or not _real_video(source):
        raise ValueError("The finished workspace film is not available")
    output = DATA / "recordings/product-workspace"
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "capture.tmp.mp4"
    shutil.copy2(source, temporary)
    temporary.replace(output / "capture.mp4")
    _write(output / "manifest.json", {"created_at": _now(), "kind": "product_demo",
        "provider": "DemoBro", "source_file": str(source), "native_pronote": False,
        "replay": True, "brand_version": "before-rebrand"})
    return output / "capture.mp4"


def start_native_session(*, desktop_prepared=False, focus_timeout_seconds=90):
    """Launch a bounded H run only through a foreground-guarded desktop bridge.

    The caller's permissions are checked in its own process (e.g. iTerm2).
    The process waits for PRONOTE, because opening a Wine HWND does not place
    that application in front on the Mac. A file lease prevents two CLIs from
    controlling the same desktop concurrently.
    """
    if not RUNNING.acquire(blocking=False):return status()
    lease=None
    started=False
    try:
        lock_path=STATUS_FILE.with_suffix('.lock')
        lock_path.parent.mkdir(parents=True,exist_ok=True)
        lease=lock_path.open('a+')
        try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return status()
        NATIVE_STOP.clear()
        preflight=desktop_preflight()
        initial={"created_at":_now(),"provider":"H Company","preflight":preflight,
                 "native_video_available":False,"is_video_file":False,
                 "native_pronote_recording_verified":False}
        if preflight['state']!='ready':
            blocked={**initial,"state":"blocked","reason":"permissions","message":preflight['message']}
            _write(STATUS_FILE,blocked);return blocked
        if not desktop_prepared:
            blocked={**initial,"state":"blocked","reason":"foreground_confirmation",
                     "message":"Afficher uniquement la base d’exemple PRONOTE avant de lancer cette session."}
            _write(STATUS_FILE,blocked);return blocked
        initial.update(state='starting',message='Dans les 90 secondes, passez dans PRONOTE Démo locale depuis le Dock ou Cmd-Tab. H attendra son vrai premier plan macOS. Laissez ensuite PRONOTE affiché. Changer d’application bloque le pilote ; Ctrl+C dans iTerm2 termine la commande.')
        _write(STATUS_FILE,initial)

        def worker():
            session=None
            monitor_stop=threading.Event()
            bridge=None
            try:
                from .native.native_documents import read_window_snapshot
                from .native.foreground import frontmost_pronote_state
                from .native.guarded_desktop import guarded_pronote_bridge,PronoteForegroundLost
                windows=read_window_snapshot().get('windows',[])
                actual=next((w for w in windows if 'base exemple' in w.get('title','').casefold()),None)
                if not actual:raise RuntimeError('La base officielle d’exemple PRONOTE n’est pas observée.')
                last_wait=[None]
                def waiting(observed):
                    state=observed.get('state')
                    if state!=last_wait[0]:
                        _write(STATUS_FILE,{**initial,'state':'waiting_for_pronote',
                            'reason':'pronote_not_foreground','message':initial['message']})
                        last_wait[0]=state
                foreground=wait_for_pronote_foreground(focus_timeout_seconds,on_wait=waiting)
                with guarded_pronote_bridge(api_key=key('H_COMPANY_API_KEY'),base_url=CONFIG.get('H_COMPANY_BASE_URL')) as guarded:
                    bridge=guarded
                    def monitor():
                        while not monitor_stop.wait(.3):
                            stop_requested=getattr(guarded,'stop_requested',None)
                            if NATIVE_STOP.is_set() or (stop_requested is not None and stop_requested.is_set()):
                                guarded.focus_lost.set()
                            if not guarded.focus_lost.is_set() and frontmost_pronote_state().get('state')!='ready':
                                guarded.focus_lost.set()
                            if guarded.focus_lost.is_set() and session is not None:
                                try:session.cancel()
                                except Exception:pass
                                return
                    threading.Thread(target=monitor,daemon=True).start()
                    if NATIVE_STOP.is_set():raise InterruptedError('Session annulée avant lancement de H.')
                    with _client() as client:
                        session=client.start_session(
                            agent={'name':'pronote-native-readonly-demo','description':'Courte démonstration native en lecture seule.',
                                   'environments':[guarded.environment]},
                            messages=('Le bureau doit afficher le vrai PRONOTE Monoposte et sa base d’exemple officielle. '
                                'Si le pilote refuse une observation ou si une autre application apparaît, arrête-toi immédiatement. '
                                'Lis le titre, puis effectue au maximum deux navigations de consultation, par exemple Notes ou Ressources pédagogiques. '
                                'Tu peux ouvrir un menu de navigation ou sélectionner une classe pour consulter ; cela ne modifie aucune donnée. '
                                'Ne saisis rien, ne change aucune cellule, note, donnée, serveur ou préférence, ne sauvegarde et n’exporte rien. '
                                'Aucun shell, fichier, raccourci de changement d’application ou action hors PRONOTE. '
                                'Retourne un constat factuel des vues effectivement lues et des pièces manquantes. '
                                'N’invente jamais une copie d’Alex ou un barème absent.'),
                            max_steps=8,max_time_s=90)
                        _write(STATUS_FILE,{**initial,**session_evidence(client,session.id),
                            'state':'running','native_window_title':actual['title'],'mac_foreground':foreground,
                            'guarded_desktop':True,'escape_armed':bool(getattr(guarded,'escape_armed',False)),
                            'message':'H travaille dans PRONOTE. Laissez cette fenêtre affichée. Changer d’application bloque le pilote.'+(' Double Échap arrête aussi la session.' if getattr(guarded,'escape_armed',False) else '')})
                        # Queue time is separate from the provider's 90s active budget.
                        session.wait_for_completion(timeout_seconds=600,wait_for_seconds=5)
                        evidence=session_evidence(client,session.id)
                        if guarded.focus_lost.is_set():
                            evidence['diagnostic_agent_view_url']=evidence.pop('agent_view_url',None)
                            _write(STATUS_FILE,{**initial,**evidence,'state':'blocked','reason':'pronote_focus_lost',
                                'guarded_desktop':True,'message':'Session arrêtée : PRONOTE a perdu le premier plan. Aucune capture hors cible n’a été transmise par le pilote gardé.'})
                        else:
                            _write(STATUS_FILE,{**initial,**evidence,'state':evidence['status'],
                                'native_window_title':actual['title'],'mac_foreground':foreground,'guarded_desktop':True,
                                'message':'Session H réelle terminée dans PRONOTE avec contrôle du premier plan. Replay à vérifier dans Agent View ; aucun MP4 natif n’est supposé.'})
                        from .engine import finish_session_safely
                        finish_session_safely(session)
            except Exception as exc:
                if session:
                    try:session.cancel()
                    except Exception:pass
                message=str(exc)
                for name in ('H_COMPANY_API_KEY','GLADIA_API_KEY','LINKUP_API_KEY'):
                    secret=CONFIG.get(name)
                    if secret:message=message.replace(secret,'[masqué]')
                _write(STATUS_FILE,{**initial,'state':'blocked' if isinstance(exc,(PermissionError,RuntimeError)) else 'failed',
                    'reason':'pronote_not_foreground' if session is None else 'native_session_stopped',
                    'session_id':session.id if session else None,'guarded_desktop':bridge is not None,'message':message[:500]})
            finally:
                monitor_stop.set()
                if lease:lease.close()
                RUNNING.release()

        threading.Thread(target=worker,daemon=True).start()
        started=True
        return initial
    finally:
        if not started:
            if lease:lease.close()
            RUNNING.release()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "index", "status", "start", "list"))
    parser.add_argument("--desktop-prepared", action="store_true")
    args = parser.parse_args()
    if args.action == "preflight":
        result = desktop_preflight()
    elif args.action == "index":
        result = refresh_session_index()
    elif args.action == "status":
        result = status()
    elif args.action == "list":
        result = get_recordings()
    else:
        result = start_native_session(desktop_prepared=args.desktop_prepared)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # A CLI invocation must keep the local bridge alive until the bounded run
    # settles. An HTTP server using the same function already owns its lifetime.
    if args.action == "start" and result.get("state") == "starting":
        try:
            while RUNNING.locked():threading.Event().wait(.25)
        except KeyboardInterrupt:
            NATIVE_STOP.set()
            deadline=time.monotonic()+10
            while RUNNING.locked() and time.monotonic()<deadline:threading.Event().wait(.1)
