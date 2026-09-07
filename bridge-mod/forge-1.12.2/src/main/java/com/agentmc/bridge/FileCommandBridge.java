package com.agentmc.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.server.MinecraftServer;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** 启动器到 1.12.2 游戏的受控文件指令通道。 */
public final class FileCommandBridge {
    private FileCommandBridge() { }

    public static void poll(MinecraftServer server) {
        File dir = BridgeIO.bridgeDir(server);
        File requestFile = new File(dir, "command_request.json");
        if (!requestFile.isFile()) return;
        JsonObject request;
        try {
            request = new Gson().fromJson(new String(Files.readAllBytes(requestFile.toPath()), StandardCharsets.UTF_8), JsonObject.class);
            if (request == null || !request.has("seq") || !request.has("command") || !requestFile.delete()) return;
        } catch (Exception ignored) { return; }
        JsonObject reply = new JsonObject();
        reply.addProperty("seq", request.get("seq").getAsLong());
        String command = request.get("command").getAsString().trim();
        if (command.startsWith("/")) command = command.substring(1);
        String playerName = request.has("as_player") ? request.get("as_player").getAsString() : "";
        EntityPlayerMP player = server.getPlayerList().getPlayerByUsername(playerName);
        if (player == null) {
            reply.addProperty("success", false); reply.addProperty("result", "发起玩家不在线，未执行命令");
        } else if (command.length() == 0) {
            reply.addProperty("success", false); reply.addProperty("result", "命令为空");
        } else {
            try {
                int result = server.getCommandManager().executeCommand(player, command);
                reply.addProperty("success", result > 0);
                reply.addProperty("result", result > 0 ? "命令已执行" : "命令未执行（Minecraft 拒绝或没有匹配目标）");
            } catch (Exception e) {
                reply.addProperty("success", false); reply.addProperty("result", "执行失败: " + e.getClass().getSimpleName());
            }
        }
        BridgeIO.write(new File(dir, "command_reply.json"), new Gson().toJson(reply));
    }
}
