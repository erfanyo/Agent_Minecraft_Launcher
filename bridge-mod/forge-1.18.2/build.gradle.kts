plugins { id("net.minecraftforge.gradle") version "5.1.+" }

val mcVersion = "1.18.2"
val forgeVersion = "40.2.17"
version = "0.2.0"

sourceSets {
    named("main") {
        java.setSrcDirs(listOf("src/main/java", layout.buildDirectory.dir("generated/sources/shared").get().asFile))
        resources.setSrcDirs(listOf("src/main/resources"))
    }
}
val prepareSharedSources by tasks.registering(Sync::class) {
    from("../common/src/main/java") {
        exclude("com/agentmc/bridge/AiChat.java")
        exclude("com/agentmc/bridge/CommandBridgeSource.java")
        exclude("com/agentmc/bridge/LocalBridgeServer.java")
    }
    from("../common-1.20.1/src/main/java") { exclude("com/agentmc/bridge/ItemExporter.java", "com/agentmc/bridge/RecipeExporter.java") }
    from("../forge-1.19.2/src/main/java") {
        include("com/agentmc/bridge/ItemExporter.java", "com/agentmc/bridge/RecipeExporter.java")
    }
    into(layout.buildDirectory.dir("generated/sources/shared"))
}
repositories { maven { url = uri("https://maven.minecraftforge.net") }; mavenCentral() }
dependencies { minecraft("net.minecraftforge:forge:$mcVersion-$forgeVersion") }
minecraft { mappings("official", mcVersion) }
java { toolchain.languageVersion.set(JavaLanguageVersion.of(17)) }
tasks.withType<JavaCompile>().configureEach { dependsOn(prepareSharedSources); options.release.set(17); options.encoding = "UTF-8" }
tasks.jar { archiveBaseName.set("agentmc-bridge-forge-1.18.2"); manifest.attributes["Implementation-Version"] = project.version }
