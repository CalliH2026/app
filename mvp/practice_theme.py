"""Reversible New Pronote presentation layer for practice previews.

The stored artifact keeps its bytes and SHA-256 (checked by practice.artifact_path);
only the preview response is derived: a style block and a key bridge are appended
before </head>, and the artifact's own meta CSP allows inline data: fonts.
Downloads stay the original file.
"""
import base64
import hashlib
import re
from functools import lru_cache
from pathlib import Path

STATIC = Path(__file__).parent / 'static'
THEME_VERSION = 'new-pronote-v1'
# Latin and Latin Extended subsets of Plus Jakarta Sans from h-kit/fonts.css.
FONT_FILES = ('fba5a26ea33df6a3-s.p.08ssgmy_tb90r.woff2', '1a099d89ee94ee96-s.15dvesjzf7814.woff2')
PREVIEW_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
               "img-src data:; connect-src 'none'; font-src data:; object-src 'none'; base-uri 'none'; "
               "form-action 'none'; frame-ancestors 'self'")
# Escape inside the sandboxed frame never reaches the parent dialog; forward a constant.
ESCAPE_BRIDGE = ("addEventListener('keydown',function(e){if(e.key==='Escape')"
                 "window.parent.postMessage('calli-practice-escape','*');});")


@lru_cache(maxsize=1)
def _layer():
    faces = []
    css = (STATIC / 'h-kit' / 'fonts.css').read_text(encoding='utf-8')
    for name in FONT_FILES:
        rule = re.search(r'@font-face\{[^}]*' + re.escape(name) + r'[^}]*\}', css).group(0)
        data = base64.b64encode((STATIC / 'h-kit' / 'fonts' / name).read_bytes()).decode('ascii')
        faces.append(rule.replace('url(./fonts/' + name + ')', 'url(data:font/woff2;base64,' + data + ')'))
    theme = (STATIC / 'practice-theme.css').read_text(encoding='utf-8')
    return (f'<style data-calli-theme="{THEME_VERSION}">' + ''.join(faces) + theme + '</style>'
            f'<script data-calli-theme="{THEME_VERSION}">' + ESCAPE_BRIDGE + '</script>')


def themed(content: bytes) -> bytes:
    text = content.decode('utf-8-sig')
    text = re.sub(r"(<meta\s+http-equiv=[\"']Content-Security-Policy[\"'][^>]*?)font-src 'none'",
                  r"\1font-src data:", text, flags=re.IGNORECASE)
    head = re.search(r'</head\s*>', text, re.IGNORECASE)
    layer = _layer()
    text = text[:head.start()] + layer + text[head.start():] if head else layer + text
    return text.encode('utf-8')


def provenance(original: bytes) -> dict:
    derived = themed(original)
    return {'theme': THEME_VERSION, 'original_sha256': hashlib.sha256(original).hexdigest(),
            'preview_sha256': hashlib.sha256(derived).hexdigest(),
            'transform': 'preview only: New Pronote style layer and Escape bridge appended; meta CSP font-src data:'}
