pluginManagement {
    repositories {
        gradlePluginPortal()
        maven("https://maven.minecraftforge.net")
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.PREFER_PROJECT)
    repositories {
        maven("https://maven.minecraftforge.net")
        mavenCentral()
        maven("https://libraries.minecraft.net")
    }
}

rootProject.name = "agentmc-bridge-forge-1.19.2"
