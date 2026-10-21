param(
    [Parameter(Mandatory=$true)][string]$Python,
    [string]$BuildRoot = 'D:\Codex\途记专项\temp\NefGpsTrack-1.5.1-windows',
    [string]$OutputDirectory = 'D:\Codex\途记专项\outputs\NefGpsTrack\1.5.1'
)

$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$vendor = Join-Path $source 'vendor\exiftool-13.59_64.zip'
$expectedHash = '44B512B25AF500724BA579D0A53C8FC5851628B692DD5E5D94AE4A15C2CBA9EC'
$actualHash = (Get-FileHash -LiteralPath $vendor -Algorithm SHA256).Hash
if ($actualHash -ne $expectedHash) { throw 'ExifTool archive SHA-256 mismatch' }

$build = [IO.Path]::GetFullPath($BuildRoot)
$output = [IO.Path]::GetFullPath($OutputDirectory)
$sourceAbs = [IO.Path]::GetFullPath($source)
if ($build.StartsWith($sourceAbs, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build cache must stay outside versioned source'
}
New-Item -ItemType Directory -Force -Path $build,$output | Out-Null

$venv = Join-Path $build 'build-venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv $venv
    if ($LASTEXITCODE) { throw 'Python venv creation failed' }
}
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $source 'requirements-build.txt')
if ($LASTEXITCODE) { throw 'Build dependencies failed' }

$vendorExtract = Join-Path $build 'vendor'
New-Item -ItemType Directory -Force -Path $vendorExtract | Out-Null
Expand-Archive -LiteralPath $vendor -DestinationPath $vendorExtract -Force
$exifRoot = Join-Path $vendorExtract 'exiftool-13.59_64'
Copy-Item -LiteralPath (Join-Path $exifRoot 'exiftool(-k).exe') -Destination (Join-Path $exifRoot 'exiftool.exe') -Force
$env:LANG = 'C'
$env:LC_ALL = 'C'
$exifVersion = & (Join-Path $exifRoot 'exiftool.exe') -ver
if ($LASTEXITCODE -or $exifVersion.Trim() -ne '13.59') { throw 'ExifTool self-check failed' }

$runId = Get-Date -Format 'yyyyMMdd-HHmmss'
$runRoot = Join-Path $build "package-$runId"
$dist = Join-Path $runRoot 'dist'
$work = Join-Path $runRoot 'work'
$spec = Join-Path $runRoot 'spec'
New-Item -ItemType Directory -Force -Path $dist,$work,$spec | Out-Null
$name = 'NefGpsTrack-Windows-1.5.1'
# 主程序里带了卸载分支，需要 installer/core.py；打包时一并放进去。
$installerCore = Join-Path $source '..\installer\core.py'
if (-not (Test-Path -LiteralPath $installerCore)) { throw 'installer/core.py is missing' }
& $venvPython -m PyInstaller --noconfirm --onefile --windowed --noupx `
    --icon "$(Join-Path $source '..\shared\app.ico')" `
    --collect-all webview --hidden-import pythonnet --hidden-import clr_loader `
    --add-data "$(Join-Path $source '..\shared\ui');ui" `
    --name $name --distpath $dist --workpath $work --specpath $spec `
    --add-data "$(Join-Path $exifRoot 'exiftool.exe');exiftool" `
    --add-data "$(Join-Path $exifRoot 'exiftool_files');exiftool/exiftool_files" `
    --add-data "$installerCore;installer" `
    (Join-Path $source 'app.py')
if ($LASTEXITCODE) { throw 'PyInstaller build failed' }

$built = Join-Path $dist "$name.exe"
if (-not (Test-Path -LiteralPath $built)) { throw 'Expected EXE missing' }

# ---- 安装器：把主程序作为载荷打包进去，产出单文件 Setup ----
$installerSource = Join-Path $source '..\installer'
$payloadDir = Join-Path $runRoot 'payload'
New-Item -ItemType Directory -Force -Path $payloadDir | Out-Null
Copy-Item -LiteralPath $built -Destination (Join-Path $payloadDir '途记.exe') -Force
$setupDist = Join-Path $runRoot 'setup-dist'
$setupWork = Join-Path $runRoot 'setup-work'
$setupSpec = Join-Path $runRoot 'setup-spec'
New-Item -ItemType Directory -Force -Path $setupDist,$setupWork,$setupSpec | Out-Null
$setupName = 'NefGpsTrack-Setup-1.5.1'
& $venvPython -m PyInstaller --noconfirm --onefile --windowed --noupx `
    --icon "$(Join-Path $source '..\shared\app.ico')" `
    --collect-all webview --hidden-import pythonnet --hidden-import clr_loader `
    --add-data "$(Join-Path $installerSource 'ui');ui" `
    --add-data "$(Join-Path $payloadDir '途记.exe');payload" `
    --name $setupName --distpath $setupDist --workpath $setupWork --specpath $setupSpec `
    (Join-Path $installerSource 'app.py')
if ($LASTEXITCODE) { throw 'PyInstaller setup build failed' }

$setupBuilt = Join-Path $setupDist "$setupName.exe"
if (-not (Test-Path -LiteralPath $setupBuilt)) { throw 'Expected setup EXE missing' }

# 主程序作为载荷交付的一部分保留，方便需要时的便携部署与对照。
foreach ($pair in @(@($built, (Join-Path $output "$name.exe")), @($setupBuilt, (Join-Path $output "$setupName.exe")))) {
    $published = $pair[1]
    if (Test-Path -LiteralPath $published) { throw "Output already exists: $published" }
    Copy-Item -LiteralPath $pair[0] -Destination $published
    Get-Item -LiteralPath $published | Select-Object FullName,Length
    Get-FileHash -LiteralPath $published -Algorithm SHA256 | Select-Object Hash
}
