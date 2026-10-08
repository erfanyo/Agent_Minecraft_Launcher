# 本地模型基准测试报告

共 7 个模型。维度:工具选择准确率 / 参数填充 / 瞎编率 / 速度(tok/s) / 加载(s)。

## 模型 × 维度对照

| 模型 | 参数 | 单步工具 | 单步参数 | 模糊理解 | **多步规划** | 瞎编率 | tok/s |
|---|---|---|---|---|---|---|---|
| Bonsai 2 27B (PTQ1_0) | 27B | 96% | 70% | 80% | **83%** | 0% | 35 |
| Qwen3.5 9B | 9B | 90% | 54% | 67% | **58%** | 10% | 58 |
| Qwen3.5 4B | 4B | 88% | 48% | 67% | **42%** | 10% | 86 |
| MiMo-V2.6 Distill Qwen 9B | 9B | 65% | 43% | 40% | **33%** | 10% | 60 |
| Qwen3.5 0.8B | 0.8B | 69% | 42% | 13% | **33%** | 4% | 161 |
| Qwen3.5 2B | 2B | 67% | 54% | 20% | **33%** | 4% | 127 |
| Qwen3.5 0.8B (xLAM function-calling) | 0.8B | 63% | 44% | - | **0%** | 4% | 171 |

## 按分类明细(工具选择准确率)

| 分类 | Bonsai 2 27B | MiMo-V2.6 Di | Qwen3.5 0.8B | Qwen3.5 0.8B | Qwen3.5 2B | Qwen3.5 4B | Qwen3.5 9B |
|---|---|---|---|---|---|---|---|
| **inst** | 100% | 100% | 80% | 60% | 80% | 100% | 100% |
| **mod** | 100% | 100% | 71% | 86% | 71% | 86% | 86% |
| **inspect** | 100% | 100% | 100% | 0% | 0% | 100% | 100% |
| **log** | 100% | 40% | 40% | 60% | 80% | 80% | 80% |
| **cfg** | 100% | 50% | 50% | 50% | 25% | 75% | 100% |
| **new** | 100% | 0% | 100% | 50% | 50% | 100% | 100% |
| **cmd** | 100% | 67% | 33% | 67% | 100% | 100% | 100% |
| **key** | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| **rcp** | 100% | 0% | 67% | 100% | 100% | 67% | 100% |
| **cmp** | 50% | 0% | 50% | 50% | 100% | 50% | 50% |
| **snap** | 100% | 100% | 100% | 100% | 75% | 100% | 100% |
| **compat** | 100% | 67% | 33% | 100% | 33% | 100% | 100% |
| **core** | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| **pack** | 50% | 50% | 50% | 0% | 0% | 100% | 100% |
| **server** | 100% | 83% | 67% | 83% | 83% | 100% | 100% |
| **ask** | 100% | 0% | 0% | 0% | 0% | 50% | 0% |

## 错误明细(仅列工具选错的)

**Bonsai 2 27B (PTQ1_0)**(2 条选错):
- `cmp_01`:想用 `a`,实际 `ask_user` (参数 0%)
- `pack_02`:想用 `s`,实际 `search_modpacks` (参数 0%)

