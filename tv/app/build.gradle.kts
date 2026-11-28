plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.gametranslate.tv"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.gametranslate.tv"
        minSdk = 26
        targetSdk = 34
        versionCode = 15
        versionName = "1.5"
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}


