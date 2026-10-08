package com.agentmc.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.entity.ai.attributes.Attribute;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.component.ItemAttributeModifiers;

import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/**
 * 物品属性导出(MC 1.21.1 版):遍历注册表,把每个物品的关键属性 dump 成 .bridge/items.json。
 *
 * 1.20.5+ 起物品属性/食物改成数据组件:
 * - 老的 item.getDefaultAttributeModifiers(slot) → DataComponents.ATTRIBUTE_MODIFIERS
 * - 老的 item.getFoodProperties()               → DataComponents.FOOD
 * - AttributeModifier 变成 record(用 amount() 而不是 getAmount())
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

            j.add("attributes", attributeJson(stack));

            FoodProperties food = stack.get(DataComponents.FOOD);
            if (food != null) {
                JsonObject fj = new JsonObject();
                fj.addProperty("nutrition", food.nutrition());
                fj.addProperty("saturation", food.saturation());
                j.add("food", fj);
            }

            JsonArray tags = new JsonArray();
            item.builtInRegistryHolder().tags().forEach(t -> tags.add(t.location().toString()));
            j.add("tags", tags);

            out.add(j);
        }
        Path p = BridgeIO.bridgeDir(server).resolve("items.json");
        BridgeIO.write(p, new com.google.gson.GsonBuilder().setPrettyPrinting().create().toJson(out));
    }

    /** 从 1.21 的属性数据组件里取出比较常用的几项(取第一个槽位的值) */
    private static JsonObject attributeJson(ItemStack stack) {
        Map<String, Double> m = new HashMap<>();
        ItemAttributeModifiers mods = stack.get(DataComponents.ATTRIBUTE_MODIFIERS);
        if (mods != null) {
            for (ItemAttributeModifiers.Entry e : mods.modifiers()) {
                Attribute attr = e.attribute().value();
                double v = e.modifier().amount();
                if (attr == Attributes.ATTACK_DAMAGE.value()) m.putIfAbsent("attack_damage", v);
                else if (attr == Attributes.ATTACK_SPEED.value()) m.putIfAbsent("attack_speed", v);
                else if (attr == Attributes.ARMOR.value()) m.putIfAbsent("armor", v);
                else if (attr == Attributes.ARMOR_TOUGHNESS.value()) m.putIfAbsent("armor_toughness", v);
                else if (attr == Attributes.KNOCKBACK_RESISTANCE.value()) m.putIfAbsent("knockback_resistance", v);
                else if (attr == Attributes.MOVEMENT_SPEED.value()) m.putIfAbsent("movement_speed", v);
            }
        }
        JsonObject j = new JsonObject();
        for (Map.Entry<String, Double> e : m.entrySet()) j.addProperty(e.getKey(), e.getValue());
        return j;
    }
}
