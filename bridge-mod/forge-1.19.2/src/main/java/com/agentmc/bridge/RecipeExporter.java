package com.agentmc.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.core.Registry;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.Recipe;
import net.minecraft.world.item.crafting.RecipeManager;

/** 1.19.2 配方导出：该版 getResultItem 不需要 RegistryAccess。 */
public final class RecipeExporter {
    private RecipeExporter() {}
    public static void export(MinecraftServer server) {
        RecipeManager manager = server.getRecipeManager(); JsonArray out = new JsonArray();
        manager.getRecipeIds().forEach(id -> manager.byKey(id).ifPresent(recipe -> out.add(toJson(recipe, id))));
        BridgeIO.write(BridgeIO.bridgeDir(server).resolve("recipes.json"), new com.google.gson.GsonBuilder().setPrettyPrinting().create().toJson(out));
    }
    private static JsonObject toJson(Recipe<?> recipe, ResourceLocation id) {
        JsonObject j = new JsonObject(); j.addProperty("id", id.toString()); j.addProperty("type", recipe.getType().toString());
        ItemStack result = recipe.getResultItem(); JsonObject output = new JsonObject();
        output.addProperty("item", Registry.ITEM.getKey(result.getItem()).toString()); output.addProperty("count", result.getCount()); j.add("output", output);
        JsonArray ingredients = new JsonArray();
        for (Ingredient ingredient : recipe.getIngredients()) { JsonObject i = new JsonObject(); ItemStack[] matches = ingredient.getItems();
            if (matches.length > 0) { i.addProperty("item", Registry.ITEM.getKey(matches[0].getItem()).toString()); i.addProperty("count", matches[0].getCount()); }
            else { i.addProperty("item", "(空/任意)"); i.addProperty("count", 0); } ingredients.add(i); }
        j.add("ingredients", ingredients); return j;
    }
}
