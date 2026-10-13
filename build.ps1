$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar o ambiente Python.' }
}
& .venv/Scripts/python.exe -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependências.' }
& .venv/Scripts/python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Os testes falharam.' }
# Qt needs the newer VC runtime shipped in its wheel. Put it at the archive root
# so Windows loads it for Python first, before Qt modules enter the process.
# Isolate DLL discovery from unrelated tools on PATH (e.g. Poppler/libheif can
# carry old Windows API shims that must not enter this application's package).
$windfreePreviousPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$PSScriptRoot\.venv\Scripts"
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm --onefile --windowed --name WindFreeTray --icon assets/windfree.ico --collect-data smartthings_local --add-binary '.venv/Lib/site-packages/PySide6/VCRUNTIME140.dll;.' --add-binary '.venv/Lib/site-packages/PySide6/VCRUNTIME140_1.dll;.' --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick main.py
} finally {
    $env:PATH = $windfreePreviousPath
}
if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar o executável.' }
& .venv/Scripts/python.exe tools/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'Falha ao incluir as licenças.' }
Write-Output 'Executável criado em dist/WindFreeTray.exe'
