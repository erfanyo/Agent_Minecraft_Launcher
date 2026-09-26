# Mod 中文名审阅记录

采集日期：2026-09-25。数据来自 [Modrinth API](https://docs.modrinth.com/api/) 的热门整合包搜索、项目版本，以及所选 `.mrpack` 的 `modrinth.index.json`。归档格式见 [Modrinth 说明](https://support.modrinth.com/en/articles/8802351-modrinth-modpack-format-mrpack)。

本轮按优化、科技、魔法、冒险、战斗、装饰、综合七个方向，取各方向按下载量排序的前三个整合包，合并重复项，并读取可用的最新正式版（没有正式版时读取最新可用版）。成功读取 15 个整合包，共识别 1157 个不同的 Modrinth Mod 项目。某些热门整合包没有可读取的 `.mrpack` 或索引结构异常，因此未计入统计。分类由 Modrinth 项目标签决定，不代表整合包只有一种玩法。

完整记录：

- `modpack_mod_inventory.json`：整合包、版本、每包使用的 Modrinth 项目 ID、项目 slug 和项目页。
- `modpack_mod_name_audit.csv`：逐 Mod 审阅表，按出现在多少个整合包中排序，包含英文名、已采用的中文名、状态和来源整合包；`unreviewed` 表示尚未确认中文译名，不能按英文名硬译。
- `collect_modpack_mods.mjs` 和 `modpack_name_audit.mjs`：重新采集及生成审阅表。重新采集会按当时的下载量和版本更新结果，数量可能变化。

本轮将 16 个已确认的中文译名补入 `mod_cn_ext.json`。以 MC 百科当前收录名称为准：

| Modrinth slug | 采用名称 | 核对来源 |
| --- | --- | --- |
| polymorph | 多态合成 | [MC 百科](https://www.mcmod.cn/class/2895.html) |
| better-advancements | 更好的进度 | [MC 百科](https://www.mcmod.cn/class/1530.html) |
| comforts | 舒适用品 | [MC 百科](https://www.mcmod.cn/class/2107.html) |
| natures-compass | 自然罗盘 | [MC 百科](https://www.mcmod.cn/class/category/23-98.html) |
| waystones | 传送石碑 | [MC 百科](https://www.mcmod.cn/class/diff/0-161937.html) |
| toms-storage | 汤姆的简易存储 | [MC 百科](https://www.mcmod.cn/class/history/2882.html) |
| betterend | 更好的末地 | [MC 百科](https://www.mcmod.cn/class/diff/0-70105.html) |
| deeperdarker | 幽邃黑暗 | [MC 百科](https://www.mcmod.cn/class/7369.html) |
| create-steam-n-rails | 机械动力：汽鸣铁道 | [MC 百科](https://www.mcmod.cn/class/8230.html) |
| createaddition | 机械动力：创想附加 | [MC 百科](https://www.mcmod.cn/class/3437.html) |
| every-compat | 泛用兼容：木材 | [MC 百科](https://www.mcmod.cn/class/7096.html) |
| travelersbackpack | 旅行者背包 | [MC 百科](https://www.mcmod.cn/class/category/23-192.html) |
| yungs-better-dungeons | YUNG 的地牢优化 | [MC 百科](https://www.mcmod.cn/class/4429.html) |
| yungs-better-mineshafts | YUNG 的矿井优化 | [MC 百科](https://www.mcmod.cn/class/2788.html) |
| yungs-better-strongholds | YUNG 的要塞优化 | [MC 百科](https://www.mcmod.cn/class/3787.html) |
| yungs-better-nether-fortresses | YUNG 的下界要塞优化 | [MC 百科](https://www.mcmod.cn/class/9384.html) |

英文原名或缩写有独立品牌辨识度、MC 百科没有稳定中文名的项目，暂时不写入中文名表。中文名表只影响搜索与展示，不代表版本或加载器兼容；兼容性仍以资源文件的声明为准。
