# -*- coding: utf-8 -*-
"""
技能(Skill)管理系统:可插拔的"游戏运行时辅助"功能模块。

- 每个技能是一个 Skill 子类,挂在游戏生命周期的钩子上:
    on_game_start(游戏启动) / on_game_log(每行日志) / on_game_stop(游戏退出)
- 启用状态持久化在 config.json 的 skills 字段({技能id: true/false})
- 以后新增辅助功能:在 BUILTIN_SKILLS 列表里加一个 Skill 子类即可,
  菜单"技能 → 技能管理"会自动出现它的开关。

内置技能(示例,验证框架):
  1. 崩溃自动重启 —— 游戏异常退出后询问是否一键重启(带防循环)
  2. 备份提醒   —— 正常退出后,如果存档比上次备份新,提醒备份(灵感 #6 联动)
"""
import os

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt


class Skill:
    """技能基类:子类覆盖需要的钩子即可,未覆盖的钩子自动跳过。"""
    id = "skill"                 # 唯一 id(存进 config.json)
    name = "未命名技能"
    description = "暂无说明"
    category = "运行辅助"
    default_enabled = False      # 默认开启?(保守起见默认关)

    def __init__(self, manager):
        self.manager = manager   # SkillManager,可通过 .main 访问主窗口

    # ---- 生命周期钩子(默认空实现)----
    def on_game_start(self, process, instance_id: str):
        """游戏进程刚启动(主线程)。process = subprocess.Popen 对象"""

    def on_game_log(self, line: str):
        """游戏输出的每一行(主线程,按行实时回调)"""

    def on_game_stop(self, exit_code):
        """游戏进程退出(主线程)。exit_code 0 = 正常退出"""

    def _inst_dir(self, instance_id: str) -> str:
        """实例游戏目录(隔离开时就是实例自己的目录)"""
        return self.manager.main.game_dir_for(instance_id)

    def ai_hint(self) -> str:
        """给 AI 的提示文本(技能启用后注入 ai_context,指导 AI 行为)。默认无。"""
        return ""


# ================= 内置技能 =================

class AutoRestart(Skill):
    """崩溃自动重启:游戏异常退出后询问是否一键重启(带防循环)"""
    id = "auto_restart"
    name = "崩溃自动重启"
    description = ("游戏异常退出(退出码非 0)后,弹窗询问是否自动重启游戏。\n"
                   "连续崩溃 2 次会自动停止询问,避免死循环。")
    category = "运行辅助"
    default_enabled = True

    def __init__(self, manager):
        super().__init__(manager)
        self._crash_count = 0

    def on_game_stop(self, exit_code):
        if exit_code in (0, None):
            self._crash_count = 0
            return
        self._crash_count += 1
        if self._crash_count >= 2:
            return   # 连续崩溃:不再自动询问,交给用户手动处理
        if not self.manager.main.game_process or self.manager.main.game_process.poll() is not None:
            ret = QMessageBox.question(
                self.manager.main, "游戏异常退出",
                f"游戏异常退出(退出码 {exit_code})。\n要自动重启吗?")
            if ret == QMessageBox.StandardButton.Yes:
                self.manager.main.launch_selected()   # 重新启动当前实例


class BackupReminder(Skill):
    """备份提醒:正常退出后,若存档比上次备份新,提醒备份(灵感 #6)"""
    id = "backup_reminder"
    name = "备份提醒"
    description = ("游戏正常退出后,如果检测到存档(saves)比最近一次备份更新,\n"
                   "提醒你备份存档,防坏档。")
    category = "存档安全"
    default_enabled = True

    def on_game_stop(self, exit_code):
        if exit_code != 0:
            return   # 异常退出由自动 debug 处理
        main = self.manager.main
        inst_id = getattr(main, "_running_instance_id", None)
        if not inst_id:
            return
        inst_dir = main.game_dir_for(inst_id)
        saves_dir = os.path.join(inst_dir, "saves")
        if not os.path.isdir(saves_dir):
            return
        latest_save = 0.0
        for name in os.listdir(saves_dir):
            p = os.path.join(saves_dir, name)
            if os.path.isdir(p):
                latest_save = max(latest_save, os.path.getmtime(p))

        from backup import list_backups
        import paths
        baks = list_backups(inst_id, paths.GAME_DIR)
        latest_bak = max((os.path.getmtime(b["path"]) for b in baks), default=0.0)
        if latest_save > latest_bak:
            ret = QMessageBox.question(
                main, "备份提醒",
                "检测到存档比最近一次备份更新,建议备份防坏档。\n现在备份吗?")
            if ret == QMessageBox.StandardButton.Yes:
                from backup import backup_instance
                try:
                    out = backup_instance(inst_id, paths.GAME_DIR)
                    main.statusBar().showMessage(f"已备份到:{out}")
                except Exception as e:
                    main.statusBar().showMessage(f"备份失败:{e}")


