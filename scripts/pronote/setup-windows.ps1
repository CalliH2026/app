<#
.SYNOPSIS
  Download the PRONOTE 2026 trial installers from the official Index Education download page,
  verify their size, then open them for an interactive install.

.DESCRIPTION
  Source page: https://www.index-education.com/fr/telecharger-pronote.php
  The script reads that page, takes the installer links it publishes (hosts tele*.index-education.com),
  downloads them, and checks that the file size on disk equals the Content-Length announced by the
  server. When the version is 2026.2.8 it also checks the sizes recorded on 2026-11-07 (below).
  The download page itself does not publish file sizes or checksums.

  Silent install: NOT used by this script.
  - The only silent-install procedure Index Education documents is for the Client application
    (InstallShield-style "-r" to record a response file, then "-s -f1<file.iss> -f2<log>"):
    https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-6924-comment-installer-rapidement-des-clients-sur-tous-les-postes-d-un-reseau-installation-silencieuce.php
  - No silent flag is documented for "Utilisateur monoposte 2026", "SERVEUR 2026" or
    "Administration du SERVEUR 2026". The script therefore downloads and opens each installer;
    a human clicks through it.

  macOS: the "CLIENT PRONOTE 2026 - 2.8 MAC OS" package is listed with -IncludeMacClient only so it
  can be copied to the Mac; install it on the Mac, not here.

.PARAMETER Mode
  Monoposte (default): "Utilisateur monoposte 2026".
  Server: "SERVEUR 2026" + "Administration du SERVEUR 2026".

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1
  powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -Mode Server -IncludeWindowsClient
#>
[CmdletBinding()]
param(
    [ValidateSet('Monoposte', 'Server')]
    [string]$Mode = 'Monoposte',
    [string]$OutDir = (Join-Path $env:USERPROFILE 'Downloads\PRONOTE-2026'),
    [switch]$IncludeWindowsClient,
    [switch]$IncludeMacClient,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$DownloadPage = 'https://www.index-education.com/fr/telecharger-pronote.php'

# Sizes in bytes read from the Content-Length of the official links on 2026-11-07 (version 2026.2.8).
$KnownSizes = @{
    'Install_PRNmonoposte_FR_2026.2.8_win64.exe'   = 285153672
    'Install_PRNserveur_FR_2026.2.8_win64.exe'     = 83260808
    'Install_PRNadminserveur_FR_2026.2.8_win64.exe' = 30143016
    'Install_PRNclient_FR_2026.2.8_win64.exe'      = 281038752
    'Install_PRNclient_FR_2026.2.8_win64.pkg'      = 902811819
}

$wanted = @(switch ($Mode) {
    'Monoposte' { 'monoposte' }
    'Server'    { 'serveur', 'adminserveur' }
})
if ($IncludeWindowsClient) { $wanted += 'client' }

Write-Host "Reading $DownloadPage"
$html = (Invoke-WebRequest -Uri $DownloadPage -UseBasicParsing).Content
$pattern = 'https://tele\d*\.index-education\.com/telechargement/pn/v2026\.0/exe/Install_PRN(?<app>[a-z]+)_FR_[0-9.]+_win64\.(?<ext>exe|pkg)'
$links = [regex]::Matches($html, $pattern) | ForEach-Object {
    [pscustomobject]@{ Url = $_.Value; App = $_.Groups['app'].Value; Ext = $_.Groups['ext'].Value }
} | Sort-Object Url -Unique

$selected = @($links | Where-Object { $_.Ext -eq 'exe' -and $wanted -contains $_.App })
if ($IncludeMacClient) {
    $mac = @($links | Where-Object { $_.Ext -eq 'pkg' -and $_.App -eq 'client' })
    if (-not $mac) { throw "No macOS Client package found on $DownloadPage. Download it by hand." }
    $selected += $mac
}

foreach ($app in $wanted) {
    if (-not ($selected | Where-Object { $_.App -eq $app -and $_.Ext -eq 'exe' })) {
        throw "No link for '$app' found on $DownloadPage. The page layout may have changed: download by hand."
    }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$downloaded = @()

foreach ($item in $selected) {
    $name = Split-Path $item.Url -Leaf
    $dest = Join-Path $OutDir $name

    $head = Invoke-WebRequest -Uri $item.Url -Method Head -UseBasicParsing
    $announced = [int64]($head.Headers['Content-Length'] | Select-Object -First 1)

    if ((Test-Path $dest) -and (Get-Item $dest).Length -eq $announced) {
        Write-Host "Already downloaded: $name"
    } else {
        Write-Host "Downloading $name ($([math]::Round($announced / 1MB)) MB) ..."
        Invoke-WebRequest -Uri $item.Url -OutFile $dest -UseBasicParsing
    }

    $actual = (Get-Item $dest).Length
    if ($actual -ne $announced) {
        throw "Size mismatch for ${name}: $actual bytes on disk, $announced announced by the server."
    }
    if ($KnownSizes.ContainsKey($name) -and $KnownSizes[$name] -ne $actual) {
        throw "Size mismatch for ${name}: $actual bytes, $($KnownSizes[$name]) recorded on 2026-11-07."
    }
    if (-not $KnownSizes.ContainsKey($name)) {
        Write-Warning "$name is a newer build than the one recorded in this script; only the server size was checked."
    }
    Write-Host "OK  $name  $actual bytes"
    $downloaded += [pscustomobject]@{ Name = $name; Path = $dest; Ext = $item.Ext }
}

# Refuse to open an installer whose Authenticode signature is not valid (Windows only).
if (Get-Command Get-AuthenticodeSignature -ErrorAction SilentlyContinue) {
    foreach ($exe in ($downloaded | Where-Object Ext -eq 'exe')) {
        $sig = Get-AuthenticodeSignature $exe.Path
        Write-Host ("Signature {0}: {1} ({2})" -f $exe.Name, $sig.Status, $sig.SignerCertificate.Subject)
        if ($sig.Status -ne 'Valid') { throw "Invalid signature on $($exe.Name): $($sig.Status). Delete it and download again." }
    }
} elseif (-not $NoOpen) {
    throw 'Get-AuthenticodeSignature is not available: cannot check the installers before opening them.'
}

if ($NoOpen) { Write-Host "Downloaded to $OutDir (not opened: -NoOpen)."; return }

# No documented silent flag for these installers: open each one and let the human click through.
foreach ($exe in ($downloaded | Where-Object Ext -eq 'exe')) {
    Write-Host "Opening $($exe.Name). Finish this installer, then close it to continue."
    Start-Process -FilePath $exe.Path -Wait
}
Write-Host "Done. Next: docs/pronote-setup.md, section 'Create the base'."
