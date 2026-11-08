"""User-driven PRONOTE browser. No agent, credentials or browser profile export."""
import threading
from datetime import datetime
from urllib.parse import urlsplit
from .pilot import load, browser_url

LOCK = threading.RLock()
BROWSER = None
SOURCE = ''
CONTEXT = None

from .browser_text import READ_VISIBLE


def stop():
    global BROWSER, SOURCE, CONTEXT
    with LOCK:
        browser, BROWSER = BROWSER, None
        SOURCE = ''
        CONTEXT = None
        if browser:
            browser.destroy()


def start():
    global BROWSER, SOURCE, CONTEXT
    config = load()
    if config.connection_mode != 'web' or not config.web_url:
        raise ValueError('Enregistrer le mode web et l’URL de l’espace professeur.')
    with LOCK:
        stop()
        from hai_drivers.web.selenium import SeleniumWebDriver
        browser = SeleniumWebDriver(disable_sandbox=False, disable_security=False, lang='fr-FR')
        try:
            browser.driver.get(browser_url(config))
        except Exception:
            browser.destroy()
            raise RuntimeError('Impossible d’ouvrir l’espace professeur dans le navigateur dédié.')
        BROWSER, SOURCE, CONTEXT = browser, config.web_url, None
    return {'message': 'Navigateur dédié ouvert. Connectez-vous directement dans PRONOTE ou votre ENT, ouvrez la vue utile puis cliquez sur Relever la vue web.'}


def status():
    with LOCK:
        return {'active': BROWSER is not None, 'context': CONTEXT,
                'message': 'Lecture manuelle uniquement ; aucune synchronisation automatique.'}


def capture():
    global CONTEXT
    with LOCK:
        if BROWSER is None:
            raise ValueError('Ouvrir d’abord le navigateur dédié.')
        driver = BROWSER.driver
        # Match the exact configured origin, never an ENT or another tab/site.
        expected, current = urlsplit(SOURCE), urlsplit(driver.current_url)
        if (current.scheme, current.hostname, current.port) != (expected.scheme, expected.hostname, expected.port):
            raise ValueError('Revenir dans l’espace PRONOTE configuré après la connexion ENT. Aucune lecture effectuée.')
        data = driver.execute_script(READ_VISIBLE)
        after = urlsplit(driver.current_url)
        if (after.scheme, after.hostname, after.port, after.path) != (current.scheme, current.hostname, current.port, current.path):
            raise ValueError('La page a changé pendant le relevé. Revenez dans PRONOTE puis réessayez.')
        if data.get('login'):
            raise ValueError('Écran de connexion détecté. Terminer la connexion avant le relevé.')
        text = data.get('text', '').strip()
        if not text:
            raise ValueError('Aucun texte visible récupérable. Cette vue peut utiliser une iframe ou un dessin non lisible.')
        CONTEXT = {'state': 'observed', 'source_kind': 'pronote_web', 'method': 'visible_dom',
                   'source_url': f'{current.scheme}://{current.netloc}{current.path}',
                   'observed_at': datetime.now().astimezone().isoformat(), 'visible_text': text,
                   'limitations': ['Texte visible uniquement, sans pièces jointes ni contenu des iframes.',
                                   'La connexion et le caractère pédagogique du relevé restent à vérifier par le professeur.']}
        return CONTEXT
