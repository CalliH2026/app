"""Google OIDC login; the hosted pilot is restricted to explicitly allowed accounts."""
import os
import secrets
from urllib.parse import urlparse
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from .integrations import key
from .outing_checkout_routes import is_stripe_webhook


def install_auth(app):
    public = os.getenv('PUBLIC_URL', '').rstrip('/')
    hosted = bool(public)
    secret = os.getenv('SESSION_SECRET', '')
    sites_proxy_token = os.getenv('SITES_PROXY_TOKEN', '')
    allowed = {email.strip().lower() for email in os.getenv('ALLOWED_EMAILS', '').split(',') if email.strip()}
    if hosted and (not public.startswith('https://') or len(secret) < 32 or not allowed):
        raise RuntimeError('PUBLIC_URL HTTPS, SESSION_SECRET (32+ caractères) et ALLOWED_EMAILS requis.')
    oauth = OAuth()
    try:
        client_id, client_secret = key('GOOGLE_CLIENT_ID'), key('GOOGLE_CLIENT_SECRET')
    except RuntimeError:
        client_id = client_secret = ''
    if hosted and not client_id:
        raise RuntimeError('Configuration Google OAuth requise.')
    oauth.register('google', client_id=client_id, client_secret=client_secret,
                   server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                   client_kwargs={'scope': 'openid email profile'})

    @app.get('/healthz')
    async def health():
        return {'status': 'ok'}

    @app.get('/login')
    async def login_page():
        return HTMLResponse('''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connexion · New PRONOTE</title><link rel="stylesheet" href="/static/workspace.css"><body class="login-page"><main class="login-card"><img class="calli-symbol" src="/static/brand/calli-symbol.svg" alt="Calli, votre assistant"><h1>Votre espace professeur</h1><p>Connectez-vous pour retrouver New PRONOTE et votre assistant Calli.</p><a class="button primary" href="/auth/google">Continuer avec Google</a><p>Connexion avec votre compte Google · espace de démonstration partagé.</p><a href="/privacy">Confidentialité</a></main></body></html>''')

    from fastapi import Request

    @app.get('/privacy')
    async def privacy():
        return HTMLResponse('<!doctype html><html lang="fr"><meta charset="utf-8"><title>Confidentialité · New PRONOTE</title><main><h1>Confidentialité du pilote New PRONOTE</h1><p>Concept indépendant de démonstration, hébergé sur Microsoft Azure.</p><p>La connexion Google utilise votre identifiant Google, votre nom et votre adresse e-mail vérifiée pour ouvrir une session. Ces informations sont conservées dans un cookie signé, HttpOnly et sécurisé, pendant huit heures au maximum. Déconnectez-vous pour supprimer ce cookie. Le pilote ne demande aucun accès à votre Gmail ou à vos fichiers Google.</p><p>Les données scolaires affichées sont fictives et partagées entre les utilisateurs. Les rapports produits sont également partagés. Ne saisissez aucune donnée personnelle ou scolaire réelle. L’import audio et la connexion au calendrier personnel sont désactivés sur ce serveur.</p><p>Les préparations connectées peuvent utiliser H Company, Gladia et Linkup sur le dossier fictif. Les sorties scolaires utilisent aussi OSRM pour calculer un trajet entre des points publics du scénario fictif ; aucun nom d’élève n’est envoyé à ce service. Les journaux techniques de l’hébergeur peuvent contenir des métadonnées de requêtes telles que l’adresse IP. Aucun outil publicitaire ni de suivi analytique n’est ajouté par cette application. Pour toute demande de suppression, contactez l’administrateur du pilote.</p><a href="/login">Connexion</a></main></html>')

    @app.get('/auth/google')
    async def google_login(request: Request):
        if not client_id:
            return HTMLResponse('Connexion Google non configurée.', status_code=503)
        redirect = (public or str(request.base_url).rstrip('/')) + '/auth/callback'
        return await oauth.google.authorize_redirect(request, redirect, prompt='select_account')

    @app.get('/auth/callback')
    async def google_callback(request: Request):
        try:
            token = await oauth.google.authorize_access_token(request)
            user = token.get('userinfo', {})
            email = user.get('email', '').lower()
            if not user.get('sub') or user.get('email_verified') is not True or (allowed and '*' not in allowed and email not in allowed):
                request.session.clear()
                return HTMLResponse('Ce compte ne dispose pas d’accès au pilote.', status_code=403)
            request.session.clear()
            request.session['user'] = {'sub': user['sub'], 'email': email, 'name': user.get('name', email)}
            return RedirectResponse('/', status_code=303)
        except (OAuthError, ValueError):
            request.session.clear()
            return HTMLResponse('Connexion expirée ou refusée. <a href="/login">Réessayer</a>', status_code=400)

    @app.get('/api/auth/me')
    async def me(request: Request):
        if getattr(request.state, 'sites_public_poc', False):
            return {'user': {'sub': 'sites-public-poc', 'email': 'poc@example.invalid',
                             'name': 'Démo publique partagée'}, 'required': False}
        return {'user': request.session.get('user'), 'required': hosted}

    @app.post('/auth/logout')
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse('/login', status_code=303)

    @app.middleware('http')
    async def hosted_access(request: Request, call_next):
        if hosted:
            path = request.url.path
            if request.headers.get('host', '').lower() != urlparse(public).netloc.lower():
                return HTMLResponse('Hôte refusé', status_code=403)
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and not is_stripe_webhook(request):
                if request.headers.get('origin') != public:
                    return JSONResponse({'detail': 'Origine refusée'}, status_code=403)
            # Dedicated server-to-server access for the public, fictional-data POC.
            # Never accept a browser identity or mint a reusable session cookie here.
            proxy_access = bool(len(sites_proxy_token) >= 32 and secrets.compare_digest(
                request.headers.get('x-pronote-sites-token', ''), sites_proxy_token))
            request.state.sites_public_poc = proxy_access
            if not is_stripe_webhook(request) and path != '/healthz' and not path.startswith(('/static/', '/auth/')) and path not in ('/login', '/privacy'):
                if not proxy_access and not request.session.get('user'):
                    if path.startswith('/api/'):
                        return JSONResponse({'detail': 'Connexion requise'}, status_code=401)
                    return RedirectResponse('/login', status_code=303)
            # Desktop integrations and the globally shared Calendar token store stay local.
            if path.startswith(('/native', '/pilot', '/api/native', '/api/pilot', '/api/pronote/connection', '/api/recordings/native', '/api/calendar', '/api/notifications', '/api/audio')):
                return JSONResponse({'detail': 'Cette fonction nécessite le compagnon local.'}, status_code=409)
        response = await call_next(request)
        if hosted and not request.url.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    # Session must wrap the access middleware, so request.session exists there.
    app.add_middleware(SessionMiddleware, secret_key=secret or 'local-development-session-only',
                       session_cookie='pronote_session', https_only=hosted, same_site='lax', max_age=28800)
