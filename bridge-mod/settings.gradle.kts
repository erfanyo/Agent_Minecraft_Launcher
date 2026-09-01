pluginManagement {
    repositories {
        gradlePluginPortal()
        maven("https://maven.fabricmc.net")          // fabric-loom
        maven("https://maven.minecraftforge.net")    // forgegradle(未来)
        maven("https://maven.neoforged.net/releases") // neoforged userdev(未来)
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.PREFER_PROJECT)   // fabric 的 Loom 需项目仓库(否则映射解析失败)
    repositories {
        mavenCentral()
        maven("https://maven.fabricmc.net")
        maven("https://maven.minecraftforge.net")
        maven("https://maven.neoforged.net/releases") {   // neoforge 以 ivy 形式发布,允许 artifact 元数据
            metadataSources { mavenPom(); artifact() }
        }
        maven("https://libraries.minecraft.net")
    }
}

rootProject.name = "agentmc-bridge"

// 当前优先构建:Fabric + Forge 1.20.1。NeoForge 留作独立现代适配工程，避免旧版 Forge
// 构建时被不相关的插件配置中断。
// common 源码直接并入各平台编译单元(见各自 build.gradle.kts 的 sourceSets)。
include("fabric", "forge")
