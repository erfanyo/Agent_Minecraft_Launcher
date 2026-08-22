package com.agentmc.bridge.fabric;

import net.fabricmc.api.ModInitializer;

/**
 * Fabric 入口。服务器生命周期由 Mixin(MinecraftServerMixin)处理,
 * 无需 fabric-api 依赖——bridge-mod 单独一个 jar 即可运行。
 */
public class BridgeFabric implements ModInitializer {

    @Override
    public void onInitialize() {
        // Mixin 在 fabric.mod.json 的 mixins 字段声明,loader 自动注册
    }
}
