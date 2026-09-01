plugins {
    // Forge 1.19.2 使用 ForgeGradle 5；不能和 1.20.1 的 ForgeGradle 6 共用模块。
    id("net.minecraftforge.gradle") version "5.1.+"
}

val mcVersion = "1.19.2"
val forgeVersion = "43.2.0"
version = "0.2.2"

sourceSets {
    named("main") {
        java.setSrcDirs(listOf(
            "src/main/java",
            layout.buildDirectory.dir("generated/sources/shared").get().asFile,
        ))
        resources.setSrcDirs(listOf("src/main/resources"))
    }
}

// 两个现代共享目录中只有三个类使用 1.20+ API；把其余源码合并到生成目录，
// 由本模块 src/main/java 下的 1.19.2 同名实现替换它们。
val prepareSharedSources by tasks.registering(Copy::class) {
    from("../common/src/main/java") { exclude("com/agentmc/bridge/AiChat.java") }
    from("../common-1.20.1/src/main/java") {
        exclude("com/agentmc/bridge/ItemExporter.java", "com/agentmc/bridge/RecipeExporter.java")
    }
    into(layout.buildDirectory.dir("generated/sources/shared"))
}

repositories {
    maven { url = uri("https://maven.minecraftforge.net") }
    mavenCentral()
}

dependencies {
    minecraft("net.minecraftforge:forge:$mcVersion-$forgeVersion")
}

minecraft {
    mappings("official", mcVersion)
}

java {
    toolchain.languageVersion.set(JavaLanguageVersion.of(17))
}

tasks.withType<JavaCompile>().configureEach {
    dependsOn(prepareSharedSources)
    options.release.set(17)
    options.encoding = "UTF-8"
}

tasks.jar {
    archiveBaseName.set("agentmc-bridge-forge-1.19.2")
    manifest.attributes["Implementation-Version"] = project.version
}
