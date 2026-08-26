package com.agentmc.bridge.neoforge;

import com.agentmc.bridge.AiChat;
import com.agentmc.bridge.BridgeCore;
import com.agentmc.bridge.KeyBindingExporter;
import net.minecraft.client.Minecraft;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.fml.common.Mod;
import net.neoforged.fml.loading.FMLEnvironment;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.client.event.ScreenEvent;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.RegisterCommandsEvent;
import net.neoforged.neoforge.event.server.ServerStartedEvent;
import net.neoforged.neoforge.event.server.ServerStoppingEvent;

/**
 * NeoForge 入口:服务器生命周期(数据导出/指令口)+ 客户端按键导出。
 *
 * 注意(踩坑):
 * - ServerStartedEvent / ServerStoppingEvent / ClientTickEvent / ScreenEvent 都是
 *   game bus(NeoForge.EVENT_BUS)事件,不能注册到 mod bus(mod bus 只收 IModBusEvent)
 * - 客户端事件只在 Dist.CLIENT 注册,避免专用服务器 NoClassDefFoundError
 */
@Mod("agentmc_bridge")
public class BridgeNeoForge {

    private boolean keysExported = false;

    public BridgeNeoForge(IEventBus modBus) {
        var gameBus = NeoForge.EVENT_BUS;
        gameBus.addListener(this::onServerStarted);
        gameBus.addListener(this::onServerStopping);
        gameBus.addListener(this::onRegisterCommands);
        if (FMLEnvironment.dist == Dist.CLIENT) {
            gameBus.addListener(this::onClientTick);
            gameBus.addListener(this::onScreenClosed);
        }
    }

    private void onServerStarted(ServerStartedEvent event) {
        BridgeCore.onServerStarted(event.getServer());
    }

    private void onServerStopping(ServerStoppingEvent event) {
        BridgeCore.onServerStopped();
    }

    /** 注册 /ai 指令(与 fabric 的 CommandsMixin 等效,走 neoforge 事件) */
    private void onRegisterCommands(RegisterCommandsEvent event) {
        try {
            event.getDispatcher().register(AiChat.command());
        } catch (Exception ignored) {
        }
    }

    /** 客户端首帧:导出按键绑定(options 就绪后) */
    private void onClientTick(ClientTickEvent.Pre event) {
        if (!keysExported) {
            keysExported = true;
            Minecraft client = Minecraft.getInstance();
            if (client != null) {
                KeyBindingExporter.export(client);
            }
        }
    }

    /** 关闭任意屏幕(如键盘设置)后刷新按键导出,启动器重读即最新 */
    private void onScreenClosed(ScreenEvent.Closing event) {
        Minecraft client = Minecraft.getInstance();
        if (client != null) {
            KeyBindingExporter.export(client);
        }
    }
}
