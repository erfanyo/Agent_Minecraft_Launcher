package com.agentmc.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import net.minecraft.commands.CommandSource;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;

import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.UUID;

/** Command result capture for Minecraft 1.18.2. */
public class CommandBridgeSource implements CommandSource {
    private final long seq;
    private final String command;
    private final StringBuilder feedback = new StringBuilder();
    private volatile boolean done;
    private volatile boolean success;

    public CommandBridgeSource(long seq, String command, MinecraftServer server) { this.seq = seq; this.command = command; }
    @Override public void sendMessage(Component message, UUID sender) { feedback.append(message.getString()).append("\n"); }
    @Override public boolean acceptsSuccess() { return true; }
    @Override public boolean acceptsFailure() { return true; }
    @Override public boolean shouldInformAdmins() { return false; }
    public void markResult(boolean ok) { success = ok; done = true; }
    public void fail(String err) { feedback.append("[ERROR] ").append(err).append("\n"); success = false; done = true; }

    public void flushTo(OutputStream out, MinecraftServer srv) {
        JsonObject response = new JsonObject();
        response.addProperty("seq", seq);
        response.addProperty("command", command);
        response.addProperty("result", feedback.toString().trim());
        response.addProperty("success", done && success);
        String json = new Gson().toJson(response);
        try { out.write((json + "\n").getBytes(StandardCharsets.UTF_8)); out.flush(); } catch (Exception ignored) { }
        Path result = BridgeIO.bridgeDir(srv).resolve("command_result.json");
        BridgeIO.write(result, json + System.lineSeparator());
    }
}
