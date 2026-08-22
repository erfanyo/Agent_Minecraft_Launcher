plugins {
    id("fabric-loom") version "1.6.11"   // 1.6 稳定线,兼容 Gradle 8.10
}

// common 核心源码直接并入本编译单元(loom 提供 MC classpath)
sourceSets {
    main {
        java.srcDirs("src/main/java", "../common/src/main/java")
        // resources 用默认 src/main/resources
    }
}

dependencies {
    minecraft("com.mojang:minecraft:1.21.1")
    mappings(loom.officialMojangMappings())
    modImplementation("net.fabricmc:fabric-loader:0.16.9")
    // 不依赖 fabric-api:服务器生命周期用 Mixin 处理,单 jar 即可运行
}

loom {
    mods {
        register("agentmc-bridge") {
            sourceSet(sourceSets.main.get())
        }
    }
}
