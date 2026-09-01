package com.agentmc.bridge.forge1165;

import com.agentmc.bridge.AiChat;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.RegisterCommandsEvent;
import net.minecraftforge.fml.common.Mod;

@Mod("agentmc_bridge")
public final class BridgeForge1165 {
    public BridgeForge1165() { MinecraftForge.EVENT_BUS.addListener(this::commands); }
    private void commands(RegisterCommandsEvent event) { event.getDispatcher().register(AiChat.command()); }
}
