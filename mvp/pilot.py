"""Single-teacher local pilot configuration. Credentials stay in PRONOTE."""
import json
import os
import plistlib
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, field_validator, ConfigDict
DATA = Path(os.environ.get('PRONOTE_PILOT_DATA', Path(__file__).parent / 'data'))

FILE = DATA / 'pronote-pilot.json'

class PilotConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    connection_mode: Literal['local', 'web'] = 'local'
    auth_route: Literal['direct', 'ent'] = 'ent'
    establishment: str = Field(default='', max_length=160)
    web_url: str = Field(default='', max_length=600)
    server: str = Field(default='', max_length=253)
    port: int = Field(default=49300, ge=1, le=65535)
    client_path: str = Field(default='', max_length=1000)

    @field_validator('web_url')
    @classmethod
    def valid_url(cls, value):
        if value:
            u = urlsplit(value)
            if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError('URL HTTPS sans identifiant, paramètres ni fragment requise.')
        return value

    @field_validator('server')
    @classmethod
    def valid_server(cls, value):
        if value and any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:' for c in value):
            raise ValueError('Saisir uniquement le nom ou l’adresse du serveur.')
        return value


def load():
    return PilotConfig.model_validate_json(FILE.read_text()) if FILE.exists() else PilotConfig()


def browser_url(config):
    """Use the official direct-login switch without saving session parameters."""
    return config.web_url + ('?login=true' if config.auth_route == 'direct' else '')


def client_info(config):
    path = Path(config.client_path).expanduser()
    if not config.client_path or not path.is_absolute() or path.suffix != '.app' or not path.is_dir():
        raise ValueError('Indiquer le chemin absolu du Client PRONOTE installé (.app).')
    path = path.resolve()
    try:
        info = plistlib.loads((path / 'Contents/Info.plist').read_bytes())
    except (OSError, plistlib.InvalidFileException):
        raise ValueError('Application macOS invalide.')
    name = str(info.get('CFBundleName', path.stem))
    if 'pronote' not in (name + path.name).casefold() or 'monoposte' in (name + path.name).casefold():
        raise ValueError('Choisir le Client PRONOTE réseau, pas Monoposte.')
    return {'client_path': str(path), 'target_bundle_path': str(path), 'target_bundle_id': str(info.get('CFBundleIdentifier', ''))}


def save(config):
    if config.connection_mode == 'web' and not config.web_url:
        raise ValueError('Renseigner l’URL HTTPS de l’espace professeur.')
    if config.connection_mode == 'local' and config.client_path:
        client_info(config)
    DATA.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=DATA, prefix='.pilot-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(config.model_dump(), stream, ensure_ascii=False, indent=2)
        os.replace(temporary, FILE)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return status()


def status():
    config = load()
    try:
        if config.connection_mode == 'local':
            client_info(config)
        elif not config.web_url:
            raise ValueError('Renseigner l’URL HTTPS de l’espace professeur.')
        ready, message = True, 'Client installé repéré. La connexion à l’établissement reste à effectuer dans PRONOTE.'
    except ValueError as error:
        ready, message = False, str(error)
    if config.connection_mode == 'web' and ready:
        message = 'Espace web configuré. Ouvrez le navigateur dédié puis connectez-vous dans PRONOTE ou l’ENT.'
    return {'config': config.model_dump(), 'client_ready': ready, 'message': message,
            'scope': 'Un professeur sur ce Mac ; aucune synchronisation des classes ou des notes.'}
