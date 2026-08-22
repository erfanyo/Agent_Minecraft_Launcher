package com.agentmc.bridge.forge;

import com.agentmc.bridge.BridgeCore;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.server.ServerStartedEvent;
import net.minecraftforge.event.server.ServerStoppingEvent;
import net.minecraftforge.fml.common.Mod;

/**
 * Forge 入口:注册服务器事件,转发给 BridgeCore。
 */
@Mod("agentmc_bridge")
public class BridgeForge {

    public BridgeForge() {
        MinecraftForge.EVENT_BUS.addListener(this::onServerStarted);
        MinecraftForge.EVENT_BUS.addListener(this::onServerStopping);
    }

    private void onServerStarted(ServerStartedEvent event) {
        BridgeCore.onServerStarted(event.getServer());
    }

    private void onServerStopping(ServerStoppingEvent event) {
        BridgeCore.onServerStopped();
    }
}
