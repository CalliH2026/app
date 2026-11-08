"""Local, read-only PRONOTE connector using pronotepy's documented clients.

The password login is deliberately memory-only: export_credentials() contains the
real password in normal mode. Only mobile QR/token sessions may be remembered.
Teacher accounts use ClientBase (authentication/profile only), never student APIs.
No attachments, arbitrary links, messages, or remote editing functions are read.
"""
from __future__ import annotations

import copy
import datetime as dt
import importlib
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import socket
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from urllib.parse import unquote, urlsplit, urlunsplit
import uuid


# These are existing pronotepy.ent adapters, with explicitly bounded destinations.
# Unsupported SSO destinations are refused; a mobile QR is the portable alternative.
ENT_OPTIONS = {
    "cas_kosmos": ("Kosmos (CAS)", ("cas.kosmoseducation.com",)),
    "monbureaunumerique": ("Mon Bureau Numérique / EduConnect", ("cas.monbureaunumerique.fr", "educonnect.education.gouv.fr")),
    "eclat_bfc": ("Éclat BFC / EduConnect", ("cas.eclat-bfc.fr", "educonnect.education.gouv.fr")),
    "ent_auvergnerhonealpe": ("Auvergne-Rhône-Alpes / EduConnect", ("cas.ent.auvergnerhonealpes.fr", "educonnect.education.gouv.fr")),
    "occitanie_montpellier_educonnect": ("Occitanie Montpellier / EduConnect", ("cas.mon-ent-occitanie.fr", "educonnect.education.gouv.fr")),
    "occitanie_toulouse_edu": ("Occitanie Toulouse / EduConnect", ("cas.mon-ent-occitanie.fr", "educonnect.education.gouv.fr")),
    "ent77": ("ENT Seine-et-Marne", ("ent77.seine-et-marne.fr",)),
    "ile_de_france": ("Île-de-France (ENT)", ("ent.iledefrance.fr",)),
    "bordeaux": ("EduConnect via INDEX ÉDUCATION", ("hubeduconnect.index-education.net", "educonnect.education.gouv.fr")),
}
ACCOUNT_TYPES = {"teacher": "professeur", "student": "eleve", "parent": "parent"}
MAX_ITEMS = 250
MAX_CHILDREN = 12
MAX_REQUESTS = 32
MAX_BODY_BYTES = 8 * 1024 * 1024
OPERATION_SECONDS = 60
_TOKEN_QUERY = "fd=1&bydlg=A6ABB224-12DD-4E31-AD3E-8A39A1C2C335&login=true"
_TRANSPORT_LOCAL = threading.local()
_TRANSPORT_LOCK = threading.Lock()
_TRANSPORT_INSTALLED = False


class ConnectorError(ValueError):
    """A safe, user-facing failure; never constructed with remote exception text."""


class _LoginRequired(ConnectorError):
    pass


class _TransientError(Exception):
    pass


def connection_options():
    """Static capabilities; importing this module and listing options is offline."""
    options = {
        "available": True,
        "provider": "pronotepy",
        "unofficial": True,
        "account_types": [
            {"id": "teacher", "value": "teacher", "label": "Professeur", "capabilities": ["profile"],
             "description": "Connexion et profil uniquement ; classes et notes professeur non prises en charge."},
            {"id": "student", "value": "student", "label": "Élève", "capabilities": ["profile", "lessons", "homework", "grades"]},
            {"id": "parent", "value": "parent", "label": "Parent", "capabilities": ["profile", "children", "lessons", "homework", "grades"]},
        ],
        "auth_methods": [{"id": "password", "label": "Identifiant et mot de passe"}, {"id": "qr", "label": "QR mobile PRONOTE"}],
        "ents": [{"id": "", "value": "", "label": "Connexion PRONOTE directe"}] + [
            {"id": key, "value": key, "label": label} for key, (label, _) in ENT_OPTIONS.items()
        ],
        "remember_session": "QR / jeton mobile uniquement ; jamais le mot de passe du compte.",
        "read_only": True,
        "sync_window_days": 14,
    }
    options["accounts"] = options["account_types"]
    return options


