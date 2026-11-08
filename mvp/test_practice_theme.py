"""New Pronote presentation layer for practice previews; offline, no provider calls."""
import hashlib
import re

from fastapi.testclient import TestClient

from . import practice, practice_theme
from .app import app
from .test_practice import JOB_ID, finished, store  # noqa: F401

PROVIDER_HTML = (b'<!doctype html><html lang="fr"><head><meta charset="utf-8">'
                 b'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; font-src \'none\'">'
                 b'<style>body{font-family:system-ui}</style></head><body><h1>Pythagore</h1>'
                 b'<button id="restart">Recommencer</button><script>let step=1;</script></body></html>')


def test_layer_is_appended_once_and_keeps_the_original_markup():
    themed = practice_theme.themed(PROVIDER_HTML).decode()
    assert themed.count('data-calli-theme="new-pronote-v1"') == 2
    assert themed.index('data-calli-theme') < themed.index('</head>')
    assert "font-src data:" in themed and "font-src 'none'" not in themed
    assert '<style>body{font-family:system-ui}</style>' in themed
    assert '<button id="restart">Recommencer</button><script>let step=1;</script>' in themed
    assert themed.replace(practice_theme._layer(), '').replace('font-src data:', "font-src 'none'") == PROVIDER_HTML.decode()


def test_layer_contains_only_trusted_inline_css_fonts_and_the_escape_bridge():
    layer = practice_theme._layer()
    urls = re.findall(r'url\(([^)]*)\)', layer)
    assert urls and all(url.startswith('data:font/woff2;base64,') for url in urls)
    readable = re.sub(r'data:font/woff2;base64,[A-Za-z0-9+/=]+', '', layer)
    assert not re.search(r'https?:|//|@import|fetch\(|XMLHttpRequest|localStorage|top\.|opener', readable)
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', layer, re.DOTALL)
    assert scripts == [practice_theme.ESCAPE_BRIDGE]
    assert "postMessage('calli-practice-escape','*')" in practice_theme.ESCAPE_BRIDGE


def test_preview_is_themed_while_the_stored_file_and_download_stay_original(store):  # noqa: F811
    practice.start(JOB_ID)
    assert finished()['status'] == 'ready'
    path = practice.artifact_path(JOB_ID)
    original = path.read_bytes()
    client = TestClient(app)
    response = client.get(f'/api/jobs/{JOB_ID}/practice/preview')
    assert response.status_code == 200
    assert 'data-calli-theme="new-pronote-v1"' in response.text
    assert response.headers['x-calli-original-sha256'] == hashlib.sha256(original).hexdigest()
    policy = response.headers['content-security-policy']
    assert policy.startswith('sandbox allow-scripts;') and 'allow-same-origin' not in policy
    assert 'font-src data:' in policy and "connect-src 'none'" in policy and "frame-ancestors 'self'" in policy
    assert path.read_bytes() == original
    practice.approve(JOB_ID)
    download = client.get(f'/api/jobs/{JOB_ID}/practice/download')
    assert download.content == original
    assert 'data-calli-theme' not in download.text
    assert 'font-src' not in download.headers['content-security-policy']
    assert practice.get(JOB_ID)['presentation']['original_sha256'] == hashlib.sha256(original).hexdigest()


def test_altered_stored_artifact_is_still_rejected_before_theming(store):  # noqa: F811
    practice.start(JOB_ID)
    assert finished()['status'] == 'ready'
    practice.artifact_path(JOB_ID).write_text('<html><head></head><body>tampered</body></html>')
    response = TestClient(app).get(f'/api/jobs/{JOB_ID}/practice/preview')
    assert response.status_code in (404, 409)
    assert 'tampered' not in response.text


def test_frame_stays_allow_scripts_only():
    source = (practice_theme.STATIC / 'practice.js').read_text(encoding='utf-8')
    assert source.count('sandbox="allow-scripts"') == 1
    assert 'allow-same-origin' not in source
    assert "event.source===frame?.contentWindow&&event.data==='calli-practice-escape'" in source
