package com.agentmc.bridge;

import com.google.common.collect.Multimap;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.core.Registry;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.ai.attributes.Attribute;
import net.minecraft.world.entity.ai.attributes.AttributeModifier;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import java.util.HashMap;
import java.util.Map;

/** 1.19.2 物品属性导出。 */
public final class ItemExporter {
    private ItemExporter() {}
    public static void export(MinecraftServer server) {
        JsonArray out = new JsonArray();
        for (Item item : Registry.ITEM) { ResourceLocation key = Registry.ITEM.getKey(item); if (key == null) continue; ItemStack stack = new ItemStack(item);
            JsonObject j = new JsonObject(); j.addProperty("id", key.toString()); j.addProperty("max_stack", stack.getMaxStackSize()); j.add("attributes", attributes(item));
            FoodProperties food = item.getFoodProperties(); if (food != null) { JsonObject f = new JsonObject(); f.addProperty("nutrition", food.getNutrition()); f.addProperty("saturation", food.getSaturationModifier()); j.add("food", f); }
            out.add(j); }
        BridgeIO.write(BridgeIO.bridgeDir(server).resolve("items.json"), new com.google.gson.GsonBuilder().setPrettyPrinting().create().toJson(out));
    }
    private static JsonObject attributes(Item item) {
        Map<String, Double> values = new HashMap<>();
        for (EquipmentSlot slot : EquipmentSlot.values()) for (Map.Entry<Attribute, AttributeModifier> e : item.getDefaultAttributeModifiers(slot).entries()) {
            Attribute a = e.getKey(); double v = e.getValue().getAmount();
            if (a == Attributes.ATTACK_DAMAGE) values.put("attack_damage", v); else if (a == Attributes.ATTACK_SPEED) values.put("attack_speed", v);
            else if (a == Attributes.ARMOR) values.put("armor", v); else if (a == Attributes.ARMOR_TOUGHNESS) values.put("armor_toughness", v);
            else if (a == Attributes.KNOCKBACK_RESISTANCE) values.put("knockback_resistance", v); else if (a == Attributes.MOVEMENT_SPEED) values.put("movement_speed", v);
        }
        JsonObject j = new JsonObject(); values.forEach(j::addProperty); return j;
    }
}
