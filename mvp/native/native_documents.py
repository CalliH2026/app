"""Read registered native attachments and detect a real PRONOTE viewer opening.

This module never imports files into PRONOTE and never infers a grade from its
owner-drawn controls. Register only attachments whose native import was actually
verified. A first snapshot establishes a baseline; it cannot create an event.
"""
from __future__ import annotations

from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import unicodedata

from .prepare_demo import ROOT, BOTTLE, RUNTIME, DATA

METHOD = "win32_document_windows"
EXPORT_METHOD = "native_export_file_open"
KINDS = {"native_document", "native_export", "imported_demo_document"}
ROLES = {"copy", "rubric", "instructions"}
MAX_BYTES = 20 * 1024 * 1024
NATIVE_EXPORT_CACHE = DATA / "native-export-cache"
GUID_DIRECTORY = re.compile(r"^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Missing attachment or attachment larger than 20 MB")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_text(path: Path) -> str:
    """Read actual bytes. Scanned/empty PDFs require an explicit OCR path."""
    raw = path.read_bytes()
    if raw.startswith(b"%PDF-"):
        executable = shutil.which("pdftotext")
        if not executable:
            raise RuntimeError("pdftotext is required to read this native PDF")
        result = subprocess.run(
            [executable, "-layout", str(path), "-"], check=True,
            capture_output=True, timeout=20,
        )
        text = result.stdout.decode("utf-8", errors="strict")
    else:
        if b"\0" in raw:
            raise ValueError("Attachment is not a supported text document")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
    text = text.replace("\x0c", "\n").strip()
    if not text or len(text) > 100_000:
        raise ValueError("Native document has no extractable text or exceeds the text budget")
    return text


def read_window_snapshot() -> dict:
    """Inspect the isolated Wine bottle; no desktop input or hooks."""
    source = ROOT / "native/document_windows.c"
    binary = BOTTLE / "drive_c/H-Demo/document-windows.exe"
    output = binary.with_name("document-windows.json")
    if not binary.exists() or source.stat().st_mtime > binary.stat().st_mtime:
        binary.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["x86_64-w64-mingw32-gcc", "-Os", "-municode", "-mconsole",
             "-o", str(binary), str(source), "-luser32", "-lkernel32"],
            check=True, capture_output=True, timeout=30,
        )
    subprocess.run(
        [str(RUNTIME / "bin/wine"), "--bottle", str(BOTTLE), "--no-update",
         "--wait-children", str(binary), "C:\\H-Demo\\document-windows.json"],
        check=True, capture_output=True, timeout=12,
    )
    snapshot = json.loads(output.read_text())
    snapshot["observed_at"] = now()
    return snapshot


def native_drive(manifest: dict) -> Path:
    """Locate only the Wine drive containing this explicitly registered base."""
    database = Path(manifest["database_path"]).resolve(strict=True)
    drive = next((parent for parent in database.parents if parent.name == "drive_c"), None)
    if drive is None:
        raise ValueError("Native exports require the registered PRONOTE Wine drive")
    return drive


def export_roots(manifest: dict) -> list[Path]:
    users = native_drive(manifest) / "users"
    if not users.is_dir():
        return []
    # Do not recurse through user homes or observe the user's actual desktop.
    return [path.resolve() for user in sorted(users.iterdir())[:16]
            if user.is_dir() and (path := user / "Temp").is_dir()]