**MiMo-V2.6 Distill Qwen 9B**(18 条选错):
- `log_03`:想用 `i`,实际 `list_instances` (参数 0%)
- `log_04`:想用 `q`,实际 `resolve_mod_concept` (参数 0%)
- `log_05`:想用 `i`,实际 `` (参数 0%)
- `cfg_03`:想用 `k`,实际 `` (参数 0%)
- `cfg_04`:想用 `k`,实际 `ask_user` (参数 0%)
- `new_01`:想用 `v`,实际 `` (参数 0%)
- `new_02`:想用 `v`,实际 `search_modpacks` (参数 0%)
- `cmd_02`:想用 `c`,实际 `` (参数 0%)
- `rcp_01`:想用 `i`,实际 `resolve_mod_concept` (参数 0%)
- `rcp_02`:想用 `i`,实际 `resolve_mod_concept` (参数 0%)
- `rcp_03`:想用 `i`,实际 `resolve_mod_concept` (参数 0%)
- `cmp_01`:想用 `a`,实际 `resolve_mod_concept` (参数 0%)
- `cmp_02`:想用 `a`,实际 `resolve_mod_concept` (参数 0%)
- `compat_01`:想用 `i`,实际 `list_mods` (参数 50%)
- `pack_02`:想用 `s`,实际 `` (参数 0%)
- `srv_04`:想用 `s`,实际 `list_server_mods` (参数 0%, 瞎编)
- `ask_01`:想用 `q`,实际 `list_instances` (参数 0%)
- `ask_02`:想用 `q`,实际 `list_instances` (参数 0%)

**Qwen3.5 0.8B (xLAM function-calling)**(19 条选错):
- `inst_03`:想用 `无`,实际 `get_key_bindings` (参数 100%)
- `log_03`:想用 `i`,实际 `inspect_instance_core` (参数 100%)
- `log_04`:想用 `q`,实际 `` (参数 0%)
- `log_05`:想用 `i`,实际 `inspect_instance_core` (参数 100%)
- `cfg_02`:想用 `无`,实际 `get_username` (参数 100%)
- `cfg_04`:想用 `k`,实际 `resolve_mc_name` (参数 0%)
- `inst_mod_01`:想用 `i`,实际 `install_instance` (参数 50%)
- `inst_mod_02`:想用 `i`,实际 `install_instance` (参数 50%)
- `cmd_01`:想用 `i`,实际 `set_mod_enabled` (参数 0%)
- `cmd_02`:想用 `c`,实际 `set_setting` (参数 0%)
- `rcp_01`:想用 `i`,实际 `ultimate_sense` (参数 0%)
- `cmp_01`:想用 `a`,实际 `get_item_info` (参数 0%)
- `compat_01`:想用 `i`,实际 `replace_mod_version` (参数 50%)
- `compat_02`:想用 `i`,实际 `replace_mod_version` (参数 0%)
- `pack_02`:想用 `s`,实际 `install_instance` (参数 0%, 瞎编)
- `srv_02`:想用 `s`,实际 `list_mods` (参数 0%, 瞎编)
- `srv_04`:想用 `s`,实际 `list_server_mods` (参数 100%)
- `ask_01`:想用 `q`,实际 `suggest_mods` (参数 0%)
- `ask_02`:想用 `q`,实际 `list_mods` (参数 0%)

**Qwen3.5 0.8B**(16 条选错):
- `inst_03`:想用 `无`,实际 `list_mods` (参数 100%)
- `mod_05`:想用 `i`,实际 `inspect_instance_core` (参数 50%)
- `mod_06`:想用 `i`,实际 `replace_mod_version` (参数 33%)
- `log_03`:想用 `i`,实际 `read_server_log` (参数 0%)
- `log_04`:想用 `q`,实际 `list_mods` (参数 0%)
- `cfg_02`:想用 `无`,实际 `resolve_mod_concept` (参数 100%)
- `cfg_04`:想用 `k`,实际 `resolve_mod_concept` (参数 0%)
- `new_02`:想用 `v`,实际 `list_instances` (参数 0%)
- `new_03`:想用 `i`,实际 `install_instance` (参数 100%)
- `cmd_02`:想用 `c`,实际 `set_setting` (参数 0%)
- `cmp_01`:想用 `a`,实际 `get_command_guide` (参数 0%)
- `pack_01`:想用 `q`,实际 `search_mods` (参数 100%)
- `pack_02`:想用 `s`,实际 `search_modpacks` (参数 0%)
- `srv_04`:想用 `s`,实际 `list_server_mods` (参数 0%, 瞎编)
- `ask_01`:想用 `q`,实际 `find_compatible_mod_replacement` (参数 0%)
- `ask_02`:想用 `q`,实际 `list_mods` (参数 0%)

