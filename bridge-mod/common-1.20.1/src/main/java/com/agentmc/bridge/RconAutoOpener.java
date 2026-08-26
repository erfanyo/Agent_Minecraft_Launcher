package com.agentmc.bridge;

import net.minecraft.server.MinecraftServer;
import net.minecraft.server.dedicated.DedicatedServer;
import net.minecraft.server.ServerInterface;
import net.minecraft.server.rcon.thread.RconThread;

import java.nio.file.Path;

/**
 * 备用通道:尝试自动开启原版 RCON。
 *
 * ⚠ 现状与勘误(2026-08-26 定):
 * - Forge/MC 1.20.1 下,只有 `DedicatedServer` implements `ServerInterface`;集成服务器(单人)不是,
 *   因此 RCON 的 RconThread.create(ServerInterface) 只能接受专用服务器,单人世界走不到这里。
 * - **专用服务器 vanilla 已自行开 RCON**:`DedicatedServer.initServer()` 在 enable-rcon=true 时
 *   会调用 `RconThread.m_11615_(ServerInterface)`(srg 名;/dev 下为 create)启动 RCON
 *   (实测日志 "RCON running on 0.0.0.0:25575")。所以本 mod 在专用服务器上**无需再开**——
 *   再开只会端口占用。
 * - 反射目标方法名:srg `m_11615_`(生产运行时)/ mojang `create`(dev)。反射字符串不会被 reobf 改写,
 *   故两套名字都试。
 * - 本类定位:仅在"可能需要"时尽力触发,失败只记日志,绝不影响主通道(本地指令口 TCP 26100)。
 */
public final class RconAutoOpener {

    private RconAutoOpener() {}

    public static void tryOpen(MinecraftServer server) {
        try {
            Path dir = BridgeIO.bridgeDir(server);
            java.util.Properties props = new java.util.Properties();
            Path sp = server.getServerDirectory().toPath().resolve("server.properties");
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
                // 专用服务器 vanilla 已自行开 RCON(enable-rcon=true),无需本 mod 再开
                BridgeIO.log("rcon already managed by vanilla on dedicated server; skip auto-open");
                return;
            }
            // 非专用服务器(单人集成服务器)在 1.20.1 不是 ServerInterface → RconcThread.create 拿不到参数
            BridgeIO.log("rcon auto-open skip: non-dedicated server (no ServerInterface in 1.20.1)");
        } catch (Exception e) {
            BridgeIO.log("rcon auto-open failed: " + e);
        }
    }
}
