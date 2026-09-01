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
val lv = LVERS[mcVersion]
if (lv == null) {
    // Gradle 会配置所有 include 的子项目。Fabric 1.21.1 构建不能被这个
    // 仅支持 1.20.1 的 legacyforge 子项目中断；NeoForge 1.21.1 的正式
    // moddev 构建脚本尚未接入，先明确跳过而不是伪称已支持。
    logger.lifecycle("skip legacyforge for mcVersion=$mcVersion (supports: ${LVERS.keys})")
    tasks.configureEach { enabled = false }
} else {
    logger.lifecycle("bridge-mod legacyforge(1.20.1): mcVersion=$mcVersion forge=${lv.forge} java=${lv.java}")

    // common 便携 + 版本敏感(common-<mcVersion>)源码并入
    sourceSets {
        main {
            java.setSrcDirs(listOf(
                "../forge/src/main/java", "../common/src/main/java", "../common-${mcVersion}/src/main/java"))
            resources.setSrcDirs(listOf("../forge/src/main/resources"))
        }
    }

    tasks.withType<JavaCompile>().configureEach {
        options.release.set(lv.java)
    }

    legacyForge {
        version = lv.forge
    }
}