**Qwen3.5 2B**(17 条选错):
- `inst_03`:想用 `无`,实际 `inspect_instance_core` (参数 100%)
- `mod_02`:想用 `q`,实际 `search_modpacks` (参数 100%)
- `mod_05`:想用 `i`,实际 `inspect_instance_core` (参数 50%)
- `log_04`:想用 `q`,实际 `get_recipe_path` (参数 0%)
- `cfg_02`:想用 `无`,实际 `get_key_bindings` (参数 100%)
- `cfg_03`:想用 `k`,实际 `get_settings` (参数 0%)
- `cfg_04`:想用 `k`,实际 `get_key_bindings` (参数 50%)
- `new_02`:想用 `v`,实际 `search_modpacks` (参数 0%)
- `inst_mod_02`:想用 `i`,实际 `` (参数 0%)
- `snap_01`:想用 `i`,实际 `list_instance_snapshots` (参数 100%)
- `compat_01`:想用 `i`,实际 `find_compatible_mod_replacement` (参数 50%)
- `compat_03`:想用 `i`,实际 `find_compatible_mod_replacement` (参数 0%)
- `pack_01`:想用 `q`,实际 `search_mods` (参数 100%)
- `pack_02`:想用 `s`,实际 `search_modpacks` (参数 0%)
- `srv_04`:想用 `s`,实际 `get_settings` (参数 0%)
- `ask_01`:想用 `q`,实际 `suggest_mods` (参数 0%)
- `ask_02`:想用 `q`,实际 `get_settings` (参数 0%)

**Qwen3.5 4B**(6 条选错):
- `mod_01`:想用 `q`,实际 `resolve_mod_concept` (参数 0%)
- `log_04`:想用 `q`,实际 `resolve_mod_concept` (参数 0%)
- `cfg_02`:想用 `无`,实际 `resolve_mc_name` (参数 100%)
- `rcp_02`:想用 `i`,实际 `resolve_mod_concept` (参数 0%)
- `cmp_01`:想用 `a`,实际 `get_recipe_path` (参数 0%)
- `ask_01`:想用 `q`,实际 `search_mods` (参数 0%)

**Qwen3.5 9B**(5 条选错):
- `log_04`:想用 `q`,实际 `get_recipe_path` (参数 0%)
- `inst_mod_01`:想用 `i`,实际 `search_mods` (参数 50%)
- `cmp_01`:想用 `a`,实际 `` (参数 0%)
- `ask_01`:想用 `q`,实际 `search_mods` (参数 0%)
- `ask_02`:想用 `q`,实际 `get_command_guide` (参数 0%)

## 多步决策链(供面试,按 rubric.md 打 A/B/C/D)

### ms_voxy · 给 neoforge-21.1.248 装 voxy
*voxy 缺失→看后续处理(换同类/跨平台/叫用户放弃)  期望:给出替代方案(distant horizons)或问用户,而非硬装/瞎编*

**Bonsai 2 27B (PTQ1_0)** [方向命中 2/2 步]
- 步1: ✓ `install_mod` {"instance_id": "neoforge-21.1.248", "mod_name": "voxy"}
- 步2: ✓ `search_mods` {"query": "voxy", "instance_id": "neoforge-21.1.248"}
  - 面试评级:___  备注:___
**MiMo-V2.6 Distill Qwen 9B** [方向命中 0/2 步]
- 步1: ✗ `` {}
- 步2: ✗ `` {}
  - 面试评级:___  备注:___
**Qwen3.5 0.8B** [方向命中 2/2 步]
- 步1: ✓ `install_mod` {"mod": "voxy", "version": "1.0.0"}
- 步2: ✓ `find_compatible_mod_replacement` {"mod": "voxy", "version": "1.0.0"}
  - 面试评级:___  备注:___