def verify_native_storage(record: dict, manifest: dict, exported: Path) -> dict:
    """Tie decoded bytes to the actual imported FSFB container, never a name alone."""
    proof = record.get("provenance", {}).get("native_storage", {})
    if not proof:
        proof = record.get("provenance", {}).get("import_evidence", {}).get("native_storage", {})
    container = Path(proof.get("path", "")).resolve(strict=True)
    expected_root = (native_drive(manifest) / "ProgramData/IndexEducation/PRONOTE/MONOPOSTE"
                     / "VERSION 2026-0/FR/DocJointEleve" / str(manifest.get("base_id", ""))).resolve(strict=True)
    if not container.is_relative_to(expected_root) or container.parent != expected_root:
        raise ValueError("Native export storage proof is outside the registered PRONOTE base")
    raw = container.read_bytes()
    if len(raw) > MAX_BYTES or raw[:8] != b"FSFB\x02\0\0\0":
        raise ValueError("Native export requires an actual FSFB v2 storage proof")
    actual = digest(exported)
    if (actual != record.get("sha256") or raw[8:40].hex() != actual
            or hashlib.sha256(raw).hexdigest() != proof.get("file_sha256")):
        raise ValueError("Native export bytes do not match the registered native storage")
    if raw[40:56].hex() != hashlib.md5(exported.read_bytes()).hexdigest():
        raise ValueError("Native export MD5 does not match the native storage")
    return proof


def preview_open_file(path: Path) -> dict | None:
    """Read exact-file handles and Preview's executable; no AX, screenshots or input."""
    path = path.resolve(strict=True)
    result = subprocess.run(["/usr/sbin/lsof", "-Fpcn", "--", str(path)],
                            capture_output=True, text=True, timeout=5)
    if result.returncode not in (0, 1):
        raise RuntimeError("Cannot verify the native PDF viewer's open file")
    pid, command = None, None
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            pid, command = int(line[1:]), None
        elif line.startswith("c"):
            command = line[1:]
        elif line.startswith("n") and pid and command == "Preview" and line[1:] == str(path):
            process = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "comm="],
                                     capture_output=True, text=True, check=True, timeout=3)
            executable = process.stdout.strip()
            if executable != "/System/Applications/Preview.app/Contents/MacOS/Preview":
                continue
            return {"viewer_pid": pid, "viewer_process": command,
                    "viewer_bundle_id": "com.apple.Preview", "viewer_open_path": str(path),
                    "viewer_executable": executable}
    return None


def read_export_snapshot(registry: "AttachmentRegistry", *, viewer=preview_open_file) -> dict:
    """Inspect only exact registered names in PRONOTE's GUID export directories."""
    exports = []
    for root in export_roots(registry.manifest):
        for record in registry.manifest.get("sources", []):
            filename = record["display_name"]
            if Path(filename).name != filename:
                raise ValueError("Native export filename must be a single exact basename")
            candidates = sorted(root.glob("*/" + filename), key=lambda path: path.stat().st_mtime_ns,
                                reverse=True)[:64]
            for candidate in candidates:
                if not GUID_DIRECTORY.fullmatch(candidate.parent.name):
                    continue
                path = candidate.resolve(strict=True)
                if path.parent.parent != root or not path.is_file():
                    continue
                # Wrong/stale names cannot acquire native provenance.
                if digest(path) != record.get("sha256"):
                    continue
                proof = verify_native_storage(record, registry.manifest, path)
                stat = path.stat()
                opened = viewer(path) if record["role"] == "copy" else None
                exports.append({"document_id": record["id"], "role": record["role"],
                    "filename": filename, "path": str(path), "sha256": digest(path),
                    "mtime_ns": stat.st_mtime_ns, "size": stat.st_size,
                    "native_storage": proof, "viewer": opened})
    return {"method": EXPORT_METHOD, "observed_at": now(), "exports": exports}


