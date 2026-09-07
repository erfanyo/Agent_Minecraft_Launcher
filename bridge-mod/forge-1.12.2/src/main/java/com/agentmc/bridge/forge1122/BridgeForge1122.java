package com.agentmc.bridge.forge1122;

import com.agentmc.bridge.AiChatCommand;
import com.agentmc.bridge.FileCommandBridge;
import net.minecraft.server.MinecraftServer;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.event.ServerChatEvent;
import net.minecraftforge.fml.common.FMLCommonHandler;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.fml.common.event.FMLServerStartingEvent;
import net.minecraftforge.fml.common.eventhandler.SubscribeEvent;
import net.minecraftforge.fml.common.gameevent.TickEvent;

@Mod(modid = "agentmc_bridge", name = "AgentMC Bridge", version = "@VERSION@", acceptableRemoteVersions = "*")
public final class BridgeForge1122 {
    public BridgeForge1122() { MinecraftForge.EVENT_BUS.register(this); }

    @Mod.EventHandler public void onServerStarting(FMLServerStartingEvent event) {
        event.registerServerCommand(new AiChatCommand());
    }

    @SubscribeEvent public void onServerTick(TickEvent.ServerTickEvent event) {
        if (event.phase != TickEvent.Phase.END) return;
        MinecraftServer server = FMLCommonHandler.instance().getMinecraftServerInstance();
        if (server != null) FileCommandBridge.poll(server);
    }
}
