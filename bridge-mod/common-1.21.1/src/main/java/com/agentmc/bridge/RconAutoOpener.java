package com.agentmc.bridge;

import net.minecraft.server.MinecraftServer;
import net.minecraft.server.dedicated.DedicatedServer;

import java.nio.file.Path;

/**
 * 备用通道:尝试自动开启原版 RCON(MC 1.21.1 版)。
 *
 * ⚠ 现状与勘误(2026-08-26 定,1.21.1 结论一致):
 * - 只有 `DedicatedServer` 才自行管理 RCON;集成服务器(单人/局域网)不适用本通道。
 * - **专用服务器 vanilla 已自行开 RCON**:`enable-rcon=true` 时原版会启动 RCON,
 *   本 mod 再开只会端口占用,因此检测到专用服务器直接跳过。
 * - 本类定位:仅在"可能需要"时尽力触发,失败只记日志,绝不影响主通道(本地指令口 TCP 26100)。
 *
 * 与 common-1.20.1 的差异:
 * - 1.21 的 getServerDirectory() 已返回 Path,不需要 .toPath();
 * - 去掉了本类从未使用的 RconThread / ServerInterface 导入(1.21 包结构已变)。
 */
public final class RconAutoOpener {

    private RconAutoOpener() {}

    public static void tryOpen(MinecraftServer server) {
        try {
            java.util.Properties props = new java.util.Properties();
            Path sp = server.getServerDirectory().resolve("server.properties");
            if (java.nio.file.Files.exists(sp)) {
                try (java.io.InputStream in = java.nio.file.Files.newInputStream(sp)) {
                    props.load(in);
                }
            }
            boolean enabled = Boolean.parseBoolean(props.getProperty("enable-rcon", "false"));
            if (!enabled) {
                BridgeIO.log("rcon disabled in server.properties (enable-rcon=true 可开启备用通道)");
                return;
            }
            if (server instanceof DedicatedServer) {
                BridgeIO.log("rcon already managed by vanilla on dedicated server; skip auto-open");
                return;
            }
            BridgeIO.log("rcon auto-open skip: non-dedicated server");
        } catch (Exception e) {
            BridgeIO.log("rcon auto-open failed: " + e);
        }
    }
}
