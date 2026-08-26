package com.agentmc.bridge.forge;

import com.agentmc.bridge.AiChat;
import com.agentmc.bridge.BridgeCore;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.RegisterCommandsEvent;
import net.minecraftforge.event.server.ServerStartedEvent;
import net.minecraftforge.event.server.ServerStoppingEvent;
import net.minecraftforge.fml.common.Mod;

/**
 * Forge 入口:注册服务器事件(转发给 BridgeCore)+ /ai 指令。
 * 适配 MC 1.20.1(经典 Forge API:net.minecraftforge.*)。
 */
@Mod("agentmc_bridge")
public class BridgeForge {

    public BridgeForge() {
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

    /** 注册 /ai 指令(与 fabric 的 CommandsMixin 等效,走 Forge 事件) */
    private void onRegisterCommands(RegisterCommandsEvent event) {
        try {
            event.getDispatcher().register(AiChat.command());
        } catch (Exception ignored) {
        }
    }
}