class CommandGuide(Skill):
    """指令指南:按游戏版本生成正确的原版指令(重点: NBT/组件写法)"""
    id = "command_guide"
    name = "指令指南"
    description = ("生成各版本原版指令(自动适配 1.13 指令改版、1.20.5 物品组件、\n"
                   "老版本数字 id),着重正确书写 NBT 标签。助手生成指令前会用 \n"
                   "get_command_guide 工具查版本写法。")
    category = "运行辅助"
    default_enabled = True

    def ai_hint(self) -> str:
        return ("【指令指南已启用】需要给游戏生成/修改指令时,"
                "先调用 get_command_guide 查该版本的 NBT/组件写法再生成,"
                "避免版本语法错误。")


class TaskSplit(Skill):
    """任务拆分:长任务分成多步逐步执行,每步检查结果再继续"""
    id = "task_split"
    name = "任务拆分"
    description = ("长任务自动拆成小步逐步执行(如 建实例:先原版→再加载器→再 Mod)。\n"
                   "每步执行后检查工具返回结果,确认做完再走下一步;\n"
                   "不确定用户意图时调用 ask_user 让用户选择/补充。")
    category = "AI 助手"
    default_enabled = True

    def ai_hint(self) -> str:
        return ("【任务拆分已启用】长任务先拆成小步,一步一个工具,逐步完成。"
                "每步执行后检查返回结果(成功/失败/列表)再决定下一步:"
                "实例是否装好 → 用 list_instances 确认;Mod 是否装好 → 用 list_mods 确认;"
                "某步失败就停下来向用户说明原因,不要硬继续。"
                "拿不准用户想要什么时,调用 ask_user 工具让用户勾选/补充。")


class BridgeModGuide(Skill):
    """bridge-mod 指南:让 AI 知道启动器内置的自制私有 Mod(测试阶段,不成熟)"""
    id = "bridge_mod_guide"
    name = "bridge-mod 指南"
    description = ("告知 AI 启动器内置一个自制私有 Mod「agentmc-bridge」(测试阶段,不成熟):\n"
                   "进世界后开本地指令口(127.0.0.1:26100)发游戏指令 100% 精确反馈,\n"
                   "并导出配方/物品/按键数据供查询。仅支持 Fabric/NeoForge · MC 1.21.1。")
    category = "运行辅助"
    default_enabled = True

    def ai_hint(self) -> str:
        return ("【bridge-mod 指南已启用】启动器内置一个自制**私有 Mod**「agentmc-bridge」"
                "(测试阶段,不成熟,有 bug 属正常):\n"
                "- 用途:进世界后开本地指令口(127.0.0.1:26100),发游戏指令 100% 精确反馈;"
                "并导出配方/物品/按键数据供 AI 查询。\n"
                "- 支持范围:**仅 Fabric / NeoForge · MC 1.21.1**(v0.1.0);其他版本/加载器没有,"
                "不要建议用户在那里装。\n"
                "- 装法:引导用户用首页「一键配置 ▾ → 一键配置 bridge-mod」,"
                "或手动把 agentmc-bridge-*.jar 放进实例 mods 目录。\n"
                "- 生效条件:必须**进游戏并进入世界**后才有指令口(实例 .bridge/ 下生成 token.txt);"
                "没进世界时提示用户先进世界。\n"
                "- 指令通道:发游戏指令优先走 bridge(send_game_command 自动探测),"
                "bridge 不可用时 RCON/模拟按键兜底。\n"
                "- 用户问「桥 mod / 指令 mod / bridge」相关时按此说明回答,"
                "并说明它是测试阶段私有 Mod。")


