package com.agentmc.bridge;

import net.minecraft.commands.CommandSource;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.phys.Vec2;
import net.minecraft.world.phys.Vec3;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;

/**
 * 命令结果捕获器:实现 CommandSource,把 sendSuccess/sendFailure 的文本攒起来,
 * 执行结束后回写 TCP + 落盘 .bridge/command_result.json。
 */
public class CommandBridgeSource implements CommandSource {

    private final long seq;
    private final String command;
    private final MinecraftServer server;
    private final StringBuilder feedback = new StringBuilder();
    private volatile boolean done = false;
    private volatile boolean success = false;

    public CommandBridgeSource(long seq, String command, MinecraftServer server) {
        this.seq = seq;
        this.command = command;
        this.server = server;
    }

    @Override
    public void sendSystemMessage(Component message) {
        feedback.append(message.getString()).append("\n");
    }

    @Override
    public boolean acceptsSuccess() {
        return true;
    }

    @Override
    public boolean acceptsFailure() {
        return true;
    }

    @Override
    public boolean shouldInformAdmins() {
        return false;
    }

    public void markResult(boolean ok) {
        this.success = ok;
        this.done = true;
    }

    public void fail(String err) {
        feedback.append("[ERROR] ").append(err).append("\n");
        this.success = false;
        this.done = true;
    }

    /** 把结果写回 socket 与磁盘(由服务器线程调用) */
    public void flushTo(OutputStream out, MinecraftServer srv) {
        JsonObject resp = new JsonObject();
        resp.addProperty("seq", seq);
        resp.addProperty("command", command);
        resp.addProperty("result", feedback.toString().trim());
        resp.addProperty("success", done && success);
        String json = new Gson().toJson(resp);
        try {
            out.write((json + "\n").getBytes(StandardCharsets.UTF_8));
            out.flush();
        } catch (Exception ignored) {
        }
        Path p = BridgeIO.bridgeDir(srv).resolve("command_result.json");
        BridgeIO.write(p, json + System.lineSeparator());
    }
}