def export_cache_directory(manifest: dict) -> Path:
    context = str(manifest.get("native_context_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", context) or context in {".", ".."}:
        raise ValueError("Native export cache requires a safe explicit context identifier")
    return NATIVE_EXPORT_CACHE.resolve() / context


def is_native_temp_export(path: Path, manifest: dict, filename: str) -> bool:
    """Check the original native export location even after Temp is cleaned."""
    if not path.is_absolute() or path.name != filename or path.suffix.casefold() != ".pdf":
        return False
    drive = native_drive(manifest)
    try:
        parts = path.relative_to(drive / "users").parts
    except ValueError:
        return False
    return (len(parts) == 4 and parts[1] == "Temp"
            and bool(GUID_DIRECTORY.fullmatch(parts[2]))
            and (not path.exists() or path.resolve(strict=True) == path))


def validate_archived_export(record: dict, manifest: dict) -> Path:
    """An archived companion is accepted only with its real export/storage trace."""
    provenance = record.get("provenance", {})
    archived = provenance.get("archived_from", {})
    evidence = provenance.get("archive_evidence", {})
    if (provenance.get("kind") != "native_export" or not isinstance(archived, dict)
            or evidence.get("method") != "native_export_archive"
            or not archived.get("observed_at") or not archived.get("path")):
        raise ValueError("Archived school document requires verified native export provenance")
    path = Path(record["path"]).resolve(strict=True)
    directory = export_cache_directory(manifest)
    if path.parent != directory or path.name != record["display_name"]:
        raise ValueError("Archived native document is outside its registered context cache")
    original = Path(archived["path"])
    if (not is_native_temp_export(original, manifest, record["display_name"])
            or archived.get("url") != original.as_uri()
            or archived.get("sha256") != record.get("sha256")
            or archived.get("sha256") != digest(path)):
        raise ValueError("Archived bytes do not match the original native Temp export")
    proof = verify_native_storage(record, manifest, path)
    if archived.get("native_storage") != proof:
        raise ValueError("Archived native export storage trace is missing or changed")
    return path


def archive_native_exports(registry: "AttachmentRegistry") -> dict:
    """Explicit setup step: persist already verified native exports, never originals.

    This helper neither changes the active manifest nor emits an opening. The
    caller reviews/writes the returned manifest after the actual run completes.
    """
    manifest = copy.deepcopy(registry.manifest)
    directory = export_cache_directory(manifest)
    staged = []
    for record in manifest["sources"]:
        provenance = record["provenance"]
        path = registry._path(record)
        if (provenance.get("kind") != "native_export"
                or not is_native_temp_export(path, manifest, record["display_name"])):
            raise ValueError("Only actual decoded native Temp exports may be archived")
        proof = verify_native_storage(record, manifest, path)
        raw = path.read_bytes()
        if not raw.startswith(b"%PDF-") or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError("The native PDF changed before archival")
        staged.append((record, path, raw, proof))
    # Validate the complete set before writing any archive files.
    directory.mkdir(parents=True, exist_ok=True)
    observed_at = now()
    for record, original, raw, proof in staged:
        path = directory / record["display_name"]
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)
        record["path"] = str(path)
        record["provenance"].update(path=str(path), locator=str(path),
            archived_from={"path": str(original), "url": original.as_uri(),
                "sha256": record["sha256"], "observed_at": observed_at,
                "native_storage": proof},
            archive_evidence={"method": "native_export_archive", "archived_at": observed_at},
            text_extraction_source="archived bytes of an actually verified PRONOTE Temp export")
        validate_archived_export(record, manifest)
    manifest["attachment_roots"] = [str(directory)]
    return manifest


