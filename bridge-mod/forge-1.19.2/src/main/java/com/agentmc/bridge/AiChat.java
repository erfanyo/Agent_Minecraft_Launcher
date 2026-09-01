package com.agentmc.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.builder.LiteralArgumentBuilder;
import com.mojang.brigadier.context.CommandContext;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.Registry;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.Vec3;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicLong;

/** 1.19.2 版 /ai 文件交换入口；协议字段与现代实现保持一致。 */
public final class AiChat {
    private static final AtomicLong SEQ = new AtomicLong(0);
    private static final long TIMEOUT_MS = 120_000L, POLL_INTERVAL_MS = 500L;
    private AiChat() {}

    public static LiteralArgumentBuilder<CommandSourceStack> command() {
        return Commands.literal("ai").requires(src -> true)
                .executes(ctx -> { ctx.getSource().sendSystemMessage(Component.literal("用法: /ai <你的问题>")); return 1; })
                .then(Commands.argument("描述", StringArgumentType.greedyString()).executes(AiChat::submit));
    }

    private static int submit(CommandContext<CommandSourceStack> ctx) {
        CommandSourceStack src = ctx.getSource();
        MinecraftServer server = src.getServer();
        String prompt = StringArgumentType.getString(ctx, "描述").trim();
        boolean console = prompt.startsWith("--console") && src.hasPermission(4);
        if (prompt.startsWith("--console")) prompt = prompt.substring("--console".length()).trim();
        if (prompt.isEmpty()) { src.sendSystemMessage(Component.literal("用法: /ai <你的问题>")); return 1; }
        long seq = SEQ.incrementAndGet();
        JsonObject req = new JsonObject();
        req.addProperty("seq", seq); req.addProperty("text", prompt); req.addProperty("ts", System.currentTimeMillis());
        req.addProperty("protocol_version", 2);
        ServerPlayer player = src.getEntity() instanceof ServerPlayer p ? p : null;
        String name = player == null ? "" : player.getGameProfile().getName();
        req.addProperty("player", name); req.addProperty("is_op", src.hasPermission(2));
        int level = 0; for (int i = 4; i >= 0; i--) if (src.hasPermission(i)) { level = i; break; }
        req.addProperty("permission_level", level); req.addProperty("exec_mode", console ? "console" : "player");
        boolean dedicated = server.isDedicatedServer();
        req.addProperty("server_type", dedicated ? "dedicated" : (server.isPublished() ? "lan" : "singleplayer"));
        req.addProperty("is_integrated_owner", player != null && !dedicated && server.isSingleplayerOwner(player.getGameProfile()));
        if (player != null) {
            try { Vec3 pos = player.position(); req.addProperty("pos", String.format("%.1f,%.1f,%.1f", pos.x, pos.y, pos.z)); } catch (Exception ignored) {}
            try { req.addProperty("dim", player.getLevel().dimension().location().toString()); } catch (Exception ignored) {}
            try { ItemStack held = player.getMainHandItem(); if (!held.isEmpty()) req.addProperty("held", Registry.ITEM.getKey(held.getItem()).toString()); } catch (Exception ignored) {}
        }
        if (console) BridgeIO.log("/ai --console by " + name + " (level4)");
        BridgeIO.write(BridgeIO.bridgeDir(server).resolve("ai_request.json"), new Gson().toJson(req) + System.lineSeparator());
        src.sendSystemMessage(Component.literal("已提交 AI 处理(seq=" + seq + "),思考中…"));
        Path reply = BridgeIO.bridgeDir(server).resolve("ai_reply.json");
        Thread t = new Thread(() -> pollReply(server, seq, player, reply), "bridge-ai-poll-" + seq); t.setDaemon(true); t.start();
        return 1;
    }

    private static void pollReply(MinecraftServer server, long seq, ServerPlayer requester, Path reply) {
        long deadline = System.currentTimeMillis() + TIMEOUT_MS;
        while (System.currentTimeMillis() < deadline) {
            try {
                if (Files.exists(reply)) {
                    JsonObject o = new Gson().fromJson(Files.readString(reply), JsonObject.class);
                    if (o != null && o.has("seq") && o.get("seq").getAsLong() == seq && o.has("text")) {
                        String text = o.get("text").getAsString(); if (text != null && !text.isBlank()) { echo(server, requester, "[AI] " + text); Files.deleteIfExists(reply); return; }
                    }
                }
            } catch (Exception ignored) {}
            try { Thread.sleep(POLL_INTERVAL_MS); } catch (InterruptedException ignored) { return; }
        }
        echo(server, requester, "[AI] 处理超时(未收到 launcher 侧回复,请确认游戏内 AI 已开启)");
    }

    private static void echo(MinecraftServer server, ServerPlayer requester, String text) {
        if (server == null) return;
        server.execute(() -> { Component msg = Component.literal(text); if (requester != null && requester.isAlive()) requester.sendSystemMessage(msg); else server.getPlayerList().broadcastSystemMessage(msg, false); });
    }
}
