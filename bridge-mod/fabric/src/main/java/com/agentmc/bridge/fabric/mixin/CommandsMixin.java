package com.agentmc.bridge.fabric.mixin;

import com.agentmc.bridge.AiChat;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import com.mojang.brigadier.CommandDispatcher;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * 在指令树构建时注册 /ai,保证它出现在指令补全里(运行时 register 会破坏补全)。
 * 免 fabric-api:直接往 Commands 构造时的 dispatcher 挂字面量。
 */
@Mixin(Commands.class)
public class CommandsMixin {

    @Shadow
    private CommandDispatcher<CommandSourceStack> dispatcher;

    @Inject(method = "<init>", at = @At("TAIL"))
    private void agentmc$registerAiCommand(CallbackInfo ci) {
        try {
            dispatcher.register(AiChat.command());
        } catch (Exception ignored) {
        }
    }
}
