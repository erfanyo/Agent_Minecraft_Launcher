package com.agentmc.bridge;

import net.minecraft.server.MinecraftServer;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * 桥接 IO 工具:数据目录约定 + 日志。
 * 数据目录 = 服务器运行目录(版本隔离时 = versions/&lt;id&gt;)下的 .bridge/。
 */
public final class BridgeIO {

    private BridgeIO() {}

    /** 服务器运行目录的 .bridge 子目录(不存在则创建) */
    public static Path bridgeDir(MinecraftServer server) {
        Path root = server.getServerDirectory();   // 1.20.5+ 提供
        return bridgeDirFrom(root);
    }

    /** 任意根目录下的 .bridge 子目录(客户端按键导出等用) */
    public static Path bridgeDirFrom(Path root) {
        Path dir = root.resolve(".bridge");
        try {
            Files.createDirectories(dir);
        } catch (Exception ignored) {
        }
        return dir;
    }

    public static void write(Path path, String content) {
        try {
            Files.writeString(path, content);
        } catch (Exception e) {
            log("write failed " + path + ": " + e);
        }
    }

    public static void log(String msg) {
        try {
            Path dir = Paths.get(".").toAbsolutePath().resolve(".bridge");
            Files.createDirectories(dir);
            Files.writeString(dir.resolve("bridge_mod.log"),
                    java.time.LocalDateTime.now() + " " + msg + System.lineSeparator(),
                    java.nio.file.StandardOpenOption.CREATE,
                    java.nio.file.StandardOpenOption.APPEND);
        } catch (Exception ignored) {
        }
    }
}
