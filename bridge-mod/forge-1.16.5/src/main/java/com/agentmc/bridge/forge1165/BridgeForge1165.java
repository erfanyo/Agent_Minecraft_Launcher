package com.agentmc.bridge.forge1165;

import com.agentmc.bridge.AiChat;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.RegisterCommandsEvent;
import net.minecraftforge.event.TickEvent;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.fml.server.ServerLifecycleHooks;

@Mod("agentmc_bridge")
public final class BridgeForge1165 {
    public BridgeForge1165() {
        MinecraftForge.EVENT_BUS.addListener(this::commands);
        MinecraftForge.EVENT_BUS.addListener(this::serverTick);
    }
    private void commands(RegisterCommandsEvent event) { event.getDispatcher().register(AiChat.command()); }
    private void serverTick(TickEvent.ServerTickEvent event) {
        if (event.phase == TickEvent.Phase.END) {
            net.minecraft.server.MinecraftServer server = ServerLifecycleHooks.getCurrentServer();
            if (server != null) com.agentmc.bridge.FileCommandBridge.poll(server);
        }
    }
}
