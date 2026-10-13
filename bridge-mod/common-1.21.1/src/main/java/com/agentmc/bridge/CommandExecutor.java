package com.agentmc.bridge;

import net.minecraft.commands.CommandSourceStack;
import net.minecraft.server.MinecraftServer;

/** Capture the actual Minecraft command callback, including denied commands. */
public final class CommandExecutor {
    private CommandExecutor() {}

    public static void execute(MinecraftServer server, CommandSourceStack source,
                               String command, CommandBridgeSource sink) {
        server.getCommands().performPrefixedCommand(
                source.withCallback((success, result) -> sink.markResult(success)), command);
    }
}
