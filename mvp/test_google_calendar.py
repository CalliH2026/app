from datetime import datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from . import google_calendar as calendar


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(calendar, 'STORE', tmp_path / 'private.json')
    monkeypatch.setattr(calendar, 'key', lambda name: 'test-client')


def test_oauth_requires_browser_state_and_is_single_use(store):
    url = calendar.connect()
    state = parse_qs(urlparse(url).query)['state'][0]
    with pytest.raises(ValueError):
        calendar.callback(state, 'code', 'wrong-browser')
    with pytest.raises(ValueError):
        calendar.callback(state, 'code', state)
    assert 'state' not in calendar.read()
    assert calendar.STORE.stat().st_mode & 0o777 == 0o600
    assert 'refresh_token' not in calendar.status()


def test_sync_creates_then_updates_same_event_without_inviting_people(store, monkeypatch):
    calls = []
    events = {}
    def handle(request):
        import json
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'secret-access'})
        if request.url.path.endswith('/calendars'):
            return httpx.Response(200, json={'id': 'dedicated@example.com'})
        body = json.loads(request.content)
        assert 'attendees' not in body
        if request.method == 'PUT':
            event_id = request.url.path.rsplit('/', 1)[1]
            if event_id not in events:
                return httpx.Response(404)
        else:
            event_id = body['id']
        events[event_id] = body
        return httpx.Response(200, json={'id': event_id})
    client = httpx.Client
    monkeypatch.setattr(calendar.httpx, 'Client', lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs))
    calendar.write({'refresh_token': 'private-refresh'})
    meeting = {'at': '2026-11-07T18:00:00+01:00', 'title': 'Parents', 'room': 'Salle 1', 'reason': 'Échange', 'duration_minutes': 30}
    assert calendar.sync([meeting])['count'] == 1
    meeting['at'] = '2026-11-08T18:00:00+01:00'
    calendar.sync([meeting])
    assert len(events) == 1
    event = next(iter(events.values()))
    assert datetime.fromisoformat(event['end']['dateTime']).minute == 30
    assert event['start']['dateTime'] == meeting['at']
    assert sum(r.url.path.endswith('/calendars') for r in calls) == 1
    assert sum(r.method == 'POST' and r.url.path.endswith('/events') for r in calls) == 1
    assert 'private-refresh' not in str(calendar.status())
