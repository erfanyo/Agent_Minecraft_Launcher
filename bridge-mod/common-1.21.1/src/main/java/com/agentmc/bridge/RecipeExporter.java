package com.agentmc.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.core.RegistryAccess;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.Recipe;
import net.minecraft.world.item.crafting.RecipeManager;

import java.nio.file.Path;

/**
 * 配方导出:把 RecipeManager 的全部配方 dump 成 .bridge/recipes.json。
 * 数据源是游戏自己的配方表(JEI 也是读它),不依赖 JEI mod,更通用。
 *
 * 结构:[{id, type, output:{item,count}, ingredients:[{item,count}...]}]
 * 本文件按 MC 1.21.1 API 编写(getResultItem(RegistryAccess) / Ingredient#getItems / getRecipeIds)。
 */
public final class RecipeExporter {

    private RecipeExporter() {}

    public static void export(MinecraftServer server) {
        RegistryAccess access = server.registryAccess();
        RecipeManager manager = server.getRecipeManager();
        JsonArray out = new JsonArray();
        manager.getRecipeIds().forEach(id -> {
            // 1.21 起 byKey 返回 RecipeHolder<?>,配方本体在 value() 里
            manager.byKey(id).ifPresent(holder -> out.add(toJson(holder.value(), id, access)));
        });
        Path p = BridgeIO.bridgeDir(server).resolve("recipes.json");
        BridgeIO.write(p, new com.google.gson.GsonBuilder().setPrettyPrinting().create().toJson(out));
    }

    private static JsonObject toJson(Recipe<?> recipe, ResourceLocation id, RegistryAccess access) {
        JsonObject j = new JsonObject();
        j.addProperty("id", id.toString());
        j.addProperty("type", recipe.getType().toString());
        ItemStack result = recipe.getResultItem(access);
        JsonObject output = new JsonObject();
        output.addProperty("item", BuiltInRegistries.ITEM.getKey(result.getItem()).toString());
        output.addProperty("count", result.getCount());
        j.add("output", output);
        JsonArray ings = new JsonArray();
        for (Ingredient ing : recipe.getIngredients()) {
            JsonObject i = new JsonObject();
            ItemStack[] matches = ing.getItems();
            if (matches.length > 0) {
                i.addProperty("item", BuiltInRegistries.ITEM.getKey(matches[0].getItem()).toString());
                i.addProperty("count", matches[0].getCount());
            } else {
                i.addProperty("item", "(空/任意)");
                i.addProperty("count", 0);
            }
            ings.add(i);
        }
        j.add("ingredients", ings);
        return j;
    }
}
