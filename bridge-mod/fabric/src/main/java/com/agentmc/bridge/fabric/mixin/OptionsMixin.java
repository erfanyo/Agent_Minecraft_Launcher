package com.agentmc.bridge.fabric.mixin;

import com.agentmc.bridge.KeyBindingExporter;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Options;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * 玩家保存设置/改键后(Options.save)刷新按键导出,启动器重读即最新。
 */
@Mixin(Options.class)
public class OptionsMixin {

    @Inject(method = "save", at = @At("RETURN"))
    private void agentmc$refreshKeyBindings(CallbackInfo ci) {
        Minecraft client = Minecraft.getInstance();
        if (client != null) {
            KeyBindingExporter.export(client);
        }
    }
}
