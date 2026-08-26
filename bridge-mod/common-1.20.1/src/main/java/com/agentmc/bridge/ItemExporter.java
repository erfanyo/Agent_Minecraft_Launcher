package com.agentmc.bridge;

import com.google.common.collect.Multimap;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.tags.TagKey;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.ai.attributes.Attribute;
import net.minecraft.world.entity.ai.attributes.AttributeModifier;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;

import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/**
 * 物品属性导出(MC 1.20.1 版):遍历注册表,把每个物品的关键属性 dump 成 .bridge/items.json。
 * 1.20.1 没有 1.20.5+ 的数据组件(DataComponents/ItemAttributeModifiers),
 * 用老的 getAttributeModifiers(EquipmentSlot) Multimap + getFoodProperties()。
 */
public final class ItemExporter {

    private ItemExporter() {}

    public static void export(MinecraftServer server) {
        JsonArray out = new JsonArray();
        for (Item item : BuiltInRegistries.ITEM) {
            ResourceLocation key = BuiltInRegistries.ITEM.getKey(item);
            if (key == null) continue;
            ItemStack stack = new ItemStack(item);
            JsonObject j = new JsonObject();
            j.addProperty("id", key.toString());
            j.addProperty("max_stack", stack.getMaxStackSize());

            // 属性:遍历装备槽位的属性修改器
            j.add("attributes", attributeJson(item));

            // 食物(1.20.1 用 getFoodProperties())
            FoodProperties food = item.getFoodProperties();
            if (food != null) {
                JsonObject fj = new JsonObject();
                fj.addProperty("nutrition", food.getNutrition());
                fj.addProperty("saturation", food.getSaturationModifier());
                j.add("food", fj);
            }

            // 标签(含工具等级推断用)
            JsonArray tags = new JsonArray();
            item.builtInRegistryHolder().tags().forEach(t -> tags.add(t.location().toString()));
            j.add("tags", tags);

            out.add(j);
        }
        Path p = BridgeIO.bridgeDir(server).resolve("items.json");
        BridgeIO.write(p, new com.google.gson.GsonBuilder().setPrettyPrinting().create().toJson(out));
    }

    private static JsonObject attributeJson(Item item) {
        Map<String, Double> m = new HashMap<>();
        for (EquipmentSlot slot : EquipmentSlot.values()) {
            Multimap<Attribute, AttributeModifier> mm = item.getDefaultAttributeModifiers(slot);
            for (Map.Entry<Attribute, AttributeModifier> e : mm.entries()) {
                Attribute attr = e.getKey();
                double v = e.getValue().getAmount();
                if (attr == Attributes.ATTACK_DAMAGE) m.put("attack_damage", v);
                else if (attr == Attributes.ATTACK_SPEED) m.put("attack_speed", v);
                else if (attr == Attributes.ARMOR) m.put("armor", v);
                else if (attr == Attributes.ARMOR_TOUGHNESS) m.put("armor_toughness", v);
                else if (attr == Attributes.KNOCKBACK_RESISTANCE) m.put("knockback_resistance", v);
                else if (attr == Attributes.MOVEMENT_SPEED) m.put("movement_speed", v);
            }
        }
        JsonObject j = new JsonObject();
        for (Map.Entry<String, Double> e : m.entrySet()) j.addProperty(e.getKey(), e.getValue());
        return j;
    }
}
