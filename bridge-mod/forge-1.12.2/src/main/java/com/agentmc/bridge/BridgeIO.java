package com.agentmc.bridge;

import net.minecraft.server.MinecraftServer;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;

/** 文件协议的最小兼容实现，避免旧 Forge 引入新版网络依赖。 */
public final class BridgeIO {
    private BridgeIO() { }

    public static File bridgeDir(MinecraftServer server) {
        File dir = server.getFile(".bridge");
        dir.mkdirs();
        return dir;
    }

    public static void write(File file, String text) {
        try {
            Writer out = new OutputStreamWriter(new FileOutputStream(file), StandardCharsets.UTF_8);
            out.write(text);
            out.close();
        } catch (Exception ignored) { }
    }
}
