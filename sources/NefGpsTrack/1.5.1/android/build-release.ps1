param(
    [string]$BuildRoot = 'D:\Codex\nefgpstrack-151-build',
    [string]$GradleUserHome = 'D:\Codex\gps30-gradle-cache',
    [string]$ToolRoot = 'D:\Codex\改软件\tools'
)

$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..\..')).Path
$sdk = Join-Path $ToolRoot 'android-sdk'
$jdk = Join-Path $ToolRoot 'jdk-17.0.10.7-hotspot'
$keyDir = Join-Path $ToolRoot 'signing\nefgpstrack'
$keyPath = Join-Path $keyDir 'release.p12'
$secretPath = Join-Path $keyDir 'release-secret.json'
$outDir = Join-Path $workspace 'outputs\NefGpsTrack\1.5.1'

if (!(Test-Path -LiteralPath $keyPath) -or !(Test-Path -LiteralPath $secretPath)) {
    throw 'Missing NefGpsTrack signing key or secret file.'
}
if (Test-Path -LiteralPath $BuildRoot) {
    $existing = Join-Path $BuildRoot 'settings.gradle.kts'
    if ((Test-Path -LiteralPath $existing) -and
        !(Select-String -LiteralPath $existing -Pattern 'rootProject.name = "NefGpsTrack"' -Quiet)) {
        throw "BuildRoot belongs to another project: $BuildRoot"
    }
} else {
    New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
}

New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'app\src\main\assets\ui') | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot '..\shared\ui\*') -Destination (Join-Path $PSScriptRoot 'app\src\main\assets\ui') -Recurse -Force
Copy-Item -Path (Join-Path $PSScriptRoot '*') -Destination $BuildRoot -Recurse -Force
$env:GRADLE_USER_HOME = $GradleUserHome
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
$env:JAVA_HOME = $jdk

Push-Location -LiteralPath $BuildRoot
try {
    & .\gradlew.bat :app:assembleRelease :app:lintRelease --no-daemon
    if ($LASTEXITCODE -ne 0) { throw "Gradle failed: $LASTEXITCODE" }
} finally {
    Pop-Location
}

$unsigned = Join-Path $BuildRoot 'app\build\outputs\apk\release\app-release-unsigned.apk'
$aligned = Join-Path $BuildRoot 'release-aligned.apk'
$signed = Join-Path $BuildRoot 'release-signed.apk'
$buildTools = Join-Path $sdk 'build-tools\36.0.0'
$zipalign = Join-Path $buildTools 'zipalign.exe'
$apksigner = Join-Path $buildTools 'apksigner.bat'
$secret = Get-Content -LiteralPath $secretPath -Raw | ConvertFrom-Json
& $zipalign -p -f 4 $unsigned $aligned
if ($LASTEXITCODE -ne 0) { throw 'zipalign failed' }
& $apksigner sign --ks $keyPath --ks-key-alias $secret.alias `
    --ks-pass "pass:$($secret.password)" --key-pass "pass:$($secret.password)" `
    --v4-signing-enabled false --out $signed $aligned
if ($LASTEXITCODE -ne 0) { throw 'apksigner failed' }
& $zipalign -c 4 $signed
if ($LASTEXITCODE -ne 0) { throw 'zipalign verification failed' }
& $apksigner verify --verbose $signed
if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed' }

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$deliverable = Join-Path $outDir 'NefGpsTrack-Android-1.5.1.apk'
Copy-Item -LiteralPath $signed -Destination $deliverable -Force
$item = Get-Item -LiteralPath $deliverable
$hash = (Get-FileHash -LiteralPath $deliverable -Algorithm SHA256).Hash
@(
    'NefGpsTrack Android 1.5.1'
    "Built UTC: $([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))"
    'Package: app.nefgpstrack'
    "Version: $((Select-String -LiteralPath (Join-Path $PSScriptRoot 'app\build.gradle.kts') -Pattern 'versionName = "([^"]+)"').Matches[0].Groups[1].Value) / code $((Select-String -LiteralPath (Join-Path $PSScriptRoot 'app\build.gradle.kts') -Pattern 'versionCode = (\d+)').Matches[0].Groups[1].Value)"
    "APK bytes: $($item.Length)"
    "SHA-256: $hash"
    'Gradle: assembleRelease + lintRelease passed'
    'zipalign: passed'
    'APK signature: verified by apksigner (v2/v3)'
    'UI: dragging .nef files imports photos and dragging .clp imports routes; several routes can be checked for smart matching'
    'Windows: NEF GPS writes no longer produce any table file; write mode can be a new copy or an in-place rewrite of the original'
    'Xiaomi island: three-state capability gate, template-library param_v2, exported IslandActionReceiver for the stop action'
    'Device recording, Xiaomi island display and background survival: not yet verified on hardware'
) | Set-Content -LiteralPath (Join-Path $outDir 'android-build-verification.txt') -Encoding utf8
Write-Output $deliverable