**Qwen3.5 2B** [方向命中 2/2 步]
- 步1: ✓ `install_mod` {"mod": "voxy", "version": "latest"}
- 步2: ✓ `find_compatible_mod_replacement` {"mod": "voxy", "version": "latest"}
  - 面试评级:___  备注:___
**Qwen3.5 4B** [方向命中 1/2 步]
- 步1: ✓ `install_mod` {"instance_id": "neoforge-21.1.248", "mod_id": "voxy"}
- 步2: ✗ `resolve_mod_concept` {"mod_name": "voxy"}
  - 面试评级:___  备注:___
**Qwen3.5 9B** [方向命中 2/2 步]
- 步1: ✓ `install_mod` {"instance_id": "neoforge-21.1.248", "mod_id": "voxy"}
- 步2: ✓ `search_mods` {"query": "voxy"}
  - 面试评级:___  备注:___

### ms_restore · 把 neoforge-21.1.248 恢复到昨天的状态
*多步:需先查后做  期望:先查快照再恢复,不编造 snapshot_id*

**Bonsai 2 27B (PTQ1_0)** [方向命中 2/2 步]
- 步1: ✓ `list_instance_snapshots` {"instance_id": "neoforge-21.1.248"}
- 步2: ✓ `restore_instance_snapshot` {"instance_id": "neoforge-21.1.248", "snapshot_id": "snap-20260101"}
  - 面试评级:___  备注:___
**MiMo-V2.6 Distill Qwen 9B** [方向命中 2/2 步]
- 步1: ✓ `list_instance_snapshots` {"instance_id": "neoforge-21.1.248"}
- 步2: ✓ `restore_instance_snapshot` {"instance_id": "neoforge-21.1.248", "snapshot_id": "snap-20260101"}
  - 面试评级:___  备注:___
**Qwen3.5 0.8B** [方向命中 1/2 步]
- 步1: ✗ `restore_instance_snapshot` {"instance_id": "neoforge-21.1.248"}
- 步2: ✓ `restore_instance_snapshot` {"instance_id": "neoforge-21.1.248"}
  - 面试评级:___  备注:___
**Qwen3.5 2B** [方向命中 1/2 步]
- 步1: ✗ `restore_instance_snapshot` {"instance": "neoforge-21.1.248", "snapshot": "yesterday"}
- 步2: ✓ `restore_instance_snapshot` {"instance": "neoforge-21.1.248", "snapshot": "snap-20260101"}
  - 面试评级:___  备注:___
**Qwen3.5 4B** [方向命中 1/2 步]
- 步1: ✗ `restore_instance_snapshot` {"instance_id": "neoforge-21.1.248", "snapshot_id": "yesterday"}
- 步2: ✓ `restore_instance_snapshot` {"instance_id": "neoforge-21.1.248", "snapshot_id": "snap-20260101"}
  - 面试评级:___  备注:___
**Qwen3.5 9B** [方向命中 1/2 步]
- 步1: ✗ `restore_instance_snapshot` {"instance_id": "neoforge-21.1.248", "snapshot_time": "yesterday"}
- 步2: ✓ `restore_instance_snapshot` {"instance_id": "neoforge-21.1.248", "snapshot_time": "snap-20260101"}
  - 面试评级:___  备注:___

### ms_bycraft · 帮我找个能自动熔炉的东西
*按功能找 mod(多步:解析→选择→安装)  期望:模糊需求→解析概念→用户选→装,不瞎猜 slug*

**Bonsai 2 27B (PTQ1_0)** [方向命中 1/2 步]
- 步1: ✓ `search_mods` {"query": "auto furnace"}
- 步2: ✗ `ask_user` {"question": "你想用哪个模组实现自动熔炉？候选：create（机械动力）、mekanism（通用机械）、thermal（热力）。请回复名称或序号。"}
  - 面试评级:___  备注:___