class CrossLoaderModGuide(Skill):
    """非主流/跨加载器 Mod 检查:AI 判断兼容性/缺失依赖时不要想当然
    (例: voxy 本是 Fabric mod,却有 GitHub 上的非官方 NeoForge 版)"""
    id = "cross_loader_mod_guide"
    name = "非主流 Mod 兼容性检查"
    description = ("提醒 AI:存在「同名但跨加载器」的非主流 Mod(如 Fabric 专属 mod 有非官方的 "
                   "NeoForge/Forge 移植版,常见于 GitHub/CurseForge),以及「Fabric Mod 被转译到 "
                   "Forge/NeoForge、把 fabric-api 换成 Forge 等价物」的可能。"
                   "判断某个 Mod 在指定加载器上有没有时,先检查是否有社区移植版,别过早说'没有'。")
    category = "AI 助手"
    default_enabled = True

    def ai_hint(self) -> str:
        return ("【非主流/跨加载器 Mod 检查已启用】给用户判断 Mod 兼容性、缺失依赖、'某加载器上有没有这个 Mod'时,"
                "先别下结论,注意三种可能:\n"
                "- **同名跨加载器的非官方版**:很多 Mod 本是某一加载器专属,但有人在社区出过另一加载器的移植版"
                "(常见于 GitHub / CurseForge,文件名常带 `-forge`、`-neoforge` 后缀,大概率**非官方**)。"
                "例:`voxy` 本是 **Fabric** 优化 Mod,却存在 GitHub 发布的 **NeoForge** 版(非官方版,不稳定)。\n"
                "- **存在'转译/迁移'的可能**:有些 Fabric Mod 被迁移(transpiled)到 Forge/NeoForge,"
                "会把 `fabric-api` 依赖换成 Forge 等价物,或直接内嵌进移植版。"
                "所以**'缺 fabric-api' 不一定真缺**——可能是被移植版内嵌或等价替代,别急着报'装了 A 缺 B'。\n"
                "- **选装/需自行编译的资源**:有的 Mod 是整合包的**选装(optional)资源**,甚至要**跑编译脚本**"
                "才能装(如 `voxy`:本是 Fabric 优化 Mod,本整合包版本为**选装**,想装还得先编译)。"
                "这类 Mod 缺失时**不是装漏了**,而是作者故意没带 / 需要用户自行编译;"
                "别当'缺失依赖'报错,应说明'这是选装资源,想装需先编译/手动添加'。\n"
                "- **提示策略**:当某 Mod 在当前加载器上'找不到/没适配'时,应向用户说明"
                "'可能只有 Fabric 原版,但有非官方 NeoForge/Forge 移植版(会更易出 bug、不随原版更新)'"
                "让用户自己决定是否装非官方版;若用户想装,提醒其风险。\n"
                "判断前可先用 search_mods / translate_mod_desc / 读实例 mods 核对该 Mod 的真实加载器与依赖,"
                "不要凭印象断定。")


class CrashDiagnosisGuide(Skill):
    """崩溃诊断「修改意见清单」:让 AI 分析崩溃时输出结构化、可照着做的清单,而不是一段话"""
    id = "crash_diagnosis_guide"
    name = "崩溃诊断 · 修改意见清单"
    description = ("游戏崩溃/异常时,AI 先读日志与崩溃报告,然后输出【修改意见清单】"
                   "(每条 = 改什么 + 为什么/怎么做,按严重度排序 + 兜底步骤),方便你照着一步步做。")
    category = "运行辅助"
    default_enabled = True

    def ai_hint(self) -> str:
        return ("【崩溃诊断·修改意见清单】用户遇到游戏崩溃/报错要你诊断时,按下面做:\n"
                "① 先读日志(read_instance_log)与崩溃报告(read_crash_report),定位异常类型"
                "(如 NullPointerException / ClassNotFound / OutOfMemoryError)和涉及的 Mod/加载器;\n"
                "② 然后输出【修改意见清单】(编号 + 每条一行,按严重度排序,**别只给一大段话**):\n"
                "   〔动作〕改什么(如 换/升/降 Java 版本、删冲突 Mod、关掉含中文/特殊字符的路径、加内存、"
                "更新/移除某 Mod 或光影、重装整合包、清空配置)\n"
                "   　说明:为什么(对应哪个错误特征)/ 具体怎么做(去哪改)。\n"
                "③ 若不能确定具体原因,给 1~2 条「先试」的兜底步骤(如 单独重启 1 次、干净重装该整合包、"
                "换回上一版);不要硬说成确定结论。\n"
                "④ 用中文;专业术语(完整异常类名、Mod 名、文件路径、版本号)保留原样,方便定位。")