class AttachmentRegistry:
    """Explicit mapping from real database files to pedagogical roles.

    Manifest keys: attachment_roots, native_context_id, sources, parent_audio.
    Every source has id, role, path, display_name and provenance.kind. Imported
    demo sources additionally require provenance.import_evidence describing the
    native UI action that was actually observed. No fixtures are auto-registered.
    """
    def __init__(self, manifest: dict):
        self.manifest = manifest
        self.roots = [Path(p).resolve(strict=True) for p in manifest["attachment_roots"]]
        if not self.roots:
            raise ValueError("At least one actual native attachment root is required")

    @classmethod
    def from_file(cls, path: Path) -> "AttachmentRegistry":
        return cls(json.loads(path.read_text()))

    def _path(self, record: dict, *, audio: bool = False) -> Path:
        path = Path(record["path"]).resolve(strict=True)
        roots = ([Path(p).resolve(strict=True) for p in self.manifest.get('audio_roots', [])]
                 if audio and self.manifest.get('audio_roots') else self.roots)
        if not any(path.is_relative_to(root) for root in roots):
            raise ValueError("Attachment path is outside the registered native roots")
        provenance = record.get("provenance", {})
        if provenance.get("kind") not in (KINDS | ({'attached_test_dossier'} if audio else set())):
            raise ValueError("Attachment requires explicit source provenance")
        if provenance["kind"] == "imported_demo_document" and not provenance.get("import_evidence"):
            raise ValueError("Imported demonstration data requires observed native import evidence")
        actual = digest(path)
        if record.get("sha256") and record["sha256"] != actual:
            raise ValueError("Native attachment changed since registration")
        if not audio and (provenance.get("archived_from") or provenance.get("archive_evidence")):
            validate_archived_export(record, self.manifest)
        return path

    def sources(self, observed_at: str) -> list[dict]:
        result = []
        for record in self.manifest.get("sources", []):
            if record.get("role") not in ROLES:
                raise ValueError("Unknown pedagogical source role")
            path = self._path(record)
            before = digest(path)
            text = extract_text(path)
            if digest(path) != before:
                raise ValueError("Native attachment changed while being read")
            result.append({
                "id": record["id"], "role": record["role"],
                "title": record["display_name"], "text": text,
                "sha256": before,
                "provenance": {**record["provenance"], "path": str(path),
                    "locator": str(path),
                    "imported_into_native": record["provenance"]["kind"] == "imported_demo_document"
                        or (record["provenance"]["kind"] == "native_export"
                            and bool(record["provenance"].get("import_evidence"))),
                    "attachment_id": record["id"], "observed_at": observed_at,
                    "native_context_id": self.manifest["native_context_id"]},
            })
        if not {"copy", "rubric"}.issubset({s["role"] for s in result}):
            raise ValueError("Actual copy and rubric attachments are required")
        if len({s["id"] for s in result}) != len(result):
            raise ValueError("Native attachment identifiers must be unique")
        return result

    def audio(self, observed_at: str) -> dict | None:
        record = self.manifest.get("parent_audio")
        if not record:
            return None
        path = self._path(record, audio=True)
        return {"path": str(path), "sha256": digest(path),
            "provenance": {**record["provenance"], "path": str(path),
                "locator": str(path),
                "imported_into_native": record["provenance"]["kind"] == "imported_demo_document",
                "native_context_id": self.manifest["native_context_id"],
                "observed_at": observed_at}}


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def exported_registry(registry: AttachmentRegistry, exports: list[dict], active: dict,
                      observed_at: str) -> AttachmentRegistry:
    """Read the decoded school files from this actual PRONOTE export session."""
    manifest = copy.deepcopy(registry.manifest)
    directory = Path(active["path"]).parent
    manifest["attachment_roots"] = [*manifest["attachment_roots"], str(directory)]
    for record in manifest["sources"]:
        origin = record["provenance"].get("import_origin_kind", record["provenance"]["kind"])
        exported = next((item for item in exports if item["document_id"] == record["id"]
                         and Path(item["path"]).parent == directory), None)
        if not exported:
            # Only verified persistent exports may supply companion documents.
            # The active copy must always come from the new genuine opening.
            if record["id"] == active["document_id"] or record.get("role") == "copy":
                raise ValueError("The active copy must be a newly opened native Temp export")
            validate_archived_export(record, manifest)
            continue
        path = Path(exported["path"]).resolve(strict=True)
        verify_native_storage(record, manifest, path)
        record["path"] = str(path)
        record["provenance"].pop("archived_from", None)
        record["provenance"].pop("archive_evidence", None)
        record["provenance"].update(kind="native_export", imported_into_native=True,
            import_origin_kind=origin,
            text_extraction_source="actual clear PDF decoded by PRONOTE from its native attachment store",
            export_evidence={"method": EXPORT_METHOD, "export_path": str(path),
                             "sha256": exported["sha256"], "observed_at": observed_at})
    return AttachmentRegistry(manifest)


def event_fingerprint(registry: AttachmentRegistry, document: str, sources: list[dict],
                      audio: dict | None) -> str:
    return hashlib.sha256(json.dumps({
        "context": registry.manifest["native_context_id"], "document": document,
        "sources": [(source["id"], source["sha256"]) for source in sources],
        "audio": audio["sha256"] if audio else None,
    }, sort_keys=True).encode()).hexdigest()


