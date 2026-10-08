pluginManagement {
    repositories {
        gradlePluginPortal()
        maven("https://maven.neoforged.net/releases")
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.PREFER_PROJECT)
    repositories {
        // NeoForge 以 ivy 形式发布,允许 artifact 元数据(否则 userdev 解析失败)
        maven("https://maven.neoforged.net/releases") {
            metadataSources { mavenPom(); artifact() }
        }
        mavenCentral()
        maven("https://libraries.minecraft.net")
    }
}

// NeoForge 1.21.1 独立根工程:ModDevGradle 与 1.20.1 的 legacyforge 插件不能共用
// 同一个配置阶段,因此和 forge-1.18.2 / forge-1.19.2 一样单独作为一个 root project。
rootProject.name = "agentmc-bridge-neoforge-1.21.1"
