"""Prepare a separate official Monoposte example; keep the signed Mac client intact."""
import json
import shutil
import subprocess
import plistlib
import shlex
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
CLIENT=DATA/'pronote-native/component.pkg/Payload/Client PRONOTE 2026.app'
RUNTIME=CLIENT/'Contents/SharedSupport/pronote'
MONO=DATA/'pronote-monoposte'
BOTTLE=DATA/'pronote-demo-bottle'
PROGRAM=BOTTLE/'drive_c/H-Demo/PRONOTE'


def selected_database():
    """Use the registered demo base containing the verified imported documents.

    Registration may never redirect this launcher outside its isolated Wine
    drive. A missing/invalid registration keeps the vendor's original example.
    """
    fallback=PROGRAM/'Base-Exemple/Base Exemple.not'
    try:
        manifest=json.loads((DATA/'native-attachments.json').read_text())
        candidate=Path(manifest['database_path']).expanduser()
        if not candidate.is_absolute() or candidate.suffix.casefold()!='.not':
            return fallback
        database=candidate.resolve(strict=True)
        drive=(BOTTLE/'drive_c').resolve(strict=True)
        if database.is_file() and database.suffix.casefold()=='.not' and database.is_relative_to(drive):
            return database
    except (OSError,KeyError,TypeError,ValueError):
        pass
    return fallback


def launch_command(runtime):
    return [str(runtime/'bin/wine'),'--bottle',str(BOTTLE),'--no-update',
            '--wait-children','--enable-alt-loader=macdrv','--workdir',str(PROGRAM),
            str(PROGRAM/'PRONOTE Monoposte.exe'),str(selected_database())]


def prepare():
    if not BOTTLE.exists():
        subprocess.run(['/bin/cp','-cR',str(RUNTIME/'support/v2026_FRANCE'),str(BOTTLE)],check=True)
    devices=BOTTLE/'dosdevices';devices.mkdir(exist_ok=True)
    if not (devices/'c:').exists():(devices/'c:').symlink_to('../drive_c')
    PROGRAM.mkdir(parents=True,exist_ok=True)
    for group in ('exe','xml','Dictionnaire','WPDFViewer'):
        for source in (MONO/group).glob('*'):
            if source.is_file() and not (PROGRAM/source.name).exists():shutil.copy2(source,PROGRAM/source.name)
    for source in (MONO/'icu').glob('*'):
        target=PROGRAM/'icu'/source.name;target.parent.mkdir(exist_ok=True)
        if source.is_file() and not target.exists():shutil.copy2(source,target)
    chromium=PROGRAM/'wwwroot'
    if not chromium.exists():subprocess.run(['/bin/cp','-cR',str(MONO/'Chromium'),str(chromium)],check=True)
    examples=PROGRAM/'Exemples';examples.mkdir(exist_ok=True)
    for source in (MONO/'exemple').glob('*'):
        if source.is_file() and not (examples/source.name).exists():shutil.copy2(source,examples/source.name)
    database=PROGRAM/'Base-Exemple'
    if not (database/'Base Exemple.not').exists():
        database.mkdir(exist_ok=True)
        with zipfile.ZipFile(examples/'Base Exemple PRONOTE 2026.zip') as archive:
            for item in archive.infolist():
                relative=Path(item.filename.replace('\\','/'))
                if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe example archive path')
                target=database/relative
                if item.is_dir():target.mkdir(parents=True,exist_ok=True)
                else:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(archive.read(item))
    manifest={'source':'Paquet officiel PRONOTE Monoposte 2026.2.8','client_mac_unchanged':True,'mode':'Monoposte officiel sur bouteille séparée','example_archive':str(examples/'Base Exemple PRONOTE 2026.zip'),'program':str(PROGRAM/'PRONOTE Monoposte.exe'),'bottle':str(BOTTLE),'database':str(selected_database()),'ui_verified':False}
    (DATA/'native-demo-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest

def bundle():
    prepare()
    target=DATA/'PRONOTE Démo locale.app'
    if not target.exists():subprocess.run(['/bin/cp','-cR',str(CLIENT),str(target)],check=True)
    launcher=target/'Contents/SharedSupport/pronote/bin/run_pronote'
    runtime=target/'Contents/SharedSupport/pronote'
    script='#!/bin/sh\nexec '+shlex.join(launch_command(runtime))+'\n'
    if launcher.exists() and launcher.read_text(errors='replace')==script:
        return target
    info_path=target/'Contents/Info.plist'
    info=plistlib.loads(info_path.read_bytes())
    info.update(CFBundleIdentifier='local.hcompany.pronote-demo',CFBundleName='PRONOTE Démo locale',CFBundleDisplayName='PRONOTE Démo locale')
    info_path.write_bytes(plistlib.dumps(info))
    launcher.write_text(script);launcher.chmod(0o755)
    subprocess.run(['codesign','--force','--sign','-',str(target)],check=True,capture_output=True)
    return target

def launch():
    prepare()
    command=launch_command(RUNTIME)
    log=(DATA/'pronote-demo-launch.log').open('ab')
    p=subprocess.Popen(command,stdout=log,stderr=log,start_new_session=True)
    (DATA/'native-demo-process.json').write_text(json.dumps({'pid':p.pid,'mode':'official_monoposte_example'}))
    return p.pid

if __name__=='__main__':print('Official local example launched. PID',launch())
