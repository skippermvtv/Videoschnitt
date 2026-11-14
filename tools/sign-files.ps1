# Signiert Programmdateien (.exe, .dll, .pyd, die noch keine Signatur haben) mit signtool und einem Zertifikat aus .pfx-Datei.
# Ohne hinterlegtes Zertifikat (Secret SIGN_PFX_BASE64) passiert nichts, der Build läuft normal weiter.
# Aufruf:  pwsh tools/sign-files.ps1 -Path dist/FATE-VIDEOSCHNITT   (Ordner oder einzelne Datei)
param([Parameter(Mandatory = $true)][string]$Path)

$ErrorActionPreference = "Stop"
if (-not $env:SIGN_PFX_BASE64) {
    Write-Host "Signieren übersprungen: kein Zertifikat hinterlegt (Secret SIGN_PFX_BASE64)."
    exit 0
}

$st = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" | Sort-Object FullName | Select-Object -Last 1
if (-not $st) { throw "signtool.exe nicht gefunden" }

$pfx = Join-Path $env:RUNNER_TEMP "sign.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:SIGN_PFX_BASE64))

try {
    if (Test-Path $Path -PathType Container) {
        $files = Get-ChildItem $Path -Recurse -File | Where-Object { $_.Extension -in ".exe", ".dll", ".pyd" }
    } else {
        $files = @(Get-Item $Path)
    }
    # Schon signierte Dateien (z. B. von Python oder Qt) bleiben unberührt
    $todo = @($files | Where-Object { (Get-AuthenticodeSignature $_.FullName).Status -eq "NotSigned" })
    Write-Host "$($files.Count) Dateien gefunden, $($todo.Count) ohne Signatur."

    $servers = @("http://timestamp.digicert.com", "http://timestamp.sectigo.com", "http://time.certum.pl")
    for ($i = 0; $i -lt $todo.Count; $i += 40) {
        $chunk = @($todo[$i..([Math]::Min($i + 39, $todo.Count - 1))] | ForEach-Object { $_.FullName })
        $ok = $false
        foreach ($tsa in $servers) {
            & $st.FullName sign /f $pfx /p $env:SIGN_PFX_PASSWORD /fd SHA256 /tr $tsa /td SHA256 @chunk
            if ($LASTEXITCODE -eq 0) { $ok = $true; break }
            Write-Host "Zeitstempel-Server $tsa hat nicht geantwortet, nächster Versuch."
        }
        if (-not $ok) { throw "Signieren fehlgeschlagen" }
    }

    $bad = @($todo | Where-Object { (Get-AuthenticodeSignature $_.FullName).Status -ne "Valid" })
    if ($bad.Count -gt 0) {
        $bad | ForEach-Object { Write-Host "Keine gültige Signatur: $($_.FullName)" }
        throw "$($bad.Count) Dateien haben nach dem Signieren keine gültige Signatur."
    }
    Write-Host "$($todo.Count) Dateien signiert und geprüft."
} finally {
    Remove-Item $pfx -ErrorAction SilentlyContinue
}
