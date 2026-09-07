package com.agentmc.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import net.minecraft.command.CommandBase;
import net.minecraft.command.CommandException;
import net.minecraft.command.ICommandSender;
import net.minecraft.entity.player.EntityPlayerMP;
import net.minecraft.server.MinecraftServer;
import net.minecraft.util.text.TextComponentString;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicLong;

/** 1.12.2 的 /ai 命令及协议 v2 权限上下文。 */
public final class AiChatCommand extends CommandBase {
    private static final AtomicLong SEQUENCE = new AtomicLong();

    @Override public String getName() { return "ai"; }
    @Override public String getUsage(ICommandSender sender) { return "/ai <想问的问题>"; }
    @Override public int getRequiredPermissionLevel() { return 0; }

    @Override public void execute(final MinecraftServer server, final ICommandSender sender, String[] args) throws CommandException {
        String text = String.join(" ", Arrays.asList(args)).trim();
        if (text.length() == 0) {
            sender.sendMessage(new TextComponentString("[AI] 用法: /ai <想问的问题>"));
            return;
        }
        EntityPlayerMP player = sender instanceof EntityPlayerMP ? (EntityPlayerMP) sender : null;
        boolean dedicated = server.isDedicatedServer();
        boolean owner = player != null && !dedicated && player.getName().equals(server.getServerOwner());
        boolean isOp = player != null && (server.getPlayerList().canSendCommands(player.getGameProfile()) || owner);
        long seq = SEQUENCE.incrementAndGet();
        JsonObject request = new JsonObject();
        request.addProperty("seq", seq);
        request.addProperty("text", text);
        request.addProperty("ts", System.currentTimeMillis());
        request.addProperty("protocol_version", 2);
        request.addProperty("player", player == null ? "" : player.getName());
        request.addProperty("is_op", isOp);
        request.addProperty("permission_level", isOp ? 4 : 0);
        request.addProperty("exec_mode", "player");
        request.addProperty("server_type", dedicated ? "dedicated" : "singleplayer");
        request.addProperty("is_integrated_owner", owner);
        final File reply = new File(BridgeIO.bridgeDir(server), "ai_reply.json");
        BridgeIO.write(new File(BridgeIO.bridgeDir(server), "ai_request.json"), new Gson().toJson(request));
        sender.sendMessage(new TextComponentString("[AI] 已提交请求，正在思考…"));
        Thread poller = new Thread(new ReplyPoller(server, player, reply, seq), "agentmc-ai-reply");
        poller.setDaemon(true);
        poller.start();
    }

    private static final class ReplyPoller implements Runnable {
        private final MinecraftServer server; private final EntityPlayerMP player; private final File reply; private final long seq;
        private ReplyPoller(MinecraftServer server, EntityPlayerMP player, File reply, long seq) {
            this.server = server; this.player = player; this.reply = reply; this.seq = seq;
        }
        @Override public void run() {
            long deadline = System.currentTimeMillis() + 120000L;
            while (System.currentTimeMillis() < deadline) {
                try {
                    JsonObject result = new Gson().fromJson(new String(Files.readAllBytes(reply.toPath()), StandardCharsets.UTF_8), JsonObject.class);
                    if (result != null && result.has("seq") && result.get("seq").getAsLong() == seq && result.has("text")) {
                        final String message = result.get("text").getAsString();
                        reply.delete();
                        server.addScheduledTask(new Runnable() { @Override public void run() {
                            if (player != null && player.isEntityAlive()) player.sendMessage(new TextComponentString("[AI] " + message));
                        }});
                        return;
                    }
                } catch (Exception ignored) { }
                try { Thread.sleep(500L); } catch (InterruptedException ignored) { return; }
            }
        }
    }
}
