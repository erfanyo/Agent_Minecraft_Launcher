package com.agentmc.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.builder.LiteralArgumentBuilder;
import com.mojang.brigadier.context.CommandContext;
import net.minecraft.command.CommandSource;
import net.minecraft.command.Commands;
import net.minecraft.entity.player.ServerPlayerEntity;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.atomic.AtomicLong;

/** Minecraft 1.16.5 Java 8 compatible /ai request endpoint. */
public final class AiChat {
    private static final AtomicLong SEQ = new AtomicLong();
    private static final long TIMEOUT_MS = 120000L;
    private static final long POLL_INTERVAL_MS = 500L;
    private AiChat() { }
    public static LiteralArgumentBuilder<CommandSource> command() {
        return Commands.literal("ai").executes(c -> usage(c.getSource()))
            .then(Commands.argument("text", StringArgumentType.greedyString()).executes(AiChat::submit));
    }

    private static int usage(CommandSource source) {
        tell(source, "[AI] 用法: /ai <想问的问题>");
        return 1;
    }
    private static int submit(CommandContext<CommandSource> context) {
        CommandSource source = context.getSource();
        String text = StringArgumentType.getString(context, "text").trim();
        net.minecraft.server.MinecraftServer server = source.getServer();
        ServerPlayerEntity player = source.getEntity() instanceof ServerPlayerEntity ? (ServerPlayerEntity) source.getEntity() : null;
        // 单人游戏即使尚未开启作弊，房主的 CommandSource 也可能没有传统
        // OP 标记。把“集成服房主”单独上报，启动器可放行 AI 的受控工具调用，
        // 实际命令仍以该玩家身份执行，MC 自己决定是否允许该命令。
        boolean dedicated = server.isDedicatedServer();
        boolean integratedOwner = player != null && !dedicated
                && server.isSingleplayerOwner(player.getGameProfile());
        boolean console = text.startsWith("--console") && (source.hasPermission(4) || integratedOwner);
        if (text.startsWith("--console")) text = text.substring("--console".length()).trim();
        if (text.length() == 0) return usage(source);
        long seq = SEQ.incrementAndGet();
        JsonObject request = new JsonObject();
        request.addProperty("seq", seq); request.addProperty("text", text); request.addProperty("ts", System.currentTimeMillis()); request.addProperty("protocol_version", 2);
        request.addProperty("player", player == null ? "" : player.getGameProfile().getName());
        request.addProperty("is_op", source.hasPermission(2) || integratedOwner);
        int permissionLevel = 0;
        for (int level = 4; level >= 0; level--) {
            if (source.hasPermission(level)) { permissionLevel = level; break; }
        }
        if (integratedOwner) permissionLevel = Math.max(permissionLevel, 4);
        request.addProperty("permission_level", permissionLevel);
        request.addProperty("exec_mode", console ? "console" : "player");
        request.addProperty("server_type", dedicated ? "dedicated" : (server.isPublished() ? "lan" : "singleplayer"));
        request.addProperty("is_integrated_owner", integratedOwner);
        File requestFile = new File(BridgeIO.bridgeDir(server), "ai_request.json");
        BridgeIO.write(requestFile, new Gson().toJson(request) + System.lineSeparator());
        File replyFile = new File(BridgeIO.bridgeDir(server), "ai_reply.json");
        Thread thread = new Thread(new ReplyPoller(server, seq, player, replyFile), "bridge-ai-poll-" + seq);
        thread.setDaemon(true);
        thread.start();
        tell(source, "[AI] 已提交请求，正在思考…");
        return 1;
    }

    private static void tell(CommandSource source, String text) {
        if (source.getEntity() instanceof ServerPlayerEntity) {
            ServerPlayerEntity player = (ServerPlayerEntity) source.getEntity();
            player.sendMessage(new net.minecraft.util.text.StringTextComponent(text), player.getUUID());
        }
    }

    private static final class ReplyPoller implements Runnable {
        private final net.minecraft.server.MinecraftServer server;
        private final long sequence;
        private final ServerPlayerEntity requester;
        private final File replyFile;

        private ReplyPoller(net.minecraft.server.MinecraftServer server, long sequence, ServerPlayerEntity requester, File replyFile) {
            this.server = server;
            this.sequence = sequence;
            this.requester = requester;
            this.replyFile = replyFile;
        }

        @Override public void run() {
            long deadline = System.currentTimeMillis() + TIMEOUT_MS;
            while (System.currentTimeMillis() < deadline) {
                try {
                    if (replyFile.isFile()) {
                        String json = new String(Files.readAllBytes(replyFile.toPath()), StandardCharsets.UTF_8);
                        JsonObject response = new Gson().fromJson(json, JsonObject.class);
                        if (response != null && response.has("seq") && response.get("seq").getAsLong() == sequence && response.has("text")) {
                            final String text = response.get("text").getAsString();
                            if (text != null && text.trim().length() > 0) {
                                if (!replyFile.delete()) { /* the next reply may overwrite this file */ }
                                server.execute(new Runnable() {
                                    @Override public void run() {
                                        if (requester != null && requester.isAlive()) {
                                            requester.sendMessage(new net.minecraft.util.text.StringTextComponent("[AI] " + text), requester.getUUID());
                                        }
                                    }
                                });
                                return;
                            }
                        }
                    }
                } catch (Exception ignored) { }
                try { Thread.sleep(POLL_INTERVAL_MS); } catch (InterruptedException ignored) { return; }
            }
        }
    }
}
