plugins {
    id("net.neoforged.moddev.legacyforge") version "2.0.91"
}

// ---- 版本参数化:环境变量 BRIDGE_MC_VERSION,默认 1.20.1 ----
val mcVersion: String = providers.environmentVariable("BRIDGE_MC_VERSION").getOrElse("1.20.1")
data class LVers(val forge: String, val java: Int)
val LVERS = mapOf(
    "1.20.1" to LVers("1.20.1-47.1.3", 17),
    // 1.21.1 走 neoForge(非 legacyforge);到时用别的插件/坐标
)
val lv = LVERS[mcVersion] ?: error("暂不支持的 mcVersion=$mcVersion(已支持: ${LVERS.keys})")
logger.lifecycle("bridge-mod legacyforge(1.20.1): mcVersion=$mcVersion forge=${lv.forge} java=${lv.java}")

// common 便携 + 版本敏感(common-<mcVersion>)源码并入;入口按版本:1.20.1=Forge(BridgeForge),1.21.1=NeoForge(BridgeNeoForge)
sourceSets {
    main {
        java.setSrcDirs(listOf(
            if (mcVersion == "1.20.1") "../forge/src/main/java" else "src/main/java",
            "../common/src/main/java", "../common-${mcVersion}/src/main/java"))
        // 1.20.1=Forge 用 forge 的 mods.toml;1.21.1=NeoForge 用 neoforge.mods.toml
        resources.setSrcDirs(listOf(
            if (mcVersion == "1.20.1") "../forge/src/main/resources" else "src/main/resources"))
    }
}

tasks.withType<JavaCompile>().configureEach {
    options.release.set(lv.java)
}

legacyForge {
    version = lv.forge
}
