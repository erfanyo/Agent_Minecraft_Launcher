package com.agentmc.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import net.minecraft.command.CommandSource;
import net.minecraft.entity.player.ServerPlayerEntity;
import net.minecraft.server.MinecraftServer;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/**
 * 1.16.5 的受控本地指令通道。
 *
 * 这一代 Forge 不复用新版 TCP bridge：启动器写 command_request.json，服务端
 * tick 线程以指定在线玩家的 CommandSource 执行，再写 command_reply.json。
 * 因此不会把游戏内 AI 的请求悄悄降级为控制台权限。
 */
public final class FileCommandBridge {
    private FileCommandBridge() { }

    public static void poll(MinecraftServer server) {
        File dir = BridgeIO.bridgeDir(server);
        File requestFile = new File(dir, "command_request.json");
        if (!requestFile.isFile()) return;
        JsonObject request;
        try {
            String raw = new String(Files.readAllBytes(requestFile.toPath()), StandardCharsets.UTF_8);
            request = new Gson().fromJson(raw, JsonObject.class);
            if (request == null || !request.has("seq") || !request.has("command")) return;
            // 先移走请求，执行失败也不会在每个 tick 重复执行同一条命令。
            if (!requestFile.delete()) return;
        } catch (Exception ignored) { return; }

        long seq = request.get("seq").getAsLong();
        String command = request.get("command").getAsString().trim();
        String playerName = request.has("as_player") ? request.get("as_player").getAsString().trim() : "";
        JsonObject reply = new JsonObject();
        reply.addProperty("seq", seq);
        if (command.startsWith("/")) command = command.substring(1);
        if (command.length() == 0) {
            reply.addProperty("success", false); reply.addProperty("result", "命令为空");
            BridgeIO.write(new File(dir, "command_reply.json"), new Gson().toJson(reply)); return;
        }
        // 游戏内 AI 一律指定发起玩家；找不到玩家时宁可拒绝，也绝不使用控制台身份。
        ServerPlayerEntity player = playerName.length() == 0 ? null
                : server.getPlayerList().getPlayerByName(playerName);
        if (player == null) {
            reply.addProperty("success", false); reply.addProperty("result", "发起玩家不在线，未执行命令");
            BridgeIO.write(new File(dir, "command_reply.json"), new Gson().toJson(reply)); return;
        }
        try {
            CommandSource source = player.createCommandSourceStack();
            int result = server.getCommands().performCommand(source, command);
            reply.addProperty("success", result > 0);
            reply.addProperty("result", result > 0 ? "命令已执行" : "命令未执行（Minecraft 拒绝或没有匹配目标）");
        } catch (Exception e) {
            reply.addProperty("success", false); reply.addProperty("result", "执行失败: " + e.getClass().getSimpleName());
        }
        BridgeIO.write(new File(dir, "command_reply.json"), new Gson().toJson(reply));
    }
}
