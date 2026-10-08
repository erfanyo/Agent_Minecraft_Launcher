plugins {
    // NeoForge 1.21.1 用官方 ModDevGradle。
    // 注意:legacyforge 变体只适用于 1.20.1,不能用来编 1.21.1。
    id("net.neoforged.moddev") version "2.0.91"
}

val mcVersion = "1.21.1"
val neoForgeVersion = "21.1.250"
version = "0.2.0"

// common 核心源码 + 1.21.1 版本适配层直接并入本编译单元(需要目标 MC 的 classpath)。
// 版本敏感的类(BridgeIO / ItemExporter / RconAutoOpener / RecipeExporter)放在
// common-1.21.1,按 1.21 API 实现。
sourceSets {
    named("main") {
        java.setSrcDirs(listOf(
            "src/main/java",
            "../common/src/main/java",
            "../common-$mcVersion/src/main/java",
        ))
        resources.setSrcDirs(listOf("src/main/resources"))
    }
}

neoForge {
    version = neoForgeVersion
}

java {
    toolchain.languageVersion.set(JavaLanguageVersion.of(21))
}

tasks.withType<JavaCompile>().configureEach {
    options.release.set(21)
    options.encoding = "UTF-8"
}

// neoforge.mods.toml 里的 ${version} 用项目版本展开,避免版本号两处维护
tasks.processResources {
    inputs.property("version", project.version)
    filesMatching("META-INF/neoforge.mods.toml") {
        expand(mapOf("version" to project.version))
    }
}

tasks.jar {
    // 产物名必须匹配启动器的发现规则:agentmc-bridge-{loader}-{mc}-{ver}.jar
    archiveBaseName.set("agentmc-bridge-neoforge-$mcVersion")
    manifest.attributes["Implementation-Version"] = project.version
}