class McNameNormalize(Skill):
    """本地名称归一化:查 wiki/资料库前,先把中文/口语叫法解析成规范英文名+id"""
    id = "mc_name_normalize"
    name = "本地名称归一化 · 查 wiki 更准"
    description = ("当你要用外部 wiki / 资料库(MCP)查某个物品/生物/效果/附魔,"
                   "或用户给了中文/口语叫法(如 苦力怕、会爆炸的怪)时,先本地解析成规范英文名+id 再查,命中更准。")
    category = "运行辅助"
    default_enabled = True

    def ai_hint(self) -> str:
        return ("【本地名称归一化·查 wiki 更准】要用外部 wiki / 资料库(MCP)查某物品/生物/效果/附魔,"
                "或用户给了中文/口语叫法(如「苦力怕」「会爆炸的怪」「锋利」)时:\n"
                "① **先用 resolve_mc_name 把叫法解析成规范英文名 + id**(如 苦力怕 → Creeper / minecraft:creeper);\n"
                "② 再用这个规范英文名/id 去查 wiki/资料库,别用用户口语生查;\n"
                "③ resolve_mc_name 查不到(可能 Mod 专属/生僻)就直接用它检索,别硬造 id;\n"
                "④ 支持物品/方块/生物/效果/附魔,读实例 lang 文件 + 内置常见词表(离线也准)。")


class CloudAIConfigGuide(Skill):
    """云端 AI 配置指南:让 AI 教用户一步步配好云端模型(DeepSeek/OpenRouter/国内/自定义)"""
    id = "cloud_ai_config_guide"
    name = "云端 AI 配置指南"
    description = ("教用户配置云端 AI(设置 → AI 助手 → 云端块):选服务商 → 自动填接口地址 "
                   "→ 去平台注册拿 API Key 粘贴 → 填模型名 → **点连接测试/发一条消息验证**。\n"
                   "覆盖 DeepSeek/OpenRouter/硅基流动/智谱GLM/通义千问/自定义,以及 401/402/404/429\n"
                   "等失败原因。云端=更强,本地=免费离线;未配云端时「本地优先/混合」仍可用内置本地。")
    category = "AI 助手"
    default_enabled = True

    def ai_hint(self) -> str:
        return ("【云端 AI 配置指南已启用】用户想配置「云端 AI」时,带他按下面步骤做,"
                "并把**最终结果验证到底**(AI规划 §4.3 验证最终结果):\n"
                "\n"
                "① 定位:设置 →「AI 助手」→「云端块」(AI 策略选「云端优先」或「混合」时显示);\n"
                "② 选「服务商」(下拉 _CLOUD_PROVIDERS:DeepSeek(推荐,便宜好用)/ OpenRouter / "
                "硅基流动 / 智谱 GLM / 通义千问 / 自定义);\n"
                "③ 「接口地址」:选服务商后自动填(如 DeepSeek→https://api.deepseek.com/v1),"
                "别手改除非自定义;custom 让用户自己填;\n"
                "④ 「API 密钥」:引导用户**去对应平台官网注册**(DeepSeek platform、"
                "OpenRouter、siliconflow、open.bigmodel.cn、dashscope.aliyuncs.com 等)生成 Key,"
                "复制粘贴进来(本地/离线模式留空);提醒 Key 是敏感信息、不要外发;\n"
                "⑤ 「模型」:按服务商自动填默认(DeepSeek→deepseek-chat;OpenRouter→"
                "deepseek/deepseek-chat-v3-0324:free;硅基流动→Qwen/Qwen2.5-7B-Instruct;"
                "智谱→glm-4-flash;通义→qwen-plus);也可让用户按需改;\n"
                "⑥ **验证最终结果(最重要)**:保存后,切到 AI 面板发一条消息,看是否有正常回复;"
                "或点「🛠 测试工具」/「连接测试」式的自测,确认 Key 真的能用。"
                "**别只描述流程,要让用户/你确认实际能通**;\n"
                "⑦ 若用户已有可用 Key 但想换服务商:只需改服务商+Key+模型,地址会自动跟;\n"
                "\n"
                "【常见适配】OpenRouter 部分模型**会看图**(图像输入),模型名如 "
                "`anthropic/claude-3.5-sonnet`;硅基流动/智谱/通义为国内(通常无需翻墙,"
                "速度/合规更稳);custom 自定义接口(OpenAI 兼容 /v1)。\n"
                "\n"
                "【失败路径友好解释(AI规划 §4.5)】按错误码提示,别让用户干等:\n"
                "- 401 = API Key 无效或未配置 → 检查密钥是否粘全/正确/没多余空格;\n"
                "- 402 = 账户余额不足 → 提示充值(DeepSeek 按量计费);\n"
                "- 404 = 接口地址或模型名不存在 → 检查设置的接口地址/模型名;\n"
                "- 429 = 请求太频繁 → 稍后再试;\n"
                "- 网络异常/超时 = 查联网、确认接口地址正确(可让用户在浏览器打开该地址验证)。\n"
                "\n"
                "【未配云端也能用】若用户没配/配不好云端,「本地优先」或「混合」也能走**内置本地模型**"
                "(离线免费,首次自动下载约 500MB);云端是「更强」但**可选**的增强项——"
                "对应定位:**云端=大脑(更强),本地=手(免费离线)**。让用户权衡,别强推。\n"
                "\n"
                "【可读文本】用户想直接看教程时,把以上要点整理成一段人类可读说明发给他。")


