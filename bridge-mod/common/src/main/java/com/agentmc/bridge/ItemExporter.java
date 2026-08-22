package com.agentmc.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.entity.ai.attributes.Attribute;
import net.minecraft.world.entity.ai.attributes.AttributeModifier;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.food.FoodProperties;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.component.ItemAttributeModifiers;

import java.nio.file.Path;

/**
 * 物品属性导出:遍历注册表,把每个物品的关键属性 dump 成 .bridge/items.json。
 *
 * 结构:[{id, max_stack, attributes:{attack_damage, armor, ...}, food, tags:[...]}]
 * 挖掘等级:按工具类标签(如 minecraft:wooden_tools / iron_tools)推断,启动器侧比较。
 * 适配 MC 1.21.1 API(2026-08 编译验证)。
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

            // 属性:默认装备槽位的属性修改器(攻击伤害/护甲等)
            ItemAttributeModifiers mods = item.getDefaultAttributeModifiers();
            j.add("attributes", attributeJson(mods));

            // 食物(1.20.5+ 走数据组件)
            FoodProperties food = stack.get(DataComponents.FOOD);
            if (food != null) {
                JsonObject fj = new JsonObject();
                fj.addProperty("nutrition", food.nutrition());
                fj.addProperty("saturation", food.saturation());
                j.add("food", fj);
            }

            // 标签(含工具等级推断用)
            JsonArray tags = new JsonArray();
            stack.getTags().forEach(t -> tags.add(t.location().toString()));
            j.add("tags", tags);

            out.add(j);
        }
        Path p = BridgeIO.bridgeDir(server).resolve("items.json");
        BridgeIO.write(p, new com.google.gson.GsonBuilder().setPrettyPrinting().create().toJson(out));
    }

    private static JsonObject attributeJson(ItemAttributeModifiers mods) {
        JsonObject j = new JsonObject();
        for (ItemAttributeModifiers.Entry e : mods.modifiers()) {
            Attribute attr = e.attribute().value();   // 1.21:Holder<Attribute>
            AttributeModifier m = e.modifier();
            double v = m.amount();
            if (attr == Attributes.ATTACK_DAMAGE) j.addProperty("attack_damage", v);
            else if (attr == Attributes.ATTACK_SPEED) j.addProperty("attack_speed", v);
            else if (attr == Attributes.ARMOR) j.addProperty("armor", v);
            else if (attr == Attributes.ARMOR_TOUGHNESS) j.addProperty("armor_toughness", v);
            else if (attr == Attributes.KNOCKBACK_RESISTANCE) j.addProperty("knockback_resistance", v);
            else if (attr == Attributes.MOVEMENT_SPEED) j.addProperty("movement_speed", v);
        }
        return j;
    }
}
