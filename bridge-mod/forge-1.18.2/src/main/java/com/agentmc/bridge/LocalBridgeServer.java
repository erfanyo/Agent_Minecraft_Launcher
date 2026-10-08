package com.agentmc.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

/** Local authenticated command channel for Minecraft 1.18.2. */
public class LocalBridgeServer {
    private static final int PORT = 26100;
    private final MinecraftServer server;
    private final String token;
    private ServerSocket socket;
    private volatile boolean running;

    public LocalBridgeServer(MinecraftServer server) {
        this.server = server;
        this.token = UUID.randomUUID().toString().replace("-", "");
        BridgeIO.write(BridgeIO.bridgeDir(server).resolve("token.txt"), token);
    }

    public void start() {
        try { socket = new ServerSocket(PORT, 8, java.net.InetAddress.getByName("127.0.0.1")); }
        catch (IOException e) { BridgeIO.log("bridge port busy: " + e); return; }
        running = true;
        Thread thread = new Thread(this::acceptLoop, "bridge-accept");
        thread.setDaemon(true); thread.start();
        BridgeIO.log("bridge listening on 127.0.0.1:" + socket.getLocalPort());
    }

    public void stop() {
        running = false; BridgeIO.log("bridge stopped");
        try { if (socket != null) socket.close(); } catch (IOException ignored) { }
    }

    private void acceptLoop() {
        while (running) {
            try { handle(socket.accept()); }
            catch (IOException e) { if (running) BridgeIO.log("accept error: " + e); }
        }
    }

    private void handle(Socket client) {
        OutputStream out = null;
        try {
            BufferedReader in = new BufferedReader(
                    new InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8));
            out = client.getOutputStream();
            String line = in.readLine();
            if (line == null || line.isBlank()) { closeQuietly(client); return; }
            JsonObject request;
            try { request = new Gson().fromJson(line, JsonObject.class); }
            catch (Exception e) { closeQuietly(client); return; }
            if (request == null || !request.has("token") || !token.equals(request.get("token").getAsString())) {
                out.write("{\"error\":\"bad token\"}\n".getBytes(StandardCharsets.UTF_8));
                out.flush();
                closeQuietly(client);
                return;
            }
            String command = request.has("command") ? request.get("command").getAsString() : "";
            long seq = request.has("seq") ? request.get("seq").getAsLong() : 0L;
            String asPlayer = request.has("as_player") ? request.get("as_player").getAsString() : "";
            if (command.isBlank()) { closeQuietly(client); return; }
            BridgeIO.log("bridge got command: " + command + (asPlayer.isEmpty() ? "" : " (as_player=" + asPlayer + ")"));
            final OutputStream replyOut = out;
            CommandBridgeSource sink = new CommandBridgeSource(seq, command, server);
            // ⚠ 两条坑(与 common/LocalBridgeServer 同步修):
            // 1) 命令是异步在服务器线程执行的,不能在 handle 里用 try-with-resources 关连接,
            //    否则结果写不回 socket,启动器只收到空响应 —— 表现就是"说发了指令但游戏没执行";
            // 2) 启动器发来的指令带前导 "/",必须用 performPrefixedCommand(会去掉 "/");
            //    performCommand 不认 "/",会解析失败并静默什么都不做。
            server.execute(() -> {
                try {
                    CommandSourceStack source = server.createCommandSourceStack();
                    if (!asPlayer.isEmpty()) {
                        ServerPlayer player = findPlayer(asPlayer);
                        if (player == null) {
                            sink.fail("as_player specified player is offline: " + asPlayer);
                            return;
                        }
                        source = source.withEntity(player).withSource(player);
                    }
                    source = source.withSource(sink);
                    // 1.18.2 没有 performPrefixedCommand(1.19 才加入),这里自己剥掉前导 "/";
                    // performCommand 返回执行结果数(0 = 没执行/被拒绝),正好用来判定成功与否。
                    String cmd = command.startsWith("/") ? command.substring(1) : command;
                    int result = server.getCommands().performCommand(source, cmd);
                    sink.markResult(result > 0);
                } catch (Exception e) {
                    sink.fail(e.toString());
                } finally {
                    sink.flushTo(replyOut, server);
                    closeQuietly(client);
                }
            });
        } catch (Exception e) {
            BridgeIO.log("bridge handle error: " + e);
            closeQuietly(client);
        }
    }

    private static void closeQuietly(Socket socket) {
        try { if (socket != null) socket.close(); } catch (IOException ignored) { }
    }

    private ServerPlayer findPlayer(String nameOrUuid) {
        if (nameOrUuid == null || nameOrUuid.isBlank()) return null;
        try {
            var list = server.getPlayerList();
            ServerPlayer byName = list.getPlayerByName(nameOrUuid);
            if (byName != null) return byName;
            try { return list.getPlayer(UUID.fromString(nameOrUuid)); } catch (Exception ignored) { }
            for (ServerPlayer player : list.getPlayers()) if (player.getGameProfile().getName().equalsIgnoreCase(nameOrUuid)) return player;
        } catch (Exception ignored) { }
        return null;
    }
}
