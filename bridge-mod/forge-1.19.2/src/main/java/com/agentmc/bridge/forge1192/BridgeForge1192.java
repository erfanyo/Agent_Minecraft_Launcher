package com.agentmc.bridge.forge1192;

import com.agentmc.bridge.AiChat;
import com.agentmc.bridge.BridgeCore;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.RegisterCommandsEvent;
import net.minecraftforge.event.server.ServerStartedEvent;
import net.minecraftforge.event.server.ServerStoppingEvent;
import net.minecraftforge.fml.common.Mod;

/** Forge 1.19.2 平台入口。版本差异只留在本模块与兼容导出层。 */
@Mod("agentmc_bridge")
public final class BridgeForge1192 {
    public BridgeForge1192() {
        MinecraftForge.EVENT_BUS.addListener(this::onServerStarted);
        MinecraftForge.EVENT_BUS.addListener(this::onServerStopping);
        MinecraftForge.EVENT_BUS.addListener(this::onRegisterCommands);
    }

    private void onServerStarted(ServerStartedEvent event) {
        BridgeCore.onServerStarted(event.getServer());
    }

    private void onServerStopping(ServerStoppingEvent event) {
        BridgeCore.onServerStopped();
    }

    private void onRegisterCommands(RegisterCommandsEvent event) {
        event.getDispatcher().register(AiChat.command());
    }
}
