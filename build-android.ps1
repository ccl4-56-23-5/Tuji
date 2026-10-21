param(
    # 只列当前保留的版本：普通版本保留最新三版，退休版本已被清理。
    [ValidateSet('1.4.3', '1.5.0', '1.5.1')]
    [string]$Version = '1.5.1',
    [string]$BuildCacheRoot,
    [string]$GradleUserHome = 'D:\Codex\gps30-gradle-cache',
    [string]$ToolRoot = 'D:\Codex\改软件\tools'
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($BuildCacheRoot)) {
    $BuildCacheRoot = Join-Path $PSScriptRoot 'temp\NefGpsTrackBuilds'
}
$BuildCacheRoot = [IO.Path]::GetFullPath($BuildCacheRoot)
New-Item -ItemType Directory -Force -Path $BuildCacheRoot | Out-Null

$buildDirectory = switch ($Version) {
    '1.4.3' { 'nefgpstrack-143-build' }
    '1.5.0' { 'nefgpstrack-150-build' }
    '1.5.1' { 'nefgpstrack-151-build' }
}
$buildScript = Join-Path $PSScriptRoot "sources\NefGpsTrack\$Version\android\build-release.ps1"
if (!(Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "Android build script not found: $buildScript"
}

$driveLetter = @('R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z') |
    Where-Object { !(Test-Path -LiteralPath ('{0}:\' -f $_)) } |
    Select-Object -First 1
if (!$driveLetter) {
    throw 'No free drive letter is available for the temporary ASCII Android build path.'
}

$substDrive = '{0}:' -f $driveLetter
$driveRoot = '{0}:\' -f $driveLetter
& subst $substDrive $BuildCacheRoot
if ($LASTEXITCODE -ne 0) {
    throw "Could not map the project build cache to $substDrive"
}

try {
    $buildRoot = Join-Path $driveRoot $buildDirectory
    if ($buildRoot -match '[^\x00-\x7F]') {
        throw "Android BuildRoot must use an ASCII-only path: $buildRoot"
    }
    Write-Host "Project cache: $BuildCacheRoot"
    Write-Host "Android build workspace: $buildRoot"
    & $buildScript -BuildRoot $buildRoot -GradleUserHome $GradleUserHome -ToolRoot $ToolRoot
} finally {
    & subst $substDrive /d
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Could not remove temporary drive mapping $substDrive"
    }
}
