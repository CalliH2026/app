import plistlib
import pytest
from pydantic import ValidationError
from . import pilot


def test_config_rejects_credentials_and_tokens():
    for url in ('http://school.fr', 'https://user:pass@school.fr', 'https://school.fr/?token=secret', 'https://school.fr/#token'):
        with pytest.raises(ValidationError):
            pilot.PilotConfig(web_url=url)
    with pytest.raises(ValidationError):
        pilot.PilotConfig(password='secret')


def test_installed_client_and_private_config(tmp_path, monkeypatch):
    bundle=tmp_path/'Client PRONOTE.app'
    (bundle/'Contents').mkdir(parents=True)
    (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'Client PRONOTE','CFBundleIdentifier':'test.pronote'}))
    monkeypatch.setattr(pilot,'DATA',tmp_path)
    monkeypatch.setattr(pilot,'FILE',tmp_path/'pilot.json')
    config=pilot.PilotConfig(establishment='Collège test',client_path=str(bundle))
    assert pilot.save(config)['client_ready']
    assert pilot.load()==config
    assert pilot.FILE.stat().st_mode & 0o777 == 0o600
    assert pilot.client_info(config)['target_bundle_path']==str(bundle)
    (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'PRONOTE Monoposte'}))
    with pytest.raises(ValueError):pilot.client_info(config)


def test_stop_rejects_late_observation(tmp_path,monkeypatch):
    from . import native_bridge as bridge
    from starlette.requests import Request
    from fastapi import HTTPException
    token=tmp_path/'token';token.write_text('test')
    monkeypatch.setattr(bridge,'TOKEN_FILE',token)
    monkeypatch.setattr(bridge,'read_settings',lambda:{'enabled':False})
    request=Request({'type':'http','headers':[(b'authorization',b'Bearer test')]})
    with pytest.raises(HTTPException) as error:
        bridge.ingest(bridge.NativeContext(state='observed',visible_text='late private text'),request)
    assert error.value.status_code==409


def test_web_configuration_needs_url(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'DATA', tmp_path)
    monkeypatch.setattr(pilot, 'FILE', tmp_path/'pilot.json')
    with pytest.raises(ValueError):
        pilot.save(pilot.PilotConfig(connection_mode='web'))
    result=pilot.save(pilot.PilotConfig(connection_mode='web', web_url='https://school.test/pronote/professeur.html', client_path='/missing.app'))
    assert result['client_ready']


class FakeWebDriver:
    current_url = 'https://school.test/pronote/professeur.html?private=token'
    def execute_script(self, script):
        return {'login': False, 'text': 'Mathématiques\nContrôle 4e'}


def test_web_capture_origin_login_and_stop(monkeypatch):
    from . import pilot_web as web
    class Browser:
        driver = FakeWebDriver()
        destroyed = False
        def destroy(self): self.destroyed=True
    browser=Browser()
    monkeypatch.setattr(web,'BROWSER', browser)
    monkeypatch.setattr(web,'SOURCE', 'https://school.test/pronote/professeur.html')
    monkeypatch.setattr(web,'CONTEXT',None)
    browser.driver.current_url='https://ent.test/login'
    with pytest.raises(ValueError):web.capture()
    assert web.CONTEXT is None
    browser.driver.current_url=FakeWebDriver.current_url
    context=web.capture()
    assert context['visible_text']=='Mathématiques\nContrôle 4e'
    assert '?' not in context['source_url']
    browser.driver.execute_script=lambda script:{'login':True,'text':'secret'}
    with pytest.raises(ValueError):web.capture()
    assert 'secret' not in str(web.CONTEXT)
    web.stop()
    assert browser.destroyed and web.status()['context'] is None
    with pytest.raises(ValueError):web.capture()