def viewer_matches(window: dict, filename: str) -> bool:
    """A filename in the main grade grid or an Open dialog is not an opening."""
    title = normalized(window.get("title", ""))
    kind = normalized(window.get("class", ""))
    if ".not" in title or title.strip() in {"ouvrir", "open", "enregistrer sous", "save as"}:
        return False
    pattern = r"(?<![\w.])" + re.escape(normalized(filename)) + r"(?![\w.])"
    if re.search(pattern, title):
        return True
    # Integrated PDF viewers sometimes keep a generic title and show the exact
    # filename in a non-editable caption. Require a viewer-specific class/title.
    viewer = any(x in kind + " " + title for x in ("pdfview", "visionneuse", "documentviewer", "aperçu"))
    return viewer and any(re.search(pattern, normalized(c.get("text", "")))
                          for c in window.get("controls", []))


class DocumentOpenDetector:
    def __init__(self, state_file: Path | None = None):
        self.state_file = state_file
        self.seen_windows: set[str] | None = None
        self.seen_exports: set[str] | None = None
        self.emitted: set[str] = set()
        if state_file and state_file.exists():
            self.emitted = set(json.loads(state_file.read_text()).get("emitted", []))

    def observe(self, snapshot: dict, registry: AttachmentRegistry, *, commit: bool = True) -> list[dict]:
        if snapshot.get("method") != METHOD:
            raise ValueError("Copy-open detection requires the native document-window probe")
        windows = snapshot.get("windows", [])
        identities = {f"{w['pid']}:{w['hwnd']}:{w.get('title', '')}" for w in windows}
        previous = self.seen_windows
        if previous is None:
            self.seen_windows = identities
            return []
        observed_at = snapshot.get("observed_at") or now()
        candidates = [(w, record) for w in windows
            if f"{w['pid']}:{w['hwnd']}:{w.get('title', '')}" not in previous
            for record in registry.manifest.get("sources", [])
            if record.get("role") == "copy" and viewer_matches(w, record["display_name"])]
        if not candidates:
            self.seen_windows = identities
            return []
        sources, audio = registry.sources(observed_at), registry.audio(observed_at)
        events = []
        for window, record in candidates:
            fingerprint = event_fingerprint(registry, record["id"], sources, audio)
            if fingerprint in self.emitted:
                continue
            active = next(s for s in sources if s["id"] == record["id"])
            events.append({"context": {
                "source_kind": "pronote_macos", "method": METHOD, "state": "observed",
                "context_id": registry.manifest["native_context_id"],
                "native_context_id": registry.manifest["native_context_id"],
                "database_path": registry.manifest.get("database_path", ""),
                "base_id": registry.manifest.get("base_id", ""),
                "dossier_id": registry.manifest.get("dossier_id", ""),
                "window_title": window["title"], "pid": window["pid"],
                "observed_at": observed_at,
            }, "sources": sources, "parent_audio": audio, "trigger": {
                "type": "copy_opened", "document_id": record["id"],
                "source_locator": active["provenance"]["locator"],
                "proof": window["title"],
                "event_id": fingerprint, "observed_at": observed_at,
                "evidence": {"method": METHOD, "hwnd": window["hwnd"],
                    "window_title": window["title"], "class": window.get("class", ""),
                    "process": window.get("process", ""), "filename": record["display_name"],
                    "pid": window["pid"], "parent_pid": window.get("parent_pid", 0),
                    "owner_hwnd": window.get("owner_hwnd", ""),
                    "image_path": window.get("image_path", ""),
                    "controls": window.get("controls", [])},
            }, "identity": registry.manifest.get("identity", {}),
                "appointment": registry.manifest.get("appointment", {})})
        self._pending_windows = identities
        if commit:
            self.acknowledge(events)
        return events

    def observe_exports(self, snapshot: dict, exports: dict, registry: AttachmentRegistry,
                        *, commit: bool = True) -> list[dict]:
        """A verified native export newly open in Preview is a genuine copy opening.

        The exported PDF name or file creation alone is insufficient: the actual
        native storage hashes, live PRONOTE base and exact viewer file handle are
        all required. The first observation establishes a no-event baseline.
        """
        if snapshot.get("method") != METHOD or exports.get("method") != EXPORT_METHOD:
            raise ValueError("Native export detection requires both native metadata observations")
        observed_at = exports.get("observed_at") or now()
        main = next((window for window in snapshot.get("windows", [])
                     if window.get("process", "").casefold() in
                     {"pronote monoposte.exe", "client pronote.exe"}
                     and Path(registry.manifest["database_path"]).name.casefold()
                     in window.get("title", "").casefold()), None)
        if not main or not int(main.get("pid", 0)):
            raise ValueError("Native copy export requires the registered PRONOTE base to be open")
        candidates = [item for item in exports.get("exports", [])
                      if item.get("role") == "copy" and item.get("viewer")]
        def identity(item):
            return f"{item['path']}:{item['mtime_ns']}:{item['size']}:{item['viewer']['viewer_pid']}"
        identities = {identity(item) for item in candidates}
        previous = self.seen_exports
        if previous is None:
            self.seen_exports = identities
            return []
        events = []
        for item in candidates:
            if identity(item) in previous:
                continue
            viewer = item["viewer"]
            path = Path(item["path"]).resolve(strict=True)
            roots = export_roots(registry.manifest)
            if (not any(path.parent.parent == root for root in roots)
                    or not GUID_DIRECTORY.fullmatch(path.parent.name)
                    or viewer.get("viewer_bundle_id") != "com.apple.Preview"
                    or viewer.get("viewer_process") != "Preview"
                    or int(viewer.get("viewer_pid", 0)) <= 0
                    or Path(viewer.get("viewer_open_path", "")).resolve() != path):
                raise ValueError("Copy opening requires Preview's exact registered native export file")
            enriched = exported_registry(registry, exports["exports"], item, observed_at)
            sources, audio = enriched.sources(observed_at), enriched.audio(observed_at)
            active = next(source for source in sources if source["id"] == item["document_id"])
            fingerprint = event_fingerprint(enriched, item["document_id"], sources, audio)
            if fingerprint in self.emitted:
                continue
            evidence = {"method": EXPORT_METHOD, "export_path": str(path),
                "sha256": active["sha256"], "filename": item["filename"],
                "observed_at": observed_at, **viewer}
            events.append({"context": {
                "source_kind": "pronote_macos", "method": EXPORT_METHOD, "state": "observed",
                "context_id": registry.manifest["native_context_id"],
                "native_context_id": registry.manifest["native_context_id"],
                "database_path": registry.manifest["database_path"],
                "base_id": registry.manifest.get("base_id", ""),
                "dossier_id": registry.manifest["dossier_id"],
                "database_window_title": main["title"], "window_title": main["title"],
                "pid": main["pid"], "observed_at": observed_at,
            }, "sources": sources, "parent_audio": audio,
                "trigger": {"type": "copy_opened", "document_id": item["document_id"],
                    "source_locator": str(path), "proof": f"PRONOTE → Preview : {item['filename']}",
                    "event_id": fingerprint, "observed_at": observed_at, "evidence": evidence},
                "identity": registry.manifest.get("identity", {}),
                "appointment": registry.manifest.get("appointment", {})})
        self._pending_exports = identities
        if not events:
            self.seen_exports = identities
        if commit:
            self.acknowledge(events)
        return events

    def acknowledge(self, events: list[dict]) -> None:
        """Consume only events the pipeline has actually accepted."""
        self.emitted.update(event['trigger']['event_id'] for event in events)
        if self.state_file and events:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({"emitted": sorted(self.emitted)}))
            temporary.replace(self.state_file)
        self.seen_windows = getattr(self, '_pending_windows', self.seen_windows)
        self.seen_exports = getattr(self, '_pending_exports', self.seen_exports)
