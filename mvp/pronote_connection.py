"""Local PRONOTE connection API and lifetime-bound background synchronization."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    web_url: str = Field(min_length=1, max_length=600)
    account_type: Literal['teacher', 'student', 'parent'] = 'teacher'
    auth_method: Literal['password', 'qr'] = 'password'
    username: str = Field(default='', max_length=300, repr=False)
    password: SecretStr = Field(default_factory=lambda: SecretStr(''), max_length=1000)
    qr_code: SecretStr = Field(default_factory=lambda: SecretStr(''), max_length=6000)
    pin: SecretStr = Field(default_factory=lambda: SecretStr(''), max_length=20)
    ent: str = Field(default='', max_length=80)
    remember_session: bool = False
    auto_sync: bool = True
    interval_seconds: int = Field(default=300, ge=60, le=3600)

    def credentials(self):
        value = self.model_dump(exclude={'auto_sync', 'interval_seconds'})
        for name in ('password', 'qr_code', 'pin'):
            value[name] = getattr(self, name).get_secret_value()
        return value


class PrivateRoute(APIRoute):
    """Validation failures must never echo a password, QR code or entire body."""
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                response = await handler(request)
                response.headers['Cache-Control'] = 'no-store'
                return response
            except RequestValidationError:
                raise HTTPException(422, 'Configuration invalide. Vérifiez l’adresse, le compte et la fréquence d’actualisation.', headers={'Cache-Control': 'no-store'})
        return private_handler


class ConnectionManager:
    def __init__(self, data_dir: Path, connector=None):
        if connector is None:
            from .pronote_connector import PronoteConnector
            connector = PronoteConnector(Path(data_dir))
        self.connector = connector
        self._file = Path(data_dir) / 'pronote-sync-preferences.json'
        self._operation = threading.RLock()
        self._control = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self.auto_sync = True
        self.interval_seconds = 300
        try:
            value = json.loads(self._file.read_text())
            self.auto_sync = value.get('auto_sync') is True
            interval = value.get('interval_seconds')
            if type(interval) is int and 60 <= interval <= 3600:
                self.interval_seconds = interval
        except (OSError, ValueError, TypeError):
            pass

    def status(self):
        return {**self.connector.status(), 'auto_sync': self.auto_sync,
                'interval_seconds': self.interval_seconds}

    def _save_preferences(self):
        self._file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=self._file.parent, prefix='.pronote-sync-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'auto_sync': self.auto_sync, 'interval_seconds': self.interval_seconds}, stream)
            os.replace(temporary, self._file)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def connect(self, body: ConnectRequest):
        with self._operation:
            self.connector.connect(body.credentials())
            self.auto_sync, self.interval_seconds = body.auto_sync, body.interval_seconds
            self._save_preferences()
            self.start(resume=False)
            self._wake.set()
            return self.status()

    def sync(self):
        with self._operation:
            self.connector.sync()
            return self.status()

    def disconnect(self):
        with self._operation:
            self.connector.disconnect()
            return self.status()

    def start(self, *, resume=True):
        with self._control:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._wake.clear()
            self._thread = threading.Thread(target=self._run, args=(resume,),
                                            name='pronote-sync', daemon=True)
            self._thread.start()

    def _run(self, resume):
        try:
            if resume:
                with self._operation:
                    if not self._stop.is_set():
                        try:
                            self.connector.resume()
                        except Exception:
                            # Connector owns a sanitized, actionable error state.
                            pass
            while not self._stop.is_set():
                rescheduled = self._wake.wait(self.interval_seconds)
                self._wake.clear()
                if self._stop.is_set():
                    break
                if rescheduled:
                    continue
                with self._operation:
                    if self._stop.is_set():
                        break
                    status = self.connector.status()
                    retry = status.get('state') == 'error' and status.get('retryable') is True
                    if self.auto_sync and (status.get('connected') or retry):
                        try:
                            self.connector.sync()
                        except Exception:
                            # A failed sync must not kill the scheduler or expose errors.
                            pass
        finally:
            if self._stop.is_set():
                with self._operation:
                    self.connector.close()

    def close(self):
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        # In-flight network calls hold _operation. They close when finished;
        # do not block shutdown indefinitely or delete the saved mobile token.
        if self._operation.acquire(blocking=False):
            try:
                self.connector.close()
            finally:
                self._operation.release()


def install_routes(app, manager: ConnectionManager):
    router = APIRouter(prefix='/api/pronote/connection', route_class=PrivateRoute)

    def local():
        if os.getenv('PUBLIC_URL'):
            raise HTTPException(409, 'Cette connexion utilise le compagnon local sur votre appareil.')

    @router.get('/options')
    def options():
        local()
        from .pronote_connector import connection_options
        return connection_options()

    @router.get('')
    def status():
        local()
        return manager.status()

    @router.post('/connect')
    def connect(body: ConnectRequest):
        local()
        try:
            return manager.connect(body)
        except ValueError:
            raise HTTPException(400, 'Connexion impossible. Vérifiez l’adresse et le mode d’authentification, ou utilisez le navigateur PRONOTE.')
        except Exception:
            raise HTTPException(503, 'Connexion interrompue. Réessayez ou utilisez le navigateur PRONOTE.')

    @router.post('/sync')
    def sync():
        local()
        try:
            return manager.sync()
        except ValueError:
            raise HTTPException(409, 'Reconnectez votre compte PRONOTE avant de synchroniser.')
        except Exception:
            raise HTTPException(503, 'Actualisation impossible. Vérifiez la connexion Internet ou reconnectez le compte.')

    @router.post('/disconnect')
    def disconnect():
        local()
        try:
            return manager.disconnect()
        except Exception:
            raise HTTPException(503, 'La session n’a pas pu être oubliée. Réessayez avant de quitter.')

    app.include_router(router)