**MiMo-V2.6 Distill Qwen 9B** [方向命中 1/2 步]
- 步1: ✓ `resolve_mod_concept` {"concept": "自动熔炉"}
- 步2: ✗ `ask_user` {"question": "自动熔炉模组选哪个? 机械动力(create)、通用机械(mekanism)、热力(thermal)"}
  - 面试评级:___  备注:___
**Qwen3.5 0.8B** [方向命中 0/2 步]
- 步1: ✗ `find_compatible_mod_replacement` {"mod": "minecraft:smoke"}
- 步2: ✗ `find_compatible_mod_replacement` {"mod": "minecraft:smoke"}
  - 面试评级:___  备注:___
**Qwen3.5 2B** [方向命中 1/2 步]
- 步1: ✓ `search_mods` {"query": "auto furnace", "limit": 10}
- 步2: ✗ `create_plugin` {"mod": "thermal", "version": "1.12.0"}
  - 面试评级:___  备注:___
**Qwen3.5 4B** [方向命中 1/2 步]
- 步1: ✓ `search_mods` {"query": "自动熔炉", "instance_id": "fabric-1.21.1"}
- 步2: ✗ `ask_user` {"question": "你更倾向于哪个模组？(1.机械动力, 2.通用机械, 3.热力)"}
  - 面试评级:___  备注:___
**Qwen3.5 9B** [方向命中 1/2 步]
- 步1: ✓ `search_mods` {"query": "自动熔炉"}
- 步2: ✗ `ask_user` {"question": "你想安装哪个自动熔炉模组？(create, mekanism, thermal)"}
  - 面试评级:___  备注:___

### ms_stillcrash · 我装了 sodium 但游戏还是崩
*装了还崩(多步:诊断→处理)  期望:装了没用→诊断原因→处理冲突,而非重复装*

**Bonsai 2 27B (PTQ1_0)** [方向命中 1/2 步]
- 步1: ✓ `read_crash_report` {}
- 步2: ✗ `list_instances` {}
  - 面试评级:___  备注:___
**MiMo-V2.6 Distill Qwen 9B** [方向命中 0/2 步]
- 步1: ✗ `` {}
- 步2: ✗ `` {}
  - 面试评级:___  备注:___
**Qwen3.5 0.8B** [方向命中 0/2 步]
- 步1: ✗ `resolve_mod_concept` {"mod": "sodium"}
- 步2: ✗ `repair_instance_core` {}
  - 面试评级:___  备注:___
**Qwen3.5 2B** [方向命中 0/2 步]
- 步1: ✗ `get_key_bindings` {}
- 步2: ✗ `get_key_bindings` {}
  - 面试评级:___  备注:___
**Qwen3.5 4B** [方向命中 0/2 步]
- 步1: ✗ `inspect_mod_jar` {"mod_id": "sodium"}
- 步2: ✗ `list_mods` {}
  - 面试评级:___  备注:___
**Qwen3.5 9B** [方向命中 1/2 步]
- 步1: ✓ `read_crash_report` {}
- 步2: ✗ `search_mods` {"query": "sodium"}
  - 面试评级:___  备注:___

### ms_dep · neoforge-21.1.248 装不上 sodium,提示缺依赖
*依赖缺失(多步:查→补)  期望:装不上→查依赖→补前置*

**Bonsai 2 27B (PTQ1_0)** [方向命中 2/2 步]
- 步1: ✓ `find_compatible_mod_replacement` {"instance_id": "neoforge-21.1.248", "mod_name": "sodium"}
- 步2: ✓ `install_mod` {"instance_id": "neoforge-21.1.248", "mod_name": "lithium"}
  - 面试评级:___  备注:___
**MiMo-V2.6 Distill Qwen 9B** [方向命中 1/2 步]
- 步1: ✗ `inspect_instance_core` {"instance_id": "neoforge-21.1.248"}
- 步2: ✓ `install_mod` {"instance_id": "neoforge-21.1.248", "mod_id": "lithium"}
  - 面试评级:___  备注:___