def _host_name(value):
    if not isinstance(value, str) or not value or len(value) > 253:
        raise ConnectorError("Nom de serveur PRONOTE invalide.")
    try:
        host = value.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ConnectorError("Nom de serveur PRONOTE invalide.") from None
    if host.endswith(".") or "." not in host or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")
    ):
        raise ConnectorError("Un nom DNS public est requis pour PRONOTE.")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".home", ".lan", ".invalid", ".test")):
        raise ConnectorError("Les adresses locales ou privées sont refusées.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ConnectorError("Utilisez un nom DNS public, pas une adresse IP.")
    return host


def _public_addresses(host, resolver):
    host = _host_name(host)
    try:
        records = resolver(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise _TransientError() from None
    except ValueError:
        raise ConnectorError("Impossible de résoudre le serveur. Vérifiez l’adresse et Internet.") from None
    if not records:
        raise ConnectorError("Le serveur ne fournit aucune adresse publique.")
    for family, kind, _, _, address in records:
        try:
            ip = ipaddress.ip_address(address[0])
        except (ValueError, IndexError):
            raise ConnectorError("Adresse du serveur invalide.") from None
        if (family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM
                or address[1] != 443 or not ip.is_global or ip.is_multicast or "%" in address[0]):
            raise ConnectorError("Les serveurs locaux, privés ou de métadonnées sont refusés.")
        if (getattr(ip, "ipv4_mapped", None) is not None or getattr(ip, "sixtofour", None) is not None
                or getattr(ip, "teredo", None) is not None):
            raise ConnectorError("Adresse du serveur non prise en charge.")
    return records


def _parse_https(value, *, allow_query=False):
    if not isinstance(value, str) or not value or len(value) > 1200 or any(ord(c) < 33 for c in value):
        raise ConnectorError("Saisissez une URL HTTPS PRONOTE valide.")
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ConnectorError("Saisissez une URL HTTPS PRONOTE valide.") from None
    if (url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None
            or url.fragment or (url.query and not allow_query) or port not in (None, 443) or "\\" in value):
        raise ConnectorError("URL HTTPS sur le port 443, sans identifiant, paramètres ni fragment requise.")
    host = _host_name(url.hostname)
    decoded = unquote(url.path)
    if "%" in decoded or "\\" in decoded or any(part in (".", "..") for part in decoded.split("/")):
        raise ConnectorError("Chemin PRONOTE invalide.")
    return url, host


def validate_web_url(value, account_type, resolver=None):
    """Validate the URL and all current DNS answers before any authentication."""
    if account_type not in ACCOUNT_TYPES:
        raise ConnectorError("Choisissez un compte professeur, élève ou parent.")
    url, host = _parse_https(value)
    expected = ACCOUNT_TYPES[account_type] + ".html"
    if not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*pronote/(?:mobile\.)?" + re.escape(expected), url.path):
        raise ConnectorError("Indiquez l’URL directe de l’espace " + ACCOUNT_TYPES[account_type] + ".html.")
    _public_addresses(host, resolver or socket.getaddrinfo)
    return urlunsplit(("https", host, url.path, "", ""))


class _NetworkPolicy:
    def __init__(self, url, ent, resolver):
        parsed, self.host = _parse_https(url, allow_query=True)
        self.root_path = parsed.path.rsplit("/", 1)[0] + "/"
        self.ent_hosts = set(ENT_OPTIONS.get(ent, ("", ()))[1])
        self.resolver = resolver
        self.deadline = time.monotonic() + OPERATION_SECONDS
        self.requests = 0
        self.body_bytes = 0
        self.connections = 0
        self.sessions = set()

    def check_time(self):
        if time.monotonic() >= self.deadline:
            raise ConnectorError("Délai PRONOTE dépassé. Réessayez la synchronisation.")

    def check_url(self, url):
        self.check_time()
        parsed, host = _parse_https(url, allow_query=True)
        if host != self.host and host not in self.ent_hosts:
            raise ConnectorError("Redirection hors des serveurs PRONOTE et ENT autorisés refusée. Essayez un QR mobile.")
        if host == self.host and not parsed.path.startswith(self.root_path):
            raise ConnectorError("Requête en dehors de l’espace PRONOTE configuré refusée.")
        _public_addresses(host, self.resolver)
        self.requests += 1
        if self.requests > MAX_REQUESTS:
            raise ConnectorError("Limite de requêtes atteinte. Réessayez plus tard.")

    def connect_socket(self, address, timeout, source_address, socket_options):
        """Pin the actual TCP connection to a checked public DNS answer.

        TLS still verifies the original hostname: urllib3 wraps this socket using
        its original server_hostname. No second unvalidated DNS lookup occurs.
        """
        self.check_time()
        host, port = address
        host = host.decode("ascii") if isinstance(host, bytes) else host
        if port != 443 or (host != self.host and host not in self.ent_hosts):
            raise ConnectorError("Destination réseau PRONOTE refusée.")
        records = _public_addresses(host, self.resolver)
        self.connections += 1
        if self.connections > MAX_REQUESTS * 2:
            raise ConnectorError("Limite de connexions PRONOTE atteinte.")
        last_error = None
        for family, kind, protocol, _, sockaddr in records[:8]:
            self.check_time()
            connection = socket.socket(family, kind, protocol)
            try:
                for option in socket_options or ():
                    connection.setsockopt(*option)
                remaining = max(0.1, self.deadline - time.monotonic())
                connection.settimeout(min(timeout if isinstance(timeout, (int, float)) else 5, remaining, 5))
                if source_address:
                    connection.bind(source_address)
                connection.connect(sockaddr)
                return connection
            except OSError as error:
                last_error = error
                connection.close()
        raise last_error or ConnectorError("Connexion PRONOTE impossible.")


def _install_transport_guard():
    """Requests has no per-client hook before pronotepy's constructor logs in.

    These once-installed wrappers are inert outside this thread's connector
    context, and cover constructor, ENT forms, redirects and automatic refreshes.
    """
    global _TRANSPORT_INSTALLED
    with _TRANSPORT_LOCK:
        if _TRANSPORT_INSTALLED:
            return
        import requests.adapters
        import requests.sessions
        from urllib3.util import connection as urllib_connection

        original_send = requests.adapters.HTTPAdapter.send
        original_session_init = requests.sessions.Session.__init__
        original_connect = urllib_connection.create_connection

        def session_init(session):
            original_session_init(session)
            policy = getattr(_TRANSPORT_LOCAL, "policy", None)
            if policy is not None:
                session.trust_env = False
                session.max_redirects = 5
                policy.sessions.add(session)

        def send(adapter, request, **kwargs):
            policy = getattr(_TRANSPORT_LOCAL, "policy", None)
            if policy is None:
                return original_send(adapter, request, **kwargs)
            policy.check_url(request.url)
            kwargs.update(timeout=(5, 10), proxies={}, verify=True, stream=True)
            response = original_send(adapter, request, **kwargs)
            try:
                chunks = []
                for chunk in response.iter_content(65536):
                    policy.check_time()
                    policy.body_bytes += len(chunk)
                    if policy.body_bytes > MAX_BODY_BYTES:
                        raise ConnectorError("Réponse PRONOTE trop volumineuse. Synchronisation interrompue.")
                    chunks.append(chunk)
                response._content = b"".join(chunks)
                response._content_consumed = True
                return response
            except Exception:
                response.close()
                raise

        def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                              source_address=None, socket_options=None):
            policy = getattr(_TRANSPORT_LOCAL, "policy", None)
            if policy is None:
                return original_connect(address, timeout, source_address, socket_options)
            return policy.connect_socket(address, timeout, source_address, socket_options)

        requests.adapters.HTTPAdapter.send = send
        requests.sessions.Session.__init__ = session_init
        urllib_connection.create_connection = create_connection
        _TRANSPORT_INSTALLED = True


@contextmanager
def _network(policy):
    _install_transport_guard()
    previous = getattr(_TRANSPORT_LOCAL, "policy", None)
    _TRANSPORT_LOCAL.policy = policy
    try:
        yield
    except Exception:
        for session in policy.sessions:
            session.close()
        raise
    finally:
        _TRANSPORT_LOCAL.policy = previous


def _load_pronotepy():
    try:
        module = importlib.import_module("pronotepy")
    except ImportError:
        raise ConnectorError("Le connecteur PRONOTE n’est pas installé dans cette application.") from None
    # Upstream logs authentication payloads at DEBUG and usernames at INFO.
    for name in ("pronotepy", "pronotepy.pronoteAPI", "pronotepy.clients", "pronotepy.dataClasses",
                 "pronotepy.ent", "pronotepy.ent.generic_func", "pronotepy.ent.complex_ent"):
        logging.getLogger(name).disabled = True
    return module


def _text(value, limit=500):
    return str(value)[:limit] if value is not None else ""


def _subject(value):
    return _text(getattr(value, "name", ""), 160)


def _date(value):
    return value.isoformat() if isinstance(value, (dt.datetime, dt.date)) else _text(value, 40)


class PronoteConnector:
    def __init__(self, data_dir: Path, *, client_module=None, resolver=None):
        self.data_dir = Path(data_dir)
        self.session_file = self.data_dir / "pronote-session.json"
        self._module = client_module
        self._resolver = resolver or socket.getaddrinfo
        self._lock = threading.RLock()
        self._client = None
        self._config = {}
        self._state = "disconnected"
        self._message = "Aucun compte PRONOTE connecté."
        self._last_sync_at = None
        self._data = {}
        self._capabilities = []
        self._warnings = []
        self._remember = False
        self._retryable = False

    @staticmethod
    def connection_options():
        return connection_options()

    def status(self):
        with self._lock:
            return copy.deepcopy({
                "state": self._state, "message": self._message,
                "connected": self._client is not None and self._state in ("connected", "syncing"),
                "account_type": self._config.get("account_type"),
                "web_url": self._config.get("web_url", ""),
                "last_sync_at": self._last_sync_at, "data": self._data,
                "capabilities": self._capabilities, "warnings": self._warnings,
                "remembered_session": self.session_file.is_file(),
                "retryable": self._retryable,
                "read_only": True, "unofficial": True,
            })

    def _close_client(self):
        client, self._client = self._client, None
        self._dispose_client(client)

    def _periods(self):
        return getattr(getattr(self._module, "Period", None), "instances", set())

    def _dispose_client(self, client):
        if client:
            registry = self._periods()
            for period in list(registry):
                if getattr(period, "_client", None) is client:
                    registry.discard(period)
            try:
                client.communication.session.cookies.clear()
            except Exception:
                pass
            try:
                client.communication.session.close()
            except Exception:
                pass
            # Best effort to shorten secret lifetime in an otherwise discarded object.
            for key in ("password", "account_pin", "username", "auth_cookie"):
                try:
                    setattr(client, key, "" if key != "auth_cookie" else {})
                except Exception:
                    pass

    def _build_client(self, factory):
        # Upstream retains periods globally, including clients from a failed QR
        # login or the intermediate QR -> token conversion. Release those too.
        registry = self._periods()
        before = set(registry)
        result = None
        try:
            result = factory()
            return result
        finally:
            extras = set(registry) - before
            owners = {id(getattr(period, "_client", None)): getattr(period, "_client", None) for period in extras}
            for owner in owners.values():
                if owner is not result:
                    self._dispose_client(owner)

    def _clear(self, *, forget):
        self._close_client()
        self._config = {}
        self._last_sync_at, self._data = None, {}
        self._capabilities, self._warnings = [], []
        self._remember = False
        self._retryable = False
        if forget:
            try:
                self.session_file.unlink(missing_ok=True)
            except OSError:
                raise ConnectorError("Impossible d’effacer le jeton local de reconnexion.") from None

    def close(self):
        with self._lock:
            self._clear(forget=False)
            self._state, self._message = "disconnected", "Session PRONOTE fermée."
            return self.status()

    def disconnect(self):
        with self._lock:
            self._clear(forget=True)
            self._state, self._message = "disconnected", "Compte déconnecté et jeton local effacé."
            return self.status()

    def _client_class(self, account):
        module = self._module or _load_pronotepy()
        self._module = module
        return getattr(module, {"student": "Client", "parent": "ParentClient", "teacher": "ClientBase"}[account])

    def _failure(self, *, login=False, retryable=False, preserve_client=False):
        try:
            self._persist_token()
        except Exception:
            pass
        if not preserve_client:
            self._close_client()
        self._retryable = retryable
        self._state = "needs_login" if login else "error"
        self._message = ("Connexion PRONOTE impossible ou expirée. Vérifiez le compte, le QR et l’authentification ENT."
                         if login else "Synchronisation PRONOTE interrompue. Vérifiez Internet puis reconnectez-vous.")
        return self.status()

    def connect(self, config: dict):
        with self._lock:
            self._clear(forget=True)
            self._state, self._message = "connecting", "Connexion à PRONOTE…"
            try:
                if not isinstance(config, dict):
                    raise ConnectorError("Configuration de connexion invalide.")
                account = config.get("account_type", "teacher")
                method = config.get("auth_method", "password")
                ent = config.get("ent", "") or ""
                if method not in ("password", "qr") or ent not in ("", *ENT_OPTIONS):
                    raise ConnectorError("Méthode de connexion ou ENT non pris en charge. Essayez le QR mobile.")
                web_url = validate_web_url(config.get("web_url", ""), account, self._resolver)
                self._config = {"account_type": account, "web_url": web_url, "ent": ent}
                self._remember = config.get("remember_session", False) is True
                client_type = self._client_class(account)
                policy = _NetworkPolicy(web_url, ent, self._resolver)
                with _network(policy):
                    if method == "password":
                        username, password = config.get("username"), config.get("password")
                        if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
                            raise ConnectorError("Renseignez l’identifiant et le mot de passe PRONOTE ou ENT.")
                        if len(username) > 500 or len(password) > 2000:
                            raise ConnectorError("Identifiants PRONOTE invalides.")
                        ent_module = getattr(self._module, "ent", None)
                        adapter = getattr(ent_module or importlib.import_module("pronotepy.ent"), ent) if ent else None
                        login_url = web_url if ent else web_url + "?login=true"
                        self._client = self._build_client(lambda: client_type(login_url, username=username, password=password, ent=adapter))
                        if self._remember:
                            self._warnings.append("Le mot de passe reste uniquement en mémoire. Pour la reconnexion automatique après fermeture, utilisez un QR mobile.")
                    else:
                        qr = config.get("qr_code")
                        if isinstance(qr, str) and len(qr) <= 12000:
                            try:
                                qr = json.loads(qr)
                            except (TypeError, ValueError):
                                raise ConnectorError("Le contenu du QR doit être un objet JSON PRONOTE.") from None
                        if not isinstance(qr, dict) or any(not isinstance(qr.get(k), str) for k in ("url", "login", "jeton")):
                            raise ConnectorError("QR PRONOTE incomplet : url, login et jeton requis.")
                        qr_url = validate_web_url(qr["url"], account, self._resolver)
                        if qr_url.replace("/mobile.", "/") != web_url.replace("/mobile.", "/"):
                            raise ConnectorError("Le QR doit correspondre à l’espace PRONOTE et au type de compte choisis.")
                        if any(not re.fullmatch(r"[A-Fa-f0-9]{32,8192}", qr[k]) for k in ("login", "jeton")):
                            raise ConnectorError("Le contenu du QR PRONOTE est invalide.")
                        pin = config.get("pin", "")
                        if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{4}", pin):
                            raise ConnectorError("Renseignez le code à 4 chiffres choisi pour ce QR.")
                        self._client = self._build_client(lambda: client_type.qrcode_login(
                            {"url": qr_url, "login": qr["login"], "jeton": qr["jeton"]},
                            pin, uuid=str(uuid.uuid4()), device_name="PRONOTE local",
                        ))
                    if not self._client.logged_in:
                        return self._failure(login=True)
                    self._state = "connected"
                    self._persist_token()
                    return self._sync(policy)
            except _LoginRequired:
                return self._failure(login=True)
            except (OSError, _TransientError):
                return self._failure(retryable=self.session_file.is_file())
            except ConnectorError as error:
                self._close_client()
                self._state, self._message = "error", str(error)
                return self.status()
            except Exception:
                return self._failure(login=True)

    def _persist_token(self):
        if not self._remember or getattr(self._client, "login_mode", None) != "token":
            return
        # NEVER call export_credentials for a normal password login.
        credentials = self._client.export_credentials()
        if not all(isinstance(credentials.get(k), str) and credentials[k] for k in ("pronote_url", "username", "password", "uuid")):
            raise ConnectorError("Ce compte ne fournit pas de jeton de reconnexion utilisable.")
        token_url = self._token_url(credentials["pronote_url"], self._config["web_url"], self._config["account_type"])
        saved = {"version": 1, "account_type": self._config["account_type"],
                 "web_url": self._config["web_url"], "token_url": token_url,
                 "username": credentials["username"], "token": credentials["password"],
                 "uuid": credentials["uuid"], "client_identifier": credentials.get("client_identifier")}
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".pronote-session-", dir=self.data_dir)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            else:
                os.chmod(name, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(saved, stream, ensure_ascii=False)
            os.replace(name, self.session_file)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _token_url(self, value, web_url, account):
        parsed, host = _parse_https(value, allow_query=True)
        mobile_url = validate_web_url(urlunsplit(("https", host, parsed.path, "", "")), account, self._resolver)
        if mobile_url.replace("/mobile.", "/") != web_url.replace("/mobile.", "/"):
            raise ConnectorError("Jeton local associé à un autre espace PRONOTE.")
        # Only documented upstream transport flags are accepted; no untrusted
        # query string from a file or server is replayed during reconnection.
        return mobile_url + "?" + _TOKEN_QUERY

    def _read_saved(self):
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.session_file, flags)
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                info = os.fstat(stream.fileno())
                invalid_permissions = os.name != "nt" and (info.st_mode & 0o077 or info.st_uid != os.getuid())
                if not stat.S_ISREG(info.st_mode) or invalid_permissions or info.st_size > 32000:
                    raise ConnectorError("Le fichier de reconnexion n’est pas privé ou valide. Reconnectez-vous.")
                return json.load(stream)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            raise ConnectorError("Le jeton local est illisible. Reconnectez-vous.") from None

    def resume(self):
        with self._lock:
            if self._client is not None:
                return self.status()
            self._clear(forget=False)
            try:
                saved = self._read_saved()
                if saved is None:
                    self._state, self._message = "disconnected", "Aucun jeton de reconnexion enregistré."
                    return self.status()
                if not isinstance(saved, dict) or saved.get("version") != 1:
                    raise ConnectorError("Jeton local incompatible. Reconnectez-vous.")
                account = saved.get("account_type")
                web_url = validate_web_url(saved.get("web_url"), account, self._resolver)
                token_url = self._token_url(saved.get("token_url"), web_url, account)
                for field in ("username", "token", "uuid"):
                    if not isinstance(saved.get(field), str) or not saved[field] or len(saved[field]) > 12000:
                        raise ConnectorError("Jeton local incomplet. Reconnectez-vous.")
                self._config = {"account_type": account, "web_url": web_url, "ent": ""}
                self._remember = True
                self._state, self._message = "connecting", "Reconnexion à PRONOTE…"
                policy = _NetworkPolicy(web_url, "", self._resolver)
                with _network(policy):
                    client_type = self._client_class(account)
                    self._client = self._build_client(lambda: client_type.token_login(
                        pronote_url=token_url, username=saved["username"], password=saved["token"],
                        uuid=saved["uuid"], client_identifier=saved.get("client_identifier"),
                        device_name="PRONOTE local",
                    ))
                    if not self._client.logged_in:
                        return self._failure(login=True)
                    self._persist_token()  # PRONOTE rotates mobile tokens on every login.
                    self._state = "connected"
                    return self._sync(policy)
            except _LoginRequired:
                return self._failure(login=True)
            except (OSError, _TransientError):
                return self._failure(retryable=True)
            except ConnectorError as error:
                self._close_client()
                self._state, self._message = "needs_login", str(error)
                return self.status()
            except Exception:
                return self._failure(login=True)

    def sync(self):
        with self._lock:
            if self._client is None:
                if self.session_file.is_file():
                    return self.resume()
                self._state, self._message = "needs_login", "Connectez un compte PRONOTE avant de synchroniser."
                return self.status()
            policy = _NetworkPolicy(self._config["web_url"], self._config.get("ent", ""), self._resolver)
            try:
                with _network(policy):
                    try:
                        self._client.session_check()
                    except Exception as error:
                        if type(error).__name__ in ("CryptoError", "QRCodeDecryptError", "MFAError", "ENTLoginError") or getattr(error, "pronote_error_code", None) == 10:
                            raise _LoginRequired() from None
                        raise
                    active_periods = getattr(self._client, "periods_", None)
                    if active_periods is not None:
                        for period in list(self._periods()):
                            if getattr(period, "_client", None) is self._client and period not in active_periods:
                                self._periods().discard(period)
                    return self._sync(policy)
            except _LoginRequired:
                return self._failure(login=True)
            except Exception:
                return self._failure(retryable=True, preserve_client=True)

    def _sync(self, policy):
        self._state, self._message = "syncing", "Lecture des données PRONOTE…"
        client = self._client
        if not getattr(client, "logged_in", False):
            return self._failure(login=True)
        today = dt.datetime.now().astimezone().date()
        end = today + dt.timedelta(days=14)
        info = client.info
        profile = {key: _text(getattr(info, key, ""), 200) for key in ("name", "class_name", "establishment")}
        data = {"profile": profile, "children": [], "lessons": [], "homework": [], "grades": [],
                "window": {"from": today.isoformat(), "to": end.isoformat()}}
        capabilities = ["profile"]
        warnings = [w for w in self._warnings if "mot de passe" in w]
        account = self._config["account_type"]
        if account == "teacher":
            warnings.append("Profil professeur uniquement : le connecteur ne prend pas en charge la synchronisation des classes, notes ou cours professeur.")
        else:
            if account == "parent":
                for child in list(client.children)[:MAX_CHILDREN]:
                    data["children"].append({"name": _text(child.name, 200), "class_name": _text(child.class_name, 160)})
                capabilities.append("children")
                # The library selects the first child at login; explicitly reselect
                # it on every sync so the snapshot can never mix siblings.
                if client.children:
                    client.set_child(client.children[0])
                    data["selected_child"] = _text(client.children[0].name, 200)
                    warnings.append("Les cours, devoirs et notes concernent le premier enfant du compte.")
            readers = (
                ("lessons", lambda: [
                    {"subject": _subject(item.subject), "start": _date(item.start), "end": _date(item.end),
                     "classroom": _text(item.classroom, 160), "teacher": _text(item.teacher_name, 200),
                     "canceled": bool(item.canceled)}
                    for item in client.lessons(today, end)[:MAX_ITEMS]
                ]),
                ("homework", lambda: [
                    {"subject": _subject(item.subject), "date": _date(item.date),
                     "description": _text(item.description, 4000), "done": bool(item.done)}
                    for item in client.homework(today, end)[:MAX_ITEMS]
                ]),
                ("grades", lambda: [
                    {"subject": _subject(item.subject), "date": _date(item.date), "grade": _text(item.grade, 40),
                     "out_of": _text(item.out_of, 40), "coefficient": _text(item.coefficient, 40),
                     "comment": _text(item.comment, 1000)}
                    for item in client.current_period.grades[:MAX_ITEMS]
                ]),
            )
            for key, reader in readers:
                policy.check_time()
                try:
                    data[key] = reader()
                    capabilities.append(key)
                except ConnectorError:
                    raise
                except Exception as error:
                    if (type(error).__name__ in ("CryptoError", "QRCodeDecryptError", "MFAError", "ENTLoginError")
                            or getattr(error, "pronote_error_code", None) == 10 or not client.logged_in):
                        raise _LoginRequired() from None
                    if isinstance(error, OSError):
                        raise _TransientError() from None
                    unsupported = isinstance(error, (AttributeError, KeyError, IndexError)) or type(error).__name__ in (
                        "UnsupportedOperation", "DataError", "ParsingError", "DateParsingError")
                    if type(error).__name__ == "PronoteAPIError" and "Action not permitted" in str(error):
                        unsupported = True
                    if not unsupported:
                        raise _TransientError() from None
                    warnings.append({"lessons": "Emploi du temps", "homework": "Devoirs", "grades": "Notes"}[key] + " indisponibles pour ce compte ou cette version de PRONOTE.")
        data["counts"] = {key: len(data[key]) for key in ("children", "lessons", "homework", "grades")}
        self._persist_token()  # Also catches token rotation after an automatic refresh.
        self._data, self._capabilities, self._warnings = data, capabilities, warnings
        self._last_sync_at = dt.datetime.now().astimezone().isoformat()
        self._state = "connected"
        self._retryable = False
        self._message = ("Compte professeur connecté ; profil lu. Les classes et notes professeur ne sont pas prises en charge."
                         if account == "teacher" else "Données PRONOTE synchronisées en lecture seule.")
        return self.status()
