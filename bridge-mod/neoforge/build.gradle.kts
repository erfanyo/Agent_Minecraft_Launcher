plugins {
    id("net.neoforged.gradle.userdev") version "7.0.146"
}

// common 核心源码直接并入本编译单元(与 fabric 同做法)
sourceSets {
    main {
        java.srcDirs("src/main/java", "../common/src/main/java")
    }
}

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(21))
    }
}

tasks.withType<JavaCompile>().configureEach {
    options.release.set(21)
}

dependencies {
    implementation("net.neoforged:neoforge:21.1.139")
}
