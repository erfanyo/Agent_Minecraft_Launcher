plugins {
    id("fabric-loom") version "1.6.11"   // 1.6 稳定线,兼容 Gradle 8.10
}

// ---- 版本参数化:改 -PmcVersion,其余自动跟着变 ----
// 版本:优先环境变量 BRIDGE_MC_VERSION,否则默认 1.20.1
val mcVersion: String = providers.environmentVariable("BRIDGE_MC_VERSION").getOrElse("1.20.1")
data class Vers(val loader: String, val java: Int, val mixin: String, val range: String)
val VERSIONS = mapOf(
    "1.20.1" to Vers("0.15.2", 17, "JAVA_17", ">=1.20.1 <1.21"),
    "1.21.1" to Vers("0.16.9", 21, "JAVA_21", "~1.21.1"),
)
val v = VERSIONS[mcVersion] ?: error("暂不支持的 mcVersion=$mcVersion(已支持: ${VERSIONS.keys})")
logger.lifecycle("bridge-mod fabric: mcVersion=$mcVersion loader=${v.loader} java=${v.java} mixin=${v.mixin}")

// common 核心源码直接并入本编译单元(loom 提供 MC classpath)
sourceSets {
    main {
        java.srcDirs("src/main/java", "../common/src/main/java", "../common-${mcVersion}/src/main/java")
        // resources 用默认 src/main/resources
    }
}

dependencies {
    minecraft("com.mojang:minecraft:$mcVersion")
    mappings(loom.officialMojangMappings())
    modImplementation("net.fabricmc:fabric-loader:${v.loader}")
    // 不依赖 fabric-api:服务器生命周期用 Mixin 处理,单 jar 即可运行
}

// 用 options.release 目标编译成本地 JDK(21)+ 目标版本字节码;不强制 toolchain(省得装 JDK17)
tasks.withType<JavaCompile>().configureEach {
    options.release.set(v.java)
}

// 资源展开:fabric.mod.json 的 ${minecraftRange} 与 mixins.json 的 ${mixinCompat}
tasks.processResources {
    inputs.property("minecraftRange", v.range)
    inputs.property("mixinCompat", v.mixin)
    filesMatching("fabric.mod.json") {
        expand(mapOf("minecraftRange" to v.range))
    }
    filesMatching("agentmc_bridge.mixins.json") {
        expand(mapOf("mixinCompat" to v.mixin))
    }
}

loom {
    mods {
        register("agentmc-bridge") {
            sourceSet(sourceSets.main.get())
        }
    }
}
