package com.agentmc.bridge.fabric.mixin;

import com.agentmc.bridge.BridgeCore;
import net.minecraft.server.MinecraftServer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * 用 Mixin 监听服务器生命周期(不依赖 fabric-api):
 * - 第一次 tickServer = 世界加载完成 → 导出数据 + 开本地指令口
 * - runServer 结束 = 服务器停止 → 清理
 */
@Mixin(MinecraftServer.class)
public class MinecraftServerMixin {

    @Unique
    private boolean agentmc$notified = false;

    @Inject(method = "tickServer", at = @At("HEAD"))
    private void agentmc$onServerReady(CallbackInfo ci) {
        if (!agentmc$notified) {
            agentmc$notified = true;
            BridgeCore.onServerStarted((MinecraftServer) (Object) this);
        }
    }

    @Inject(method = "runServer", at = @At("RETURN"))
    private void agentmc$onServerStopped(CallbackInfo ci) {
        BridgeCore.onServerStopped();
    }
}