BUILTIN_SKILLS = [AutoRestart, BackupReminder, CommandGuide, TaskSplit,
                  BridgeModGuide, CloudAIConfigGuide, CrossLoaderModGuide, CrashDiagnosisGuide,
                  McNameNormalize]


# ================= 管理器 =================

class SkillManager:
    """技能管理器:持有全部技能实例,分发游戏生命周期事件,持久化启停状态。"""

    def __init__(self, main_window, settings: dict):
        self.main = main_window
        self.settings = settings
        self.skills = [cls(self) for cls in BUILTIN_SKILLS]
        # 插件注册的技能(plugin_manager.SKILLS):附属到内置技能之后,同样受启停控制
        try:
            import plugin_manager
            for skcls in plugin_manager.SKILLS:
                try:
                    self.skills.append(skcls(self))
                except Exception:
                    pass
        except Exception:
            pass

    def is_enabled(self, skill_id: str) -> bool:
        s = self.settings.get("skills", {}) or {}
        if skill_id in s:
            return bool(s[skill_id])
        for sk in self.skills:
            if sk.id == skill_id:
                return sk.default_enabled
        return False

    def set_enabled(self, skill_id: str, enabled: bool):
        self.settings.setdefault("skills", {})[skill_id] = enabled
        from settings import save_settings
        save_settings(self.settings)

    def list(self) -> list:
        """[{id, name, description, category, enabled}]"""
        return [{"id": sk.id, "name": sk.name, "description": sk.description,
                 "category": sk.category, "enabled": self.is_enabled(sk.id)}
                for sk in self.skills]

    def get(self, skill_id: str):
        return next((sk for sk in self.skills if sk.id == skill_id), None)

    def ai_hints(self) -> list:
        """已启用技能给 AI 的提示文本列表(注入 ai_context)"""
        return [sk.ai_hint() for sk in self.skills
                if self.is_enabled(sk.id) and sk.ai_hint()]

    # ---- 游戏生命周期分发 ----
    def on_game_start(self, process, instance_id: str):
        for sk in self.skills:
            if self.is_enabled(sk.id):
                try:
                    sk.on_game_start(process, instance_id)
                except Exception:
                    pass

    def on_game_log(self, line: str):
        for sk in self.skills:
            if self.is_enabled(sk.id):
                try:
                    sk.on_game_log(line)
                except Exception:
                    pass

    def on_game_stop(self, exit_code):
        for sk in self.skills:
            if self.is_enabled(sk.id):
                try:
                    sk.on_game_stop(exit_code)
                except Exception:
                    pass


# ================= 管理对话框 =================

class SkillManagerDialog(QDialog):
    """技能管理:列表勾选启停,下方显示说明。"""

    def __init__(self, manager: SkillManager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.setWindowTitle("技能管理")
        self.setMinimumSize(520, 420)

        self.list_widget = QListWidget()
        self.desc_label = QLabel("")
        self.desc_label.setWordWrap(True)

        hint = QLabel("技能 = 游戏运行时的辅助功能(如自动重启、备份提醒、指令指南)。\n"
                      "以后会逐渐添加更多,勾选即启用、取消勾选即停用,立即生效。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888888;")

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("游戏运行时辅助技能:"))
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.desc_label)
        layout.addWidget(hint)
        layout.addLayout(row)

        self.list_widget.itemChanged.connect(self._on_item_changed)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        self._reload()
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def _reload(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for info in self.mgr.list():
            item = QListWidgetItem(f"[{info['category']}] {info['name']}")
            item.setData(Qt.ItemDataRole.UserRole, info["id"])
            item.setCheckState(Qt.CheckState.Checked if info["enabled"]
                               else Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

    def _on_item_changed(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        self.mgr.set_enabled(sid, item.checkState() == Qt.CheckState.Checked)
        # 更新说明
        for info in self.mgr.list():
            if info["id"] == sid:
                self.desc_label.setText(
                    f"{info['name']}({'已启用' if info['enabled'] else '已停用'}):\n{info['description']}")

    def _on_current_changed(self, current, _prev):
        if current is None:
            return
        sid = current.data(Qt.ItemDataRole.UserRole)
        for info in self.mgr.list():
            if info["id"] == sid:
                self.desc_label.setText(
                    f"{info['name']}({'已启用' if info['enabled'] else '已停用'}):\n{info['description']}")
                break
