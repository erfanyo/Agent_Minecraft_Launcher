package com.agentmc.bridge;

import net.minecraft.server.MinecraftServer;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;

/** Java 8 / Minecraft 1.16.5 bridge file helpers. */
public final class BridgeIO {
    private BridgeIO() { }
    public static File bridgeDir(MinecraftServer server) {
        File dir = new File(server.getServerDirectory(), ".bridge");
        dir.mkdirs();
        return dir;
    }
    public static void write(File file, String text) {
        try {
            Writer out = new OutputStreamWriter(new FileOutputStream(file), StandardCharsets.UTF_8);
            out.write(text); out.close();
        } catch (Exception ignored) { }
    }
}
