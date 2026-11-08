# Maintainer build only. Teachers open the resulting .exe, never this script.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $IsWindows) { throw 'This build must run on Windows with PowerShell 7.' }
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $ProjectDir
$BuildEnv = Join-Path $ProjectDir '.venv-pilot-windows'
python -m venv $BuildEnv
if ($LASTEXITCODE -ne 0) { throw 'Could not create build environment.' }
$Python = Join-Path $BuildEnv 'Scripts/python.exe'
& $Python -m pip install -r mvp/desktop/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$env:PLAYWRIGHT_BROWSERS_PATH = '0'
& $Python -m playwright install chromium --no-shell
if ($LASTEXITCODE -ne 0) { throw 'Browser download failed.' }
& $Python -m PyInstaller `
  --noconfirm --windowed --onedir --name 'PRONOTE Pilote' `
  --distpath dist-pilot-windows --workpath build-pilot-windows/work --specpath build-pilot-windows `
  --additional-hooks-dir "$ProjectDir/mvp/desktop/hooks" `
  --paths $ProjectDir --add-data "$ProjectDir/mvp/desktop/pilot.html:mvp/desktop" `
  --add-data "$ProjectDir/mvp/desktop/pilot.js:mvp/desktop" `
  --collect-all pronotepy --collect-all Crypto `
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.asyncio `
  --hidden-import uvicorn.protocols.http.h11_impl --hidden-import uvicorn.lifespan.off `
  mvp/desktop/launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
$BrowserDir = & $Python -c 'import pathlib, playwright; print(pathlib.Path(playwright.__file__).parent / "driver/package/.local-browsers")'
$PackageDir = Join-Path $ProjectDir 'dist-pilot-windows/PRONOTE Pilote'
Copy-Item -Recurse $BrowserDir (Join-Path $PackageDir 'browsers')
$Instructions = @'
PRONOTE - Pilote professeur pour Windows 11 x64

1. Extraire entierement le ZIP (clic droit > Extraire tout).
2. Ouvrir le dossier extrait, puis double-cliquer sur PRONOTE Pilote.exe.
3. Choisir l'acces navigateur ou la connexion automatique.
4. En mode navigateur : renseigner l'adresse PRONOTE de votre etablissement,
   vous connecter dans la fenetre PRONOTE ou ENT, puis relever la vue utile.
5. En connexion automatique : choisir le type de compte et vous authentifier
   avec vos identifiants ou les donnees du QR code PRONOTE et son code PIN.
   La synchronisation se poursuit lorsque l'application reste ouverte.

Ne pas lancer le programme directement depuis le ZIP.
Conserver les dossiers _internal et browsers a cote de l'executable.
Python et Chromium sont inclus ; aucune installation et aucun terminal requis.
Une connexion Internet et votre compte habituel PRONOTE/ENT sont necessaires.

Pour quitter : fermer la fenetre principale. Le navigateur et les taches sont arretes.
La memorisation de session est facultative ; elle conserve un jeton de reconnexion
prive dans %LOCALAPPDATA%\PronotePilot, jamais le mot de passe personnel.
Deconnecter efface le jeton et les donnees de la connexion automatique.
Aucun contenu n'est envoye a une IA.

Ce pilote n'est pas signe par un certificat editeur Windows. SmartScreen ou les
regles de votre etablissement peuvent bloquer le premier lancement. En cas de
blocage sur un poste gere, contacter l'equipe informatique de l'etablissement.
Le mode navigateur lit le texte visible, pas tous les tableaux ni les pieces jointes.
Le connecteur automatique est non officiel et les donnees disponibles dependent
du compte et de la version PRONOTE. Les comptes enseignants ont un acces limite.
'@
[IO.File]::WriteAllText((Join-Path $PackageDir 'LIRE-MOI.txt'), $Instructions, [Text.UTF8Encoding]::new($false))
# Python ZIP includes all package files, including resources that may be hidden.
& $Python -c "import shutil; shutil.make_archive('dist-pilot-windows/PRONOTE-Pilote-Windows-x64', 'zip', 'dist-pilot-windows', 'PRONOTE Pilote')"
if ($LASTEXITCODE -ne 0) { throw 'ZIP creation failed.' }
