package com.agentmc.bridge;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.mojang.blaze3d.platform.InputConstants;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Options;
import net.minecraft.locale.Language;

import java.lang.reflect.Field;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/**
 * 按键绑定导出(客户端):把全部按键(含 mod 注册的)导出成 .bridge/keybindings.json。
 *
 * 结构(键码 -> 操作列表,天然支持一键多操作):
 * {
 *   "32": [{"name":"key.forward","category":"...","mod":"minecraft","display":"前进"}],
 *   "82": [{"name":"key.jei.recipe","category":"...","mod":"jei","display":"显示合成配方"}]
 * }
 * - display:用游戏翻译 API 渲染成当前语言(mod 自带 lang 的中文名自动生效)
 * - 玩家改键时(Options.save)与客户端首帧各导出一次,启动器重读即最新
 * - mod 归属按翻译键推断:key.&lt;modid&gt;.xxx → &lt;modid&gt;;原版 key.xxx → minecraft
 * - 原版 mojmap 没有 getKey(),按键在私有字段 key,用反射读取(字段名各版本稳定)
 */
public final class KeyBindingExporter {

    private KeyBindingExporter() {}

    public static void export(Minecraft client) {
        try {
            Options options = client.options;
            if (options == null) return;
            Language lang = Language.getInstance();
            Map<Integer, JsonArray> byKey = new HashMap<>();
            for (KeyMapping km : options.keyMappings) {
                if (km == null) continue;
                InputConstants.Key key = keyOf(km);
                if (key == null) continue;
                int code = key.getValue();
                JsonObject entry = new JsonObject();
                entry.addProperty("name", km.getName());
                entry.addProperty("category", km.getCategory());
                entry.addProperty("mod", guessMod(km.getName()));
                // 翻译 API:翻译键 → 当前语言文本(mod 的中文名自动覆盖)
                entry.addProperty("display", lang.getOrDefault(km.getName()));
                byKey.computeIfAbsent(code, k -> new JsonArray()).add(entry);
            }
            JsonObject root = new JsonObject();
            byKey.forEach((code, arr) -> root.add(String.valueOf(code), arr));
            Path p = BridgeIO.bridgeDirFrom(client.gameDirectory.toPath())
                    .resolve("keybindings.json");
            BridgeIO.write(p, new GsonBuilder().setPrettyPrinting().create().toJson(root));
            BridgeIO.log("keybindings exported: " + byKey.size() + " keys");
        } catch (Exception e) {
            BridgeIO.log("keybindings export failed: " + e);
        }
    }

    /** 反射读 KeyMapping 的 key 字段(原版 mojmap 无 getKey()) */
    private static InputConstants.Key keyOf(KeyMapping km) {
        try {
            Field f = KeyMapping.class.getDeclaredField("key");
            f.setAccessible(true);
            return (InputConstants.Key) f.get(km);
        } catch (Exception e) {
            return null;
        }
    }

    /** 按翻译键推断 mod:key.&lt;modid&gt;.xxx → &lt;modid&gt;;key.xxx → minecraft */
    private static String guessMod(String name) {
        if (name == null) return "minecraft";
        String[] parts = name.split("\\.");
        if (parts.length >= 3 && !parts[1].isEmpty()) {
            return parts[1];
        }
        return "minecraft";
    }
}
