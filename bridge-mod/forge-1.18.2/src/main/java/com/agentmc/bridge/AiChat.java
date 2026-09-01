package com.agentmc.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.builder.LiteralArgumentBuilder;
import com.mojang.brigadier.context.CommandContext;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.Registry;
import net.minecraft.Util;
import net.minecraft.network.chat.ChatType;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.TextComponent;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.Vec3;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicLong;

/** File-exchange /ai endpoint for Minecraft 1.18.2. */
public final class AiChat {
    private static final AtomicLong SEQ = new AtomicLong();
    private static final long TIMEOUT_MS = 120_000L, POLL_INTERVAL_MS = 500L;
    private AiChat() { }

    public static LiteralArgumentBuilder<CommandSourceStack> command() {
        return Commands.literal("ai").requires(source -> true)
                .executes(ctx -> { ctx.getSource().sendFailure(new TextComponent("Usage: /ai <your request>")); return 1; })
                .then(Commands.argument("description", StringArgumentType.greedyString()).executes(AiChat::submit));
    }

    private static int submit(CommandContext<CommandSourceStack> context) {
        CommandSourceStack source = context.getSource();
        MinecraftServer server = source.getServer();
        String prompt = StringArgumentType.getString(context, "description").trim();
        boolean console = prompt.startsWith("--console") && source.hasPermission(4);
        if (prompt.startsWith("--console")) prompt = prompt.substring("--console".length()).trim();
        if (prompt.isEmpty()) { source.sendFailure(new TextComponent("Usage: /ai <your request>")); return 1; }
        long seq = SEQ.incrementAndGet();
        JsonObject request = new JsonObject();
        request.addProperty("seq", seq); request.addProperty("text", prompt); request.addProperty("ts", System.currentTimeMillis());
        request.addProperty("protocol_version", 2);
        ServerPlayer player = source.getEntity() instanceof ServerPlayer p ? p : null;
        String name = player == null ? "" : player.getGameProfile().getName();
        request.addProperty("player", name); request.addProperty("is_op", source.hasPermission(2));
        int level = 0; for (int i = 4; i >= 0; i--) if (source.hasPermission(i)) { level = i; break; }
        request.addProperty("permission_level", level); request.addProperty("exec_mode", console ? "console" : "player");
        boolean dedicated = server.isDedicatedServer();
        request.addProperty("server_type", dedicated ? "dedicated" : (server.isPublished() ? "lan" : "singleplayer"));
        request.addProperty("is_integrated_owner", player != null && !dedicated && server.isSingleplayerOwner(player.getGameProfile()));
        if (player != null) {
            try { Vec3 pos = player.position(); request.addProperty("pos", String.format("%.1f,%.1f,%.1f", pos.x, pos.y, pos.z)); } catch (Exception ignored) { }
            try { request.addProperty("dim", player.getLevel().dimension().location().toString()); } catch (Exception ignored) { }
            try { ItemStack held = player.getMainHandItem(); if (!held.isEmpty()) request.addProperty("held", Registry.ITEM.getKey(held.getItem()).toString()); } catch (Exception ignored) { }
        }
        if (console) BridgeIO.log("/ai --console by " + name + " (level4)");
        BridgeIO.write(BridgeIO.bridgeDir(server).resolve("ai_request.json"), new Gson().toJson(request) + System.lineSeparator());
        source.sendSuccess(new TextComponent("AI request submitted (seq=" + seq + "), thinking…"), false);
        Path reply = BridgeIO.bridgeDir(server).resolve("ai_reply.json");
        Thread thread = new Thread(() -> pollReply(server, seq, player, reply), "bridge-ai-poll-" + seq);
        thread.setDaemon(true); thread.start();
        return 1;
    }

    private static void pollReply(MinecraftServer server, long seq, ServerPlayer requester, Path reply) {
        long deadline = System.currentTimeMillis() + TIMEOUT_MS;
        while (System.currentTimeMillis() < deadline) {
            try {
                if (Files.exists(reply)) {
                    JsonObject response = new Gson().fromJson(Files.readString(reply), JsonObject.class);
                    if (response != null && response.has("seq") && response.get("seq").getAsLong() == seq && response.has("text")) {
                        String text = response.get("text").getAsString();
                        if (text != null && !text.isBlank()) { echo(server, requester, "[AI] " + text); Files.deleteIfExists(reply); return; }
                    }
                }
            } catch (Exception ignored) { }
            try { Thread.sleep(POLL_INTERVAL_MS); } catch (InterruptedException ignored) { return; }
        }
        echo(server, requester, "[AI] timed out; check that in-game AI is enabled in the launcher.");
    }

    private static void echo(MinecraftServer server, ServerPlayer requester, String text) {
        if (server == null) return;
        server.execute(() -> {
            Component message = new TextComponent(text);
            if (requester != null && requester.isAlive()) requester.sendMessage(message, requester.getUUID());
            else server.getPlayerList().broadcastMessage(message, ChatType.SYSTEM, Util.NIL_UUID);
        });
    }
}
