import java.util.Properties

plugins {
    id("com.android.application")
}

val localClpProperties = Properties()
val localClpFile = rootProject.file("clp-private.properties")
if (localClpFile.isFile) localClpFile.inputStream().use { localClpProperties.load(it) }
val localClpPassword = providers.environmentVariable("NEFGPSTRACK_CLP_PASSWORD").orNull
    ?: providers.gradleProperty("tujiClpPassword").orNull
    ?: localClpProperties.getProperty("clpPassword", "")
require(localClpPassword.isNotBlank()) {
    "Configure a local CLP password; see BUILD.md. No original password is published."
}
val localClpLiteral = "\"" + localClpPassword.replace("\\", "\\\\")
    .replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r") + "\""

android {
    buildFeatures { buildConfig = true }
    namespace = "app.nefgpstrack"
    compileSdk = 37
    buildToolsVersion = "37.0.0"

    defaultConfig {
        applicationId = "app.nefgpstrack"
        minSdk = 26
        targetSdk = 35
        versionCode = 14
        versionName = "1.5.2"
        buildConfigField("String", "CLP_PASSWORD", localClpLiteral)
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
}

dependencies {
    implementation("androidx.core:core:1.18.0")
    implementation("androidx.core:core-location-altitude:1.0.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.17")
}
