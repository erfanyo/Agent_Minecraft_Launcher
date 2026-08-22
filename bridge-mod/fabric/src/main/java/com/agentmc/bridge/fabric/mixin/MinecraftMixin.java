package com.agentmc.bridge.fabric.mixin;

import com.agentmc.bridge.KeyBindingExporter;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * 客户端首帧导出按键绑定(options 就绪后)。
 */
@Mixin(Minecraft.class)
public class MinecraftMixin {

    @Unique
    private boolean agentmc$keysExported = false;

    @Inject(method = "tick", at = @At("HEAD"))
    private void agentmc$exportKeysOnce(CallbackInfo ci) {
        if (!agentmc$keysExported) {
            agentmc$keysExported = true;
            KeyBindingExporter.export((Minecraft) (Object) this);
        }
    }
}
