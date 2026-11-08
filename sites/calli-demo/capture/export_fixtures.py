"""Export the saved read-only GET responses of a local Calli server into capture/raw.

Run the product offline first, from an isolated a0d922e checkout, with saved demo data,
no provider keys and STOP set, for example:

    python -m ui.shell --stop --port 8773 --queue <queue.jsonl> --roster data/roster.csv \
        --course "3A, FRANCAIS, Trimestre 1" --data-dir <saved-data-dir>

then: python3 capture/export_fixtures.py http://127.0.0.1:8773
Only GET requests are sent. Nothing is written to the server.
"""
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

JOB = "6b073dfc404f"      # saved H preparation run (with its saved Devin exercise)
OUTING = "23025b24ce29"   # saved school-trip research draft (partial)
FAMILY_SOURCES = ["A-COPIE", "A-MSG-1", "A-MSG-3", "A-RDV", "L-DEVOIR", "L-REUNION", "L-SORTIE"]
DOCUMENTS = ["copie", "bareme", "consigne", "methode"]
CALLI_CASES = ["s01-francais-t1"]

PATHS = [
    "/", "/calli/workspace",
    "/api/workspace", "/api/auth/me", "/api/calendar/status", "/api/calli/status",
    "/api/notifications/status", "/api/recordings", "/api/recordings/native/status", "/api/reports",
    "/api/fixture", "/api/family", "/api/outings/options",
    f"/api/outings/{OUTING}", f"/api/outings/{OUTING}/export",
    f"/api/jobs/{JOB}", f"/api/jobs/{JOB}/practice", f"/api/jobs/{JOB}/practice/preview",
    f"/api/jobs/{JOB}/audio", "/audio/points",
    "/api/pronote/background", "/api/pronote/connection", "/api/native/context", "/api/native/documents",
    "/calli/api/config", "/calli/api/state", "/calli/api/workspace/cases", "/calli/api/workspace/dictations",
    *[f"/api/family/sources/{s}" for s in FAMILY_SOURCES],
    *[f"/api/workspace/documents/{d}" for d in DOCUMENTS],
    *[f"/calli/api/workspace/cases/{c}" for c in CALLI_CASES],
]
KEEP_HEADERS = {"content-type", "content-security-policy", "permissions-policy", "referrer-policy",
                "x-calli-presentation", "x-calli-original-sha256", "content-disposition"}


def main(base: str) -> None:
    out = Path(__file__).resolve().parent / "raw"
    out.mkdir(exist_ok=True)
    manifest = {"base": "local offline server", "routes": {}}
    for i, path in enumerate(PATHS):
        query = "?embed=1" if path == "/calli/workspace" else ""
        req = urllib.request.Request(base + path + query, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                status, body, headers = res.status, res.read(), res.headers
        except urllib.error.HTTPError as err:
            raise SystemExit(f"{path}: HTTP {err.code}")
        name = f"{i:03d}.bin"
        (out / name).write_bytes(body)
        manifest["routes"][path] = {
            "file": name, "status": status, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
            "headers": {k.lower(): v for k, v in headers.items() if k.lower() in KEEP_HEADERS},
        }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    print(len(PATHS), "routes exported to", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8773")
