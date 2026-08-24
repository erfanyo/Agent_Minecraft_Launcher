# -*- coding: utf-8 -*-
"""
技能(Skill)管理系统:可插拔的"游戏运行时辅助"功能模块。

- 每个技能是一个 Skill 子类,挂在游戏生命周期的钩子上:
    on_game_start(游戏启动) / on_game_log(每行日志) / on_game_stop(游戏退出)
- 启用状态持久化在 config.json 的 skills 字段({技能id: true/false})
- 以后新增辅助功能:在 BUILTIN_SKILLS 列表里加一个 Skill 子类即可,
  菜单"技能 → 技能管理"会自动出现它的开关。

内置技能(示例,验证框架):
  1. 崩溃守护   —— 实时扫日志,发现崩溃特征弹提示
  2. 崩溃自动重启 —— 游戏异常退出后询问是否一键重启(带防循环)
  3. 备份提醒   —— 正常退出后,如果存档比上次备份新,提醒备份(灵感 #6 联动)
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

class CrashWatchdog(Skill):
    """崩溃守护:实时扫日志,发现崩溃特征立即弹提示"""
    id = "crash_watchdog"
    name = "崩溃守护"
    description = ("游戏运行时实时扫描日志,检测到崩溃特征(如 Exception in thread / "
                   "OutOfMemoryError / crash report)立即弹窗提示,不用等退出才发现。")
    category = "运行辅助"
    default_enabled = True

    CRASH_MARKS = (
        "exception in thread",
        "outofmemoryerror",
        "crash report",
        "fatal error",
        "failed to start the minecraft server",
        "there was a severe problem",
        "a fatal error has been detected",
    )

    def __init__(self, manager):
        super().__init__(manager)
        self._notified = False   # 每次游戏只提示一次,避免刷屏

    def on_game_start(self, process, instance_id):
        self._notified = False

    def on_game_log(self, line):
        if self._notified or not self.manager.is_enabled(self.id):
            return
        low = line.lower()
        if any(m in low for m in self.CRASH_MARKS):
            self._notified = True
            QMessageBox.warning(
                self.manager.main, "崩溃守护",
                f"⚠️ 检测到疑似崩溃:\n{line.strip()[:120]}\n\n"
                "游戏可能已崩溃,日志见下方「游戏日志」面板;\n"
                "可以让 AI 助手分析原因(启动器会在退出后自动询问)。")


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


BUILTIN_SKILLS = [CrashWatchdog, AutoRestart, BackupReminder, CommandGuide, TaskSplit,
                  BridgeModGuide]


# ================= 管理器 =================

class SkillManager:
    """技能管理器:持有全部技能实例,分发游戏生命周期事件,持久化启停状态。"""

    def __init__(self, main_window, settings: dict):
        self.main = main_window
        self.settings = settings
        self.skills = [cls(self) for cls in BUILTIN_SKILLS]

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

        hint = QLabel("技能 = 游戏运行时的辅助功能(如崩溃守护、自动重启、备份提醒)。\n"
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
