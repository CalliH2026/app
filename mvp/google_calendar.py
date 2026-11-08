"""Explicit one-way sync into an application-owned Google calendar."""
import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from .engine import DATA
from .integrations import key

STORE = DATA / 'google-calendar-private.json'
LOCK = threading.RLock()
REDIRECT = 'http://127.0.0.1:8000/api/calendar/callback'
SCOPE = 'https://www.googleapis.com/auth/calendar.app.created'
API = 'https://www.googleapis.com/calendar/v3'


def read():
    return json.loads(STORE.read_text()) if STORE.exists() else {}


def write(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    temp = STORE.with_suffix('.tmp')
    # Tokens never enter the public workspace or browser storage.
    with open(temp, 'w', opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
        json.dump(data, f)
    temp.replace(STORE)


def status():
    try:
        key('GOOGLE_CLIENT_ID'); key('GOOGLE_CLIENT_SECRET')
        configured = True
    except RuntimeError:
        configured = False
    with LOCK:
        data = read()
    return {'configured': configured, 'connected': bool(data.get('refresh_token')),
            'last_synced': data.get('last_synced')}


def connect():
    key('GOOGLE_CLIENT_SECRET')
    state = secrets.token_urlsafe(32)
    with LOCK:
        data = read()
        data.update(state=state, state_expires=time.time() + 600)
        write(data)
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': key('GOOGLE_CLIENT_ID'), 'redirect_uri': REDIRECT,
        'response_type': 'code', 'scope': SCOPE, 'access_type': 'offline',
        'prompt': 'consent', 'state': state})


def callback(state, code, cookie):
    with LOCK:
        data = read()
        expected = data.pop('state', '')
        expires = data.pop('state_expires', 0)
        write(data)  # Single-use state, including refused authorizations.
        if not state or not cookie or not secrets.compare_digest(state, expected) or not secrets.compare_digest(state, cookie) or expires < time.time():
            raise ValueError('Connexion expirée ou invalide. Recommencez depuis l’agenda.')
        if not code:
            raise ValueError('Autorisation Google refusée.')
        with httpx.Client(timeout=30) as client:
            response = client.post('https://oauth2.googleapis.com/token', data={
                'client_id': key('GOOGLE_CLIENT_ID'), 'client_secret': key('GOOGLE_CLIENT_SECRET'),
                'redirect_uri': REDIRECT, 'code': code, 'grant_type': 'authorization_code'})
            response.raise_for_status()
        token = response.json()
        if not token.get('refresh_token'):
            raise ValueError('Google n’a pas fourni d’accès hors ligne. Reconnectez le calendrier.')
        # A new connection may belong to another account.
        write({'refresh_token': token['refresh_token']})


def sync(meetings):
    with LOCK, httpx.Client(timeout=30) as client:
        data = read()
        if not data.get('refresh_token'):
            raise ValueError('Connectez Google Calendar avant de synchroniser.')
        token = client.post('https://oauth2.googleapis.com/token', data={
            'client_id': key('GOOGLE_CLIENT_ID'), 'client_secret': key('GOOGLE_CLIENT_SECRET'),
            'refresh_token': data['refresh_token'], 'grant_type': 'refresh_token'})
        token.raise_for_status()
        headers = {'Authorization': 'Bearer ' + token.json()['access_token']}
        if not data.get('calendar_id'):
            response = client.post(API + '/calendars', headers=headers, json={
                'summary': 'New PRONOTE · Démonstration', 'timeZone': 'Europe/Paris'})
            response.raise_for_status()
            data['calendar_id'] = response.json()['id']
            write(data)
        from urllib.parse import quote
        url = API + '/calendars/' + quote(data['calendar_id'], safe='') + '/events'
        for index, meeting in enumerate(meetings):
            event_id = hashlib.sha256(f'new-pronote-meeting-{index}'.encode()).hexdigest()
            start = datetime.fromisoformat(meeting['at'])
            event = {'summary': '[Démo] ' + meeting['title'], 'location': meeting['room'],
                     'description': 'Données fictives New PRONOTE.\n' + meeting['reason'],
                     'start': {'dateTime': start.isoformat()},
                     'end': {'dateTime': (start + timedelta(minutes=meeting['duration_minutes'])).isoformat()}}
            response = client.put(url + '/' + event_id, headers=headers, json=event)
            if response.status_code == 404:
                response = client.post(url, headers=headers, json=dict(event, id=event_id))
                if response.status_code == 409:
                    response = client.put(url + '/' + event_id, headers=headers, json=event)
            response.raise_for_status()
        data['last_synced'] = datetime.now().astimezone().isoformat()
        write(data)
        return {'count': len(meetings), 'last_synced': data['last_synced']}


def disconnect():
    with LOCK:
        data = read()
        if data.get('refresh_token'):
            with httpx.Client(timeout=30) as client:
                response = client.post('https://oauth2.googleapis.com/revoke', data={'token': data['refresh_token']})
                if response.status_code not in (200, 400):
                    response.raise_for_status()
        STORE.unlink(missing_ok=True)
