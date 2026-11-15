param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'sources\NefGpsTrack\1.5.2'
$android = Join-Path $source 'android'
$assets = Join-Path $android 'app\src\main\assets\ui'
New-Item -ItemType Directory -Path $assets -Force | Out-Null
Copy-Item -Path (Join-Path $source 'shared\ui\*') -Destination $assets -Recurse -Force
Push-Location -LiteralPath $android
try {
    $tasks = @(':app:assembleRelease', ':app:lintRelease')
    if (!$SkipTests) { $tasks += ':app:testDebugUnitTest' }
    & .\gradlew.bat @tasks --no-daemon --console=plain
    if ($LASTEXITCODE) { throw "Gradle failed ($LASTEXITCODE)." }
} finally {
    Pop-Location
}
