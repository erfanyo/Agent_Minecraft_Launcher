package com.agentmc.bridge;

import net.minecraft.server.MinecraftServer;

/**
 * 桥接核心:协调各模块。
 * 各平台入口(Fabric/Forge/NeoForge)在服务器启动/停止事件里调用本类的
 * onServerStarted / onServerStopped。
 *
 * 注意:此目录代码为骨架阶段,需 Gradle + JDK 环境编译并按目标 MC 版本适配
 * (API 差异集中在 RconAutoOpener 与各事件注册处)。
 */
public final class BridgeCore {

    private static MinecraftServer server;
    private static LocalBridgeServer bridgeServer;

    private BridgeCore() {}

    /** 服务器(含单人集成服务器)启动完成后调用 */
    public static void onServerStarted(MinecraftServer s) {
        BridgeIO.log("bridge core: server started");
        server = s;
        try {
            // 1) 数据导出(供启动器 AI 使用):配方 + 物品属性
            RecipeExporter.export(s);
            ItemExporter.export(s);
            // 2) 本地指令口(主通道):TCP 监听,收到指令在服务器线程执行并回传结果
            bridgeServer = new LocalBridgeServer(s);
            bridgeServer.start();
            // 3) 备用通道:尝试自动开 RCON(失败不影响主通道)
            RconAutoOpener.tryOpen(s);
        } catch (Exception e) {
            BridgeIO.log("BridgeCore.onServerStarted failed: " + e);
        }
    }

    /** 服务器停止时调用 */
    public static void onServerStopped() {
        BridgeIO.log("bridge core: server stopped");
        if (bridgeServer != null) {
            bridgeServer.stop();
            bridgeServer = null;
        }
        server = null;
    }

    public static MinecraftServer getServer() {
        return server;
    }
}
