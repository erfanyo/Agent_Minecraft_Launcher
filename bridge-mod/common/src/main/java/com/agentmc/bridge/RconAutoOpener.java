package com.agentmc.bridge;

import net.minecraft.server.MinecraftServer;

import java.lang.reflect.Method;
import java.nio.file.Path;

/**
 * 备用通道:尝试自动开启原版 RCON(单人集成服务器默认不监听 RCON)。
 *
 * 原版开 RCON 的入口随版本变化较大(1.20.x 用 RconThread,1.21 也类似),
 * 这里用反射按多种候选签名尝试;失败只记日志,不影响主通道(本地指令口)。
 * 适配新版本时主要改这里。
 */
public final class RconAutoOpener {

    private RconAutoOpener() {}

    public static void tryOpen(MinecraftServer server) {
        try {
            Path dir = BridgeIO.bridgeDir(server);
            // 读取 server.properties(集成服务器目录下的文件,可能不存在)
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
            int port = Integer.parseInt(props.getProperty("rcon.port", "25575"));
            String password = props.getProperty("rcon.password", "");
            if (password.isEmpty()) {
                BridgeIO.log("rcon password empty, skip");
                return;
            }

            // 反射:net.minecraft.server.rcon.thread.RconThread
            Class<?> rconThread = Class.forName("net.minecraft.server.rcon.thread.RconThread");
            Object thread = null;
            // 候选签名 1:create(MinecraftServer, String password) —— 部分版本
            try {
                Method m = rconThread.getMethod("create", MinecraftServer.class, String.class);
                thread = m.invoke(null, server, password);
            } catch (NoSuchMethodException e1) {
                // 候选签名 2:create(ServerInterface, String password, int port)
                try {
                    Class<?> si = Class.forName("net.minecraft.server.rcon.thread.ServerInterface");
                    Method m = rconThread.getMethod("create", si, String.class, int.class);
                    thread = m.invoke(null, server, password, port);
                } catch (NoSuchMethodException e2) {
                    BridgeIO.log("rcon reflection signature not found; adapt for this MC version");
                    return;
                }
            }
            if (thread instanceof Thread t) {
                t.start();
                BridgeIO.log("rcon auto-opened on port " + port);
            }
        } catch (Exception e) {
            BridgeIO.log("rcon open failed: " + e);
        }
    }
}
