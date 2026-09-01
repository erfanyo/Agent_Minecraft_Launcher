package com.agentmc.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.builder.LiteralArgumentBuilder;
import com.mojang.brigadier.context.CommandContext;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.Vec3;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 游戏内 AI 入口(mod 侧):
 * 玩家敲 {@code /ai <描述>},把问题交给启动器 AI(写 .bridge/ai_request.json),
 * launcher 侧 InGameAI 轮询 → 调启动器 AI(带工具) → 写 .bridge/ai_reply.json;
 * 本类后台轮询回复,把结果回显到发起者聊天窗(类似"天气已改为晴天")。
 *
 * 指令注册交给 fabric 的 CommandsMixin(在指令树构建时注册,保证 /ai 补全正常)。
 * 协议:
 *   请求 .bridge/ai_request.json = {"seq":N,"text":"<描述>","ts":<毫秒>}
 *   回复 .bridge/ai_reply.json   = {"seq":N,"text":"<AI 回答>","ts":<毫秒>}
 */
public final class AiChat {

    private static final AtomicLong SEQ = new AtomicLong(0);
    private static final long TIMEOUT_MS = 120_000L;   // 等回复超时:2 分钟
    private static final long POLL_INTERVAL_MS = 500L;   // 轮询间隔

    private AiChat() {}

    /** 构造 /ai 指令构建器(由 CommandsMixin 在指令树构建时挂到根) */
    public static LiteralArgumentBuilder<CommandSourceStack> command() {
        return Commands.literal("ai")
                .requires(src -> true)   // 任意玩家可用
                .executes(ctx -> {
                    ctx.getSource().sendSystemMessage(Component.literal("用法: /ai <你的问题>"));
                    return 1;
                })
                .then(Commands.argument("描述", StringArgumentType.greedyString())
                        .executes(AiChat::submit));
    }

    private static int submit(CommandContext<CommandSourceStack> ctx) {
        CommandSourceStack src = ctx.getSource();
        MinecraftServer server = src.getServer();
        String prompt = StringArgumentType.getString(ctx, "描述").trim();
        // --console 前缀:仅 level 4 玩家可选(AI 执行指令用控制台身份);非 level4 忽略该标记
        boolean console = false;
        if (prompt.startsWith("--console")) {
            if (src.hasPermission(4)) {
                console = true;
                prompt = prompt.substring("--console".length()).trim();
            } else {
                // 非 level4:忽略标记,仍按玩家身份;给玩家一个说明
                prompt = prompt.substring("--console".length()).trim();
            }
        }
        if (prompt.isEmpty()) {
            src.sendSystemMessage(Component.literal("用法: /ai <你的问题>"));
            return 1;
        }
        long seq = SEQ.incrementAndGet();
        JsonObject req = new JsonObject();
        req.addProperty("seq", seq);
        req.addProperty("text", prompt);
        req.addProperty("ts", System.currentTimeMillis());
        req.addProperty("protocol_version", 2);

        // ---- 上下文与权限上报(§3.1 协议字段)----
        ServerPlayer playerEnt = (src.getEntity() instanceof ServerPlayer p) ? p : null;
        String playerName = playerEnt != null
                ? playerEnt.getGameProfile().getName() : "";
        boolean isOp = src.hasPermission(2);
        int permissionLevel = 0;
        for (int level = 4; level >= 0; level--) {
            if (src.hasPermission(level)) {
                permissionLevel = level;
                break;
            }
        }
        req.addProperty("player", playerName);
        req.addProperty("is_op", isOp);
        req.addProperty("permission_level", permissionLevel);
        req.addProperty("exec_mode", console ? "console" : "player");
        // server.isPublished() 只说明“已对 LAN 开放”，不能说明发起者就是房主。
        // 因此同时上报集成服房主身份，启动器绝不能只凭 server_type=lan 放行。
        boolean dedicated = server.isDedicatedServer();
        String serverType = dedicated ? "dedicated"
                : (server.isPublished() ? "lan" : "singleplayer");
        req.addProperty("server_type", serverType);
        boolean integratedOwner = playerEnt != null && !dedicated
                && server.isSingleplayerOwner(playerEnt.getGameProfile());
        req.addProperty("is_integrated_owner", integratedOwner);
        if (playerEnt != null) {
            try {
                Vec3 pos = playerEnt.position();
                req.addProperty("pos", String.format("%.1f,%.1f,%.1f", pos.x, pos.y, pos.z));
            } catch (Exception ignored) { }
            try {
                String dim = playerEnt.level().dimension().location().toString();
                req.addProperty("dim", dim);
            } catch (Exception ignored) { }
            try {
                ItemStack held = playerEnt.getMainHandItem();
                if (held != null && !held.isEmpty()) {
                    req.addProperty("held", BuiltInRegistries.ITEM.getKey(held.getItem()).toString());
                }
            } catch (Exception ignored) { }
        }
        if (console) {
            // 说明:仅日志记录,不额外提示(玩家已显式请求)
            BridgeIO.log("/ai --console by " + playerName + " (level4)");
        }

        BridgeIO.write(BridgeIO.bridgeDir(server).resolve("ai_request.json"),
                new Gson().toJson(req) + System.lineSeparator());
        src.sendSystemMessage(Component.literal("已提交 AI 处理(seq=" + seq + "),思考中…"));
        Path replyPath = BridgeIO.bridgeDir(server).resolve("ai_reply.json");
        Thread t = new Thread(() -> pollReply(server, seq, playerEnt, replyPath), "bridge-ai-poll-" + seq);
        t.setDaemon(true);
        t.start();
        return 1;
    }

    private static void pollReply(MinecraftServer server, long seq, ServerPlayer requester, Path replyPath) {
        long deadline = System.currentTimeMillis() + TIMEOUT_MS;
        while (System.currentTimeMillis() < deadline) {
            try {
                if (Files.exists(replyPath)) {
                    JsonObject o = new Gson().fromJson(Files.readString(replyPath), JsonObject.class);
                    if (o != null && o.has("seq") && o.get("seq").getAsLong() == seq && o.has("text")) {
                        String reply = o.get("text").getAsString();
                        if (reply != null && !reply.isBlank()) {
                            echo(server, requester, "[AI] " + reply);
                            // 消费掉当前回复,避免重复回显
                            try { Files.deleteIfExists(replyPath); } catch (Exception ignored) {}
                            return;
                        }
                    }
                }
            } catch (Exception ignored) {
            }
            try { Thread.sleep(POLL_INTERVAL_MS); } catch (InterruptedException ie) { return; }
        }
        echo(server, requester, "[AI] 处理超时(未收到 launcher 侧回复,请确认游戏内 AI 已开启)");
    }

    private static void echo(MinecraftServer server, ServerPlayer requester, String text) {
        if (server == null) return;
        server.execute(() -> {
            Component msg = Component.literal(text);
            if (requester != null && requester.isAlive()) {
                requester.sendSystemMessage(msg);
            } else {
                server.getPlayerList().broadcastSystemMessage(msg, false);
            }
        });
    }
}