**Qwen3.5 0.8B** [方向命中 1/2 步]
- 步1: ✗ `install_mod` {"name": "sodium"}
- 步2: ✓ `install_mod` {"name": "lithium"}
  - 面试评级:___  备注:___
**Qwen3.5 2B** [方向命中 0/2 步]
- 步1: ✗ `get_key_bindings` {}
- 步2: ✗ `get_key_bindings` {}
  - 面试评级:___  备注:___
**Qwen3.5 4B** [方向命中 2/2 步]
- 步1: ✓ `find_compatible_mod_replacement` {"mod": "sodium", "instance_id": "neoforge-21.1.248"}
- 步2: ✓ `install_mod` {"instance_id": "neoforge-21.1.248", "mod_id": "lithium"}
  - 面试评级:___  备注:___
**Qwen3.5 9B** [方向命中 1/2 步]
- 步1: ✗ `install_mod` {"instance_id": "neoforge-21.1.248", "mod_id": "sodium", "reason": "缺依赖"}
- 步2: ✓ `install_mod` {"instance_id": "neoforge-21.1.248", "mod_id": "lithium", "reason": "sodium 依赖"}
  - 面试评级:___  备注:___

### ms_downgrade · 我要用一个只支持 1.20.1 的老 mod
*版本不匹配(多步:找兼容→建/问)  期望:版本不匹配→建兼容实例/问用户,而非硬装到不兼容实例*

**Bonsai 2 27B (PTQ1_0)** [方向命中 2/2 步]
- 步1: ✓ `ask_user` {"question": "你想把这个 1.20.1 的 mod 装到哪个实例上？目前可用的实例有：neoforge-21.1.248、fabric-1.21.1、vanilla-1.20.1。vanilla-1.20.1 是 1.20.1 版本，适合你的老 mod。请告诉我你想装到哪个实例，以及 mod 的名字或 jar 文件路径。"}
- 步2: ✓ `ask_user` {"question": "该 mod 只支持 1.20.1 Forge，而当前实例是 1.21.1 NeoForge，不兼容。你希望我：\n1. 安装一个 1.20.1 Forge 实例来装这个 mod？\n2. 找一个兼容 1.21.1 NeoForge 的替代 mod？\n3. 其他操作？"}
  - 面试评级:___  备注:___
**MiMo-V2.6 Distill Qwen 9B** [方向命中 0/2 步]
- 步1: ✗ `resolve_mod_concept` {"concept": "只支持 1.20.1 的老 mod"}
- 步2: ✗ `list_instances` {}
  - 面试评级:___  备注:___
**Qwen3.5 0.8B** [方向命中 0/2 步]
- 步1: ✗ `install_mod` {"mod": "minecraft:cheat", "version": "1.20.1"}
- 步2: ✗ `resolve_mod_concept` {"mod": "minecraft:cheat", "version": "1.20.1"}
  - 面试评级:___  备注:___
**Qwen3.5 2B** [方向命中 0/2 步]
- 步1: ✗ `find_compatible_mod_replacement` {"mod_concept": "1.20.1", "mod_name": "老 mod"}
- 步2: ✗ `backup_instance` {"instance_id": "1.21.1 neoforge"}
  - 面试评级:___  备注:___
**Qwen3.5 4B** [方向命中 0/2 步]
- 步1: ✗ `install_modpack` {"modpack_name": "vanilla-1.20.1"}
- 步2: ✗ `install_modpack` {"modpack_name": "neoforge-21.1.248"}
  - 面试评级:___  备注:___
**Qwen3.5 9B** [方向命中 1/2 步]
- 步1: ✓ `ask_user` {"question": "请提供该 mod 的 mod ID 或文件名，以便我查找兼容版本或进行安装。"}
- 步2: ✗ `find_compatible_mod_versions` {"mod_id": "unknown", "target_version": "1.20.1", "loader": "forge"}
  - 面试评级:___  备注:___

---
*工具选择=期望工具命中率;参数填充=期望参数匹配比例;瞎编率=填了不存在的实例/服务端。*