"""Select the imported demo base without launching PRONOTE or changing real data."""
import json
import plistlib
import shlex

import pytest

from mvp.native import prepare_demo as demo


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    data=tmp_path/'data'
    program=data/'bottle/drive_c/H-Demo/PRONOTE'
    program.mkdir(parents=True)
    fallback=program/'Base-Exemple/Base Exemple.not'
    fallback.parent.mkdir()
    fallback.write_bytes(b'explicit test example')
    archived=program/'Exemples/Base Exemple PRONOTE 2026_Archive.not'
    archived.parent.mkdir()
    archived.write_bytes(b'explicit test imported base')
    monkeypatch.setattr(demo,'DATA',data)
    monkeypatch.setattr(demo,'BOTTLE',data/'bottle')
    monkeypatch.setattr(demo,'PROGRAM',program)
    return data,fallback,archived


def test_registered_imported_base_is_selected_instead_of_original_example(isolated):
    data,_,archived=isolated
    (data/'native-attachments.json').write_text(json.dumps({'database_path':str(archived)}))
    assert demo.selected_database()==archived
    assert demo.launch_command(data/'runtime')[-1]==str(archived)


@pytest.mark.parametrize('invalid', ['missing','external','wrong_extension','relative','symlink_escape','malformed'])
def test_invalid_registration_keeps_isolated_official_example(isolated,invalid,tmp_path):
    data,fallback,archived=isolated
    external=tmp_path/'unrelated.not'
    external.write_bytes(b'never opened by this launcher')
    choices={'missing':archived.with_name('missing.not'),'external':external,
             'wrong_extension':archived.with_suffix('.sauv'),'relative':'relative.not'}
    if invalid=='symlink_escape':
        archived.unlink()
        archived.symlink_to(external)
        chosen=archived
    else:
        chosen=choices.get(invalid,archived)
    (data/'native-attachments.json').write_text('{' if invalid=='malformed'
        else json.dumps({'database_path':str(chosen)}))
    assert demo.selected_database()==fallback


def test_bundle_rewrites_stale_launcher_once_without_launching_app(isolated,monkeypatch):
    data,fallback,archived=isolated
    (data/'native-attachments.json').write_text(json.dumps({'database_path':str(archived)}))
    app=data/'PRONOTE Démo locale.app'
    contents=app/'Contents'
    launcher=contents/'SharedSupport/pronote/bin/run_pronote'
    launcher.parent.mkdir(parents=True)
    launcher.write_text('#!/bin/sh\nexec wine '+shlex.quote(str(fallback))+'\n')
    (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'old.test.identifier'}))
    monkeypatch.setattr(demo,'prepare',lambda:None)
    calls=[]
    monkeypatch.setattr(demo.subprocess,'run',lambda command,**kwargs:calls.append(command))
    assert demo.bundle()==app
    command=shlex.split(launcher.read_text().splitlines()[1])
    assert command[-1]==str(archived)
    assert calls==[['codesign','--force','--sign','-',str(app)]]
    assert plistlib.loads((contents/'Info.plist').read_bytes())['CFBundleIdentifier']=='local.hcompany.pronote-demo'
    demo.bundle()
    assert len(calls)==1
