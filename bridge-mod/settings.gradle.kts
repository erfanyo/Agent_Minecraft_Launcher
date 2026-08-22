pluginManagement {
    repositories {
        gradlePluginPortal()
        maven("https://maven.fabricmc.net")          // fabric-loom
        maven("https://maven.minecraftforge.net")    // forgegradle(未来)
        maven("https://maven.neoforged.net/releases") // neoforged userdev(未来)
    }
}

dependencyResolutionManagement {
    repositories {
        mavenCentral()
        maven("https://maven.fabricmc.net")
        maven("https://maven.minecraftforge.net")
        maven("https://maven.neoforged.net/releases")
        maven("https://libraries.minecraft.net")
    }
}

rootProject.name = "agentmc-bridge"

// fabric 平台(已验证)+ neoforge 平台(适配中):
// common 源码直接并入各平台编译单元(见各自 build.gradle.kts 的 sourceSets)。
// forge(1.19 及以前)晚点再做。
include("fabric", "neoforge")
