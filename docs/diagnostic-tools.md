# 多故障实例诊断工具

AI 修复请求现在挂载：snapshot_instance、list_instance_snapshots、restore_instance_snapshot、compare_instance_snapshot、inspect_mod_jar、find_compatible_mod_versions、replace_mod_version、set_mod_enabled、launch_game、observe_game。

推荐顺序：退出游戏 → 创建快照（默认锁定当前 MC/加载器）→ 检查 JAR 内部身份与哈希 → 查严格兼容候选和前置 → 确认单项修改 → 启动 → 观察本轮日志 → 继续诊断。最后比较快照差异，并由用户确认能否进入世界与功能是否保留。不要以创建进程、退出码 0 或模型结束当作测试通过。

完整实例快照包含实例目录里的核心、存档、Mod、配置、脚本等文件，不包含共享 libraries/assets/runtime。需要版本隔离和足够的额外空间；拒绝目录联接或符号链接。复制期间文件变化则不生成有效快照。快照目录：游戏目录/diagnostic_snapshots/实例/快照ID。

恢复前校验快照，当前实例改放在 before-restore-* 目录，不永久删除。快照差异每类最多显示 500 个文件，游戏自己的日志等也可能变化，不能将所有差异归因于 AI。不要在游戏或其他编辑器写入时恢复。

锁定信息在 diagnostic_snapshots/实例/constraint.json，修改核心与启动前检查。没有提供 AI 解锁工具；需要解除测试约束时，退出游戏后由用户管理该文件。它是工具工作流约束，不是对可任意执行源码的插件/工作区权限的安全沙箱。

JAR 检查读取 Fabric/Quilt/Forge/NeoForge/旧版元数据并计算 SHA1/SHA256、检查 CRC。expected_sha1 可填可信版本 API 返回的哈希；即使 ZIP 正常也可能缺文件。元数据同样可能被伪造；工具不会仅凭文件名断言身份。

inspect_mod_jar 现在附带 metadata_summary，机械提取元数据中的身份、依赖和冲突，不根据加载器后缀猜测来源。默认 view=full 同时返回原文；view=summary 仅返回结构化声明、哈希与检查结果，可用于上下文紧张时补查。解析错误明确返回，不默认判为无依赖。set_mod_enabled 返回 JSON，包含实际文件名以及可直接调用的 undo 工具名和参数，避免回复中误写恢复后缀。

替换工具只使用精确 Modrinth 版本 ID，验证 MC/加载器及原文件 SHA1；下载完成后才移走旧 JAR。旧文件保留在 mod-* 目录，可以手动恢复，或者恢复完整快照。依赖不自动安装，需要模型查询后另行操作。启用/禁用通过 .disabled 后缀，不永久删除。锁定测试实例的旧安装工具也改用严格查询。

AI 启动复用 GameLaunchService 的身份、Java、内存与 JVM 参数准备，但诊断进程尚不绑定主窗口的游戏内 AI、联机生命周期与崩溃弹窗。observe_game 只观察本进程内由该工具启动的本轮游戏；默认等待最多 3 秒，可指定 0–10 秒。详细游戏输出留在 AMCL/diagnostic_runs，可能含个人信息，分享前检查；返回 AI 的日志尾部会脱敏。不自动关闭游戏。

现有 ai_runs 记录工具调用与结果。误判数量、真正进入世界、功能保留仍需人工标注。本轮没有改变本地单轮推理路由，也没有运行真实地狱实例。
