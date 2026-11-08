"""Local-only web pilot, sharing the desktop event loop with Playwright."""
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from ..pilot import PilotConfig, load, save, browser_url
from ..browser_text import READ_VISIBLE
from datetime import datetime

ASSETS = Path(__file__).parent

class Setup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    establishment: str = Field(default='', max_length=160)
    web_url: str = Field(max_length=600)
    auth_route: Literal['direct', 'ent'] = 'ent'

class Confirmation(BaseModel):
    authenticated: bool = False

class PilotBrowser:
    def __init__(self, browser):
        self.browser = browser
        self.context = None
        self.page = None
        self.source = ''
        self.observation = None

    async def stop(self):
        context, self.context = self.context, None
        self.page, self.source, self.observation = None, '', None
        if context:
            await context.close()

    async def start(self, url):
        await self.stop()
        self.context = await self.browser.new_context(accept_downloads=False, locale='fr-FR')
        self.context.on('page', self.track_page)
        self.source = url
        self.page = await self.context.new_page()
        try:
            await self.page.goto(url, wait_until='domcontentloaded', timeout=45000)
            await self.page.bring_to_front()
        except Exception:
            await self.stop()
            raise ValueError('Impossible d’ouvrir cette adresse. Vérifiez l’URL et la connexion Internet.')

    def track_page(self, page):
        self.page = page

    async def capture(self):
        if not self.context:
            raise ValueError('Ouvrez d’abord votre espace PRONOTE.')
        pages = [p for p in self.context.pages if not p.is_closed()]
        if not pages:
            raise ValueError('La fenêtre PRONOTE a été fermée. Ouvrez-la à nouveau.')
        page = self.page if self.page in pages else pages[-1]
        expected, actual = urlsplit(self.source), urlsplit(page.url)
        if (actual.scheme, actual.hostname, actual.port) != (expected.scheme, expected.hostname, expected.port):
            raise ValueError('Terminez la connexion ENT puis revenez dans l’espace PRONOTE configuré.')
        data = await page.evaluate('() => {' + READ_VISIBLE + '}')
        after = urlsplit(page.url)
        if (after.scheme, after.hostname, after.port, after.path) != (actual.scheme, actual.hostname, actual.port, actual.path):
            raise ValueError('La page a changé pendant le relevé. Revenez dans PRONOTE puis réessayez.')
        if data.get('login'):
            raise ValueError('Écran de connexion détecté. Connectez-vous avant de relever la vue.')
        text = data.get('text', '').strip()
        if not text:
            raise ValueError('Cette vue ne fournit pas de texte lisible. Essayez une autre vue.')
        self.observation = {'visible_text': text, 'source_url': f'{actual.scheme}://{actual.netloc}{actual.path}',
                            'observed_at': datetime.now().astimezone().isoformat()}
        return self.observation


def create_app(runtime, origin):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    token = secrets.token_urlsafe(32)

    from ..pronote_connection import ConnectionManager, install_routes
    from ..pilot import DATA
    connection = ConnectionManager(DATA)
    app.state.pronote_connection = connection
    install_routes(app, connection)

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        if request.headers.get('host') != urlsplit(origin).netloc:
            return JSONResponse({'detail': 'Hôte refusé'}, status_code=403)
        if request.method != 'GET' and request.headers.get('origin') != origin:
            return JSONResponse({'detail': 'Origine refusée'}, status_code=403)
        if request.url.path.startswith('/api/') and not secrets.compare_digest(request.cookies.get('pilot_session', ''), token):
            return JSONResponse({'detail': 'Ouvrez le pilote depuis son application.'}, status_code=401)
        return await call_next(request)

    @app.get('/')
    def home():
        response = FileResponse(ASSETS/'pilot.html')
        response.set_cookie('pilot_session', token, httponly=True, samesite='strict')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/pilot.js')
    def script():
        return FileResponse(ASSETS/'pilot.js', media_type='text/javascript')

    @app.get('/api/config')
    def config():
        config = load()
        return {'establishment': config.establishment, 'web_url': config.web_url,
                'auth_route': config.auth_route}

    @app.post('/api/connect')
    async def connect(body: Setup):
        try:
            config = PilotConfig(connection_mode='web', **body.model_dump())
            save(config)
            await runtime.start(browser_url(config))
        except ValueError as error:
            raise HTTPException(400, str(error))
        except Exception:
            raise HTTPException(503, 'Le navigateur ne répond plus. Fermez puis rouvrez l’application.')
        return {'message': 'Connectez-vous dans la fenêtre PRONOTE, puis ouvrez la vue à tester.'}

    @app.post('/api/capture')
    async def capture(body: Confirmation):
        if not body.authenticated:
            raise HTTPException(400, 'Confirmez que vous êtes connecté et que la vue utile est ouverte.')
        try:
            return await runtime.capture()
        except ValueError as error:
            raise HTTPException(409, str(error))
        except Exception:
            raise HTTPException(503, 'Lecture interrompue. Revenez sur PRONOTE et réessayez.')

    @app.post('/api/stop')
    async def stop():
        await runtime.stop()
        return {'message': 'Session fermée et relevé effacé. Vous pouvez fermer cette fenêtre.'}

    return app
