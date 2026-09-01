plugins {
    id("net.minecraftforge.gradle") version "[6.0,6.2)"
}

val mcVersion = "1.20.1"

// Forge 1.20.1 的完整 bridge 基线。common 不是独立 Gradle 项目：它需要目标 MC 的
// 编译 classpath，因此与版本适配层一起直接并入本模块。
sourceSets {
    main {
        java.setSrcDirs(listOf(
            "src/main/java",
            "../common/src/main/java",
            "../common-1.20.1/src/main/java",
        ))
        resources.setSrcDirs(listOf("src/main/resources"))
    }
}

dependencies {
    minecraft("net.minecraftforge:forge:$mcVersion-47.1.3")
}

minecraft {
    mappings("official", mcVersion)
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

tasks.withType<JavaCompile>().configureEach {
    options.release.set(17)
}

tasks.jar {
    archiveBaseName.set("agentmc-bridge-forge-1.20.1")
}
