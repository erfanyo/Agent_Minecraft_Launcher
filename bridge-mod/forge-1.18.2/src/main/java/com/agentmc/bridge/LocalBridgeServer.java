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
        try (client;
             BufferedReader in = new BufferedReader(new InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8));
             OutputStream out = client.getOutputStream()) {
            String line = in.readLine();
            if (line == null || line.isBlank()) return;
            JsonObject request;
            try { request = new Gson().fromJson(line, JsonObject.class); } catch (Exception e) { return; }
            if (request == null || !request.has("token") || !token.equals(request.get("token").getAsString())) {
                out.write("{\"error\":\"bad token\"}\n".getBytes(StandardCharsets.UTF_8)); return;
            }
            String command = request.has("command") ? request.get("command").getAsString() : "";
            long seq = request.has("seq") ? request.get("seq").getAsLong() : 0L;
            String asPlayer = request.has("as_player") ? request.get("as_player").getAsString() : "";
            if (command.isBlank()) return;
            BridgeIO.log("bridge got command: " + command + (asPlayer.isEmpty() ? "" : " (as_player=" + asPlayer + ")"));
            CommandBridgeSource sink = new CommandBridgeSource(seq, command, server);
            server.execute(() -> {
                try {
                    CommandSourceStack source = server.createCommandSourceStack();
                    if (!asPlayer.isEmpty()) {
                        ServerPlayer player = findPlayer(asPlayer);
                        if (player == null) { sink.fail("as_player specified player is offline: " + asPlayer); sink.flushTo(out, server); return; }
                        source = source.withEntity(player).withSource(player);
                    }
                    source = source.withSource(sink);
                    Commands commands = server.getCommands();
                    commands.performCommand(source, command);
                    sink.markResult(true);
                    sink.flushTo(out, server);
                } catch (Exception e) { sink.fail(e.toString()); sink.flushTo(out, server); }
            });
        } catch (IOException ignored) { }
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
