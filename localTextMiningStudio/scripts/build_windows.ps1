param(
    [string]$Version = "",
    [switch]$SkipZip,
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$AppName = "LocalTextMiningStudio"
$DistDir = Join-Path $RepoRoot "dist"
$BuildDir = Join-Path $RepoRoot "build"
$ReleaseDir = Join-Path $DistDir $AppName
$AppResourcesDir = Join-Path $RepoRoot "app\resources"
$AppSchemaFile = Join-Path $RepoRoot "app\db\schema.sql"
$ExamplesDir = Join-Path $RepoRoot "examples"

Set-Location $RepoRoot

if (-not $Version) {
    $Version = python -c "from app import __version__; print(__version__)"
}

Write-Host "Building $AppName v$Version (PyInstaller onedir)..." -ForegroundColor Cyan

if (-not $NoClean) {
    if (Test-Path $ReleaseDir) {
        Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
    }
    if (Test-Path (Join-Path $BuildDir $AppName)) {
        Remove-Item -LiteralPath (Join-Path $BuildDir $AppName) -Recurse -Force
    }
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name $AppName `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $BuildDir `
    --add-data "$AppResourcesDir;app/resources" `
    --add-data "$AppResourcesDir;resources" `
    --add-data "$AppSchemaFile;app/db" `
    --add-data "$ExamplesDir;examples" `
    --hidden-import "PySide6.QtWebEngineWidgets" `
    --hidden-import "PySide6.QtWebEngineCore" `
    --hidden-import "PySide6.QtWebEngineQuick" `
    --exclude-module "PyQt5" `
    --exclude-module "PyQt6" `
    --exclude-module "PySide2" `
    --exclude-module "tkinter" `
    --exclude-module "matplotlib" `
    --exclude-module "IPython" `
    --exclude-module "jedi" `
    --exclude-module "parso" `
    --exclude-module "sphinx" `
    --exclude-module "docutils" `
    --exclude-module "black" `
    --exclude-module "zmq" `
    --exclude-module "notebook" `
    --exclude-module "jupyter" `
    --exclude-module "pytest" `
    --collect-data "jieba" `
    "app/main.py"

if (-not (Test-Path (Join-Path $ReleaseDir "$AppName.exe"))) {
    throw "Build failed: $AppName.exe was not found in $ReleaseDir"
}

if ($SkipZip) {
    python scripts/make_release_zip.py --version $Version --no-zip
    Write-Host "Build finished: $ReleaseDir" -ForegroundColor Green
} else {
    python scripts/make_release_zip.py --version $Version
    Write-Host "Build and zip finished." -ForegroundColor Green
}
