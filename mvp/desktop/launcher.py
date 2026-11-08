"""Frozen desktop entry point. Python and Chromium are bundled, not installed."""
import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys


def default_data_dir():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'PronotePilot'
    return Path.home()/'Library/Application Support/PronotePilot'


def browser_directory():
    if not getattr(sys, 'frozen', False):
        return '0'
    executable = Path(sys.executable)
    if sys.platform == 'win32':
        return str(executable.parent/'browsers')
    return str(executable.parent.parent/'Resources/browsers')


def acquire_lock(stream):
    if sys.platform == 'win32':
        import msvcrt
        stream.seek(0)
        if not stream.read(1):
            stream.write('0')
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


def alert(message):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, 'PRONOTE · Pilote professeur', 0x40)
    else:
        # Pass the message as argv rather than interpolating AppleScript source.
        subprocess.run(['osascript', '-e', 'on run argv\ndisplay dialog (item 1 of argv) with title "PRONOTE · Pilote professeur" buttons {"OK"} default button "OK"\nend run', message], capture_output=True)


async def run():
    import uvicorn
    from playwright.async_api import async_playwright
    from mvp.desktop.server import PilotBrowser, create_app
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    origin = f'http://127.0.0.1:{sock.getsockname()[1]}'
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless='--smoke-test' in sys.argv, channel='chromium', chromium_sandbox=True)
        runtime = PilotBrowser(browser)
        app = create_app(runtime, origin)
        connection = app.state.pronote_connection
        server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, loop='asyncio', lifespan='off'))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError('Le serveur local n’a pas démarré.')
                await asyncio.sleep(.05)
            connection.start()
            context = await browser.new_context(locale='fr-FR')
            page = await context.new_page()
            finished = asyncio.Event()
            page.on('close', lambda _: finished.set())
            browser.on('disconnected', lambda _: finished.set())
            await page.goto(origin)
            if '--smoke-test' in sys.argv:
                # Exercise the packaged browser and HTTP API without a real school.
                assert await page.locator('h1').inner_text() == 'Connectez votre PRONOTE'
                result = await page.evaluate("fetch('/api/config').then(r=>r.json())")
                assert 'web_url' in result
                # The optional connector and crypto dependencies must also be bundled.
                from mvp.pronote_connector import _load_pronotepy
                assert callable(_load_pronotepy().ClientBase)
                options = await page.evaluate("fetch('/api/pronote/connection/options').then(r=>r.json())")
                assert options['available'] and any(item['id'] == 'teacher' for item in options['accounts'])
                # Reject a private destination without contacting any real school.
                rejected = await page.evaluate("fetch('/api/pronote/connection/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({web_url:'https://127.0.0.1/pronote/professeur.html',password:'smoke-private-password',username:'smoke-user'})}).then(r=>r.json())")
                assert rejected['state'] == 'error' and not rejected['connected']
                assert 'smoke-private-password' not in str(rejected)
                await page.evaluate("fetch('/api/pronote/connection/disconnect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})")
                await page.route('https://pilot.example/**', lambda route: route.fulfill(content_type='text/html', body='<meta charset="utf-8"><h1>Évaluation de mathématiques</h1><input value="private-user"><textarea>private-draft</textarea>'))
                # Separate school context: route its requests locally as well.
                async def test_start(url):
                    await runtime.stop()
                    runtime.context = await browser.new_context()
                    runtime.source = url
                    await runtime.context.route('https://pilot.example/**', lambda route: route.fulfill(content_type='text/html', body='<meta charset="utf-8"><h1>Évaluation de mathématiques</h1><input value="private-user"><textarea>private-draft</textarea>'))
                    runtime.page = await runtime.context.new_page()
                    await runtime.page.goto(url)
                runtime.start = test_start
                response = await page.evaluate("fetch('/api/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({establishment:'Test',web_url:'https://pilot.example/pronote/professeur.html'})}).then(r=>r.json())")
                assert 'message' in response, response
                result = await page.evaluate("fetch('/api/capture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({authenticated:true})}).then(r=>r.json())")
                assert 'Évaluation' in result['visible_text'] and 'private-' not in result['visible_text'], result
                await page.evaluate("fetch('/api/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})")
                assert runtime.observation is None
                (Path(os.environ['PRONOTE_PILOT_DATA'])/'smoke-test-ok').write_text('Bundled Python + Chromium + PRONOTE connector + local UI + capture + stop passed.\n')
                finished.set()
            await finished.wait()
        finally:
            server.should_exit = True
            await task
            connection.close()
            await runtime.stop()
            await browser.close()
            sock.close()


def main():
    data = Path(os.environ.get('PRONOTE_PILOT_DATA', default_data_dir()))
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ['PRONOTE_PILOT_DATA'] = str(data)
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = browser_directory()
    lock = (data/'application.lock').open('a+')
    try:
        acquire_lock(lock)
    except (BlockingIOError, OSError):
        alert('Le pilote est déjà ouvert. Retrouvez sa fenêtre PRONOTE · Pilote professeur.')
        return
    try:
        asyncio.run(run())
    except Exception as error:
        # No page content, credentials or user URL in the diagnostic file.
        (data/'startup-error.txt').write_text(type(error).__name__)
        if '--smoke-test' in sys.argv:
            import traceback
            (data/'smoke-test-failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
            raise SystemExit(1)
        alert('Le pilote n’a pas pu démarrer. Fermez-le puis réessayez. Si le problème persiste, transmettez le fichier startup-error.txt du dossier '+str(data)+' à la personne qui organise le test.')
    finally:
        lock.close()


if __name__ == '__main__':
    main()
