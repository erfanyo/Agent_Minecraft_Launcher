plugins {
    id("java")
}

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(21))   // 本机 java-runtime-delta = Java 21
    }
}

tasks.withType<JavaCompile>().configureEach {
    options.release.set(21)   // 目标字节码 21:MC 1.21.1 运行时是 Java 21
}

dependencies {
    // Minecraft 本体与加载器 API 由各平台子项目提供(见 fabric/forge/neoforge 的 build.gradle.kts)
    compileOnly("net.minecraft:minecraft:1.21.1")
    compileOnly("com.mojang:datafixerupper:8.0.16")
}
