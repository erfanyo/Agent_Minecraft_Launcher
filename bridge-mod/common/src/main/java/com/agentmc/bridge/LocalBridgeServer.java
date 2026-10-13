package com.agentmc.bridge;

import net.minecraft.server.MinecraftServer;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.server.level.ServerPlayer;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.UUID;

/**
 * 本地指令口(主通道,替代/补充 RCON):
 * - TCP 监听 127.0.0.1:26100(仅本机)
 * - 启动时把 token 写到 .bridge/token.txt,启动器读它做简单鉴权
 * - 收到 JSON:{"seq":1,"command":"weather rain","token":"..."}
 * - 在服务器线程执行命令,CommandSource 捕获反馈,回写 JSON:
 *   {"seq":1,"result":"Set the weather...","success":true}
 *   同时落盘 .bridge/command_result.json(启动器可读最新一条)
 *
 * 执行命令用 Commands.performPrefixedCommand(source, cmd) 并包一层
 * CommandBridgeSource 捕获 sendSuccess/sendFailure 的输出。
 *
 * 【可选:以玩家身份执行】请求可带 "as_player":"<玩家名或UUID>",
 * 命中在线玩家时用该玩家身份构建 CommandSourceStack(位置/权限/@p 目标按玩家),
 * 缺省仍为服务端控制台身份(权限 level 2)。玩家不在线则回退控制台并注记。
 */
public class LocalBridgeServer {

    private static final int PORT = 26100;

    private final MinecraftServer server;
    private final String token;
    private ServerSocket socket;
    private volatile boolean running = false;
    private Thread acceptThread;

    public LocalBridgeServer(MinecraftServer server) {
        this.server = server;
        this.token = UUID.randomUUID().toString().replace("-", "");
        BridgeIO.write(BridgeIO.bridgeDir(server).resolve("token.txt"), token);
    }

    public void start() {
        try {
            // 明确绑定 IPv4 127.0.0.1:getLoopbackAddress() 在部分机器返回 ::1(IPv6),
            // 启动器连 127.0.0.1 会 ConnectionRefused
            socket = new ServerSocket(PORT, 8, java.net.InetAddress.getByName("127.0.0.1"));
        } catch (IOException e) {
            BridgeIO.log("bridge port busy: " + e);
            return;
        }
        running = true;
        acceptThread = new Thread(this::acceptLoop, "bridge-accept");
        acceptThread.setDaemon(true);
        acceptThread.start();
        BridgeIO.log("bridge listening on 127.0.0.1:" + PORT
                + " (localPort=" + socket.getLocalPort() + ")");
    }

    public void stop() {
        running = false;
        BridgeIO.log("bridge stopped");
        try {
            if (socket != null) socket.close();
        } catch (IOException ignored) {
        }
    }

    private void acceptLoop() {
        while (running) {
            try {
                Socket client = socket.accept();
                BridgeIO.log("bridge got connection from " + client.getRemoteSocketAddress());
                handle(client);
            } catch (IOException e) {
                if (running) BridgeIO.log("accept error: " + e);
            }
        }
    }

    private void handle(Socket client) {
        OutputStream out = null;
        try {
            BufferedReader in = new BufferedReader(
                    new InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8));
            out = client.getOutputStream();
            String line = in.readLine();
            if (line == null || line.isBlank()) {
                closeQuietly(client);
                return;
            }
            JsonObject req;
            try {
                req = new Gson().fromJson(line, JsonObject.class);
            } catch (Exception e) {
                closeQuietly(client);
                return;
            }
            if (req == null) {
                closeQuietly(client);
                return;
            }
            if (!token.equals(req.get("token").getAsString())) {
                out.write("{\"error\":\"bad token\"}\n".getBytes(StandardCharsets.UTF_8));
                out.flush();
                closeQuietly(client);
                return;
            }
            String command = req.has("command") ? req.get("command").getAsString() : "";
            long seq = req.has("seq") ? req.get("seq").getAsLong() : 0L;
            String asPlayer = req.has("as_player") ? req.get("as_player").getAsString() : "";
            BridgeIO.log("bridge got command: " + command
                    + (asPlayer.isEmpty() ? "" : " (as_player=" + asPlayer + ")"));
            if (command.isBlank()) {
                closeQuietly(client);
                return;
            }

            final OutputStream replyOut = out;
            CommandBridgeSource sink = new CommandBridgeSource(seq, command, server);
            // 服务器线程执行命令(execute 在主线程跑,避免并发问题)。
            // ⚠ 坑:不能在这里用 try-with-resources 关 client —— 命令是异步排队的,
            // handle 一旦返回连接就被关,结果永远写不回去,启动器只能收到空响应
            // (表现就是"说发了指令,但游戏没执行/没反馈")。改由任务自己写完再关。
            server.execute(() -> {
                try {
                    // 默认:服务端控制台身份(权限 level 2,能用 /op 等高级指令)
                    CommandSourceStack source = server.createCommandSourceStack();
                    // 可选:以在线玩家身份执行(位置/权限/@p 按玩家)
                    if (!asPlayer.isEmpty()) {
                        ServerPlayer p = findPlayer(asPlayer);
                        if (p == null) {
                            sink.fail("as_player 指定的玩家不在线: " + asPlayer);
                            return;
                        }
                        source = p.createCommandSourceStack();
                    }
                    source = source.withSource(sink);
                    CommandExecutor.execute(server, source, command, sink);
                    // 执行回调判定成功；正常返回不代表通过语法或权限检查。
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
        try {
            if (socket != null) socket.close();
        } catch (IOException ignored) {
        }
    }

    /** 按玩家名(在线)或 UUID 查 ServerPlayer;查不到返回 null。 */
    private ServerPlayer findPlayer(String nameOrUuid) {
        if (nameOrUuid == null || nameOrUuid.isBlank()) return null;
        try {
            var playerList = server.getPlayerList();
            // 先试名字
            ServerPlayer byName = playerList.getPlayerByName(nameOrUuid);
            if (byName != null) return byName;
            // 再试 UUID
            try {
                UUID uuid = UUID.fromString(nameOrUuid);
                return playerList.getPlayer(uuid);
            } catch (Exception ignored) { }
            // 大小写/别名兜底:在线玩家里找名字忽略大小写匹配
            for (ServerPlayer p : playerList.getPlayers()) {
                if (p.getGameProfile().getName().equalsIgnoreCase(nameOrUuid)) return p;
            }
        } catch (Exception ignored) {
        }
        return null;
    }
}
