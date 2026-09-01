package com.agentmc.bridge.forge1182;

import com.agentmc.bridge.AiChat;
import com.agentmc.bridge.BridgeCore;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.RegisterCommandsEvent;
import net.minecraftforge.event.server.ServerStartedEvent;
import net.minecraftforge.event.server.ServerStoppingEvent;
import net.minecraftforge.fml.common.Mod;

@Mod("agentmc_bridge")
public final class BridgeForge1182 {
    public BridgeForge1182() {
        MinecraftForge.EVENT_BUS.addListener(this::onServerStarted);
        MinecraftForge.EVENT_BUS.addListener(this::onServerStopping);
        MinecraftForge.EVENT_BUS.addListener(this::onRegisterCommands);
    }
    private void onServerStarted(ServerStartedEvent event) { BridgeCore.onServerStarted(event.getServer()); }
    private void onServerStopping(ServerStoppingEvent event) { BridgeCore.onServerStopped(); }
    private void onRegisterCommands(RegisterCommandsEvent event) { event.getDispatcher().register(AiChat.command()); }
}
