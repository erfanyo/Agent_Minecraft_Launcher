package com.agentmc.bridge;

import net.minecraft.commands.CommandSourceStack;
import net.minecraft.server.MinecraftServer;

/** Brigadier callback signature used by Minecraft 1.19.2 / 1.20.1. */
public final class CommandExecutor {
    private CommandExecutor() {}

    public static void execute(MinecraftServer server, CommandSourceStack source,
                               String command, CommandBridgeSource sink) {
        server.getCommands().performPrefixedCommand(
                source.withCallback((context, success, result) -> sink.markResult(success)), command);
    }
}
