"""Command-bridge setup dialogs and task wiring, independent of MainWindow."""
import os
from PySide6.QtWidgets import QMessageBox
from launcher_app.core.i18n import t
from launcher_app.core.background_tasks import BackgroundTask
from launcher_app.ui.ui_notifications import inline_notice, inline_warning, action_question
from launcher_app.instances.command_setup import CommandSetupRequest


class CommandSetupController:
    def __init__(self, *, parent, game_dir_for, submit, show_status, clear_status):
        self.parent, self.game_dir_for = parent, game_dir_for
        self.submit, self.show_status, self.clear_status = submit, show_status, clear_status

    def _request(self, inst):
        return inst.get('_setup_request') or CommandSetupRequest.capture(inst, self.game_dir_for(inst['id']))

    def _capture(self, inst):
        from copy import deepcopy
        captured = deepcopy(inst)
        captured['_setup_request'] = self._request(inst)
        return captured

    def _one_click_bridge_for(self, inst):
        """一键配置 bridge-mod(本地指令口,推荐):检测 → 确认 → 自动下载安装。
        兼容(能自动发现该加载器+版本)则下载;不兼容 → 明确提示 + 说明可改走 RCON。
        已装但版本旧(check_bridge_mod=outdated)→ 提示可更新到最新。

        ⚠ 状态检测要读本地 dist 并访问 GitHub(同步网络请求),必须放后台线程:
        早期直接在 UI 线程里调,最坏会卡十几秒,用户看到的就是"点了没反应、也没弹框"。
        """
        inst = self._capture(inst)
        loader = inst.get("loader")
        if loader not in ("fabric", "forge", "neoforge"):
            inline_notice(self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                                    t('该实例没有加载器(原版),bridge-mod 是 mod 需要加载器。\n先给这个实例装个 Fabric/Forge 等加载器再回来。'))
            return
        self._check_bridge_async(inst, self._on_bridge_status_ready)

    def _check_bridge_async(self, inst, on_ready):
        inst = self._capture(inst)
        request = self._request(inst)
        self.show_status(f"正在检测 {inst['id']} 的 bridge-mod 状态…")
        task = BackgroundTask(request.check_bridge, self.parent)
        task.succeeded.connect(lambda payload: on_ready(inst, payload))
        task.failed.connect(lambda err: inline_warning(
            self.parent, t('一键配置 · {v0}').format(v0=inst['id']),
            t('检测 bridge-mod 状态失败:{v0}\n(可能是无法访问 GitHub;也可以手动把 agentmc-bridge-*.jar 放进实例 mods 目录)').format(v0=err)))
        task.finished.connect(self.clear_status)
        task.start()


    def _on_bridge_status_ready(self, inst, payload):
        """bridge-mod 状态检测完成(信号已回到 UI 线程)→ 弹确认框并决定是否安装。"""
        status = (payload or {}).get("status")
        info = (payload or {}).get("info")
        if status == "up_to_date":
            inline_notice(self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                                    t("✅ bridge-mod 已就绪且是最新:重进世界即可用本地指令口\n(无需'对局域网开放',指令结果可精确回传)。"))
            return
        if status == "incompatible":
            ret = action_question(
                self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                t('检测到当前 mods 目录中有其他 MC 版本或加载器的 bridge-mod。\n\n将替换为适用于 {v0}+{v1} 的版本吗？').format(v0=(inst['base']), v1=(inst['loader'])), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if ret == QMessageBox.StandardButton.Yes:
                self._install_bridge_mod(inst)
            return
        if status == "outdated":
            ret = action_question(
                self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                t('⚠️ 检测到已装 bridge-mod 但版本较旧({v0}+{v1})。\n\n自动更新到最新版吗?(会覆盖旧的 jar)').format(v0=(inst['base']), v1=(inst['loader'])), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if ret == QMessageBox.StandardButton.Yes:
                self._install_bridge_mod(inst)
            return
        if info is None:
            # 不兼容:明确提示,并引导走 RCON 临时方案
            inline_notice(
                self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                t('💡 bridge-mod 暂不兼容 {v0}+{v1}(版本表/自动发现都没有这个组合)。\n\n可以改用临时方案 RCON:功能略弱(指令结果不精确),但覆盖更多版本。\n要换 RCON 的话,点菜单里的「一键配置 RCON」。').format(v0=(inst['base']), v1=(inst['loader'])))
            return
        ret = action_question(self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                                   t('未安装 bridge-mod(本地指令口,推荐)。\n\n检测到 {v0}+{v1} 可用的 bridge-mod v{v2},自动下载安装吗?').format(v0=(inst['base']), v1=(inst['loader']), v2=(info['version'])), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._install_bridge_mod(inst)

    def _one_click_rcon_for(self, inst):
        """一键配置 RCON(临时方案):需要 Lan Server Properties + 进世界后手动对局域网开放"""
        inst = self._capture(inst)
        from launcher_app.instances.game_command import ensure_rcon_config, has_lan_server_properties, read_rcon_config
        inst_dir = self._request(inst).game_dir
        loader = inst.get("loader")
        if read_rcon_config(inst_dir):
            inline_notice(self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                                    t('✅ RCON 已就绪。\n(临时方案:进世界后按 ESC → 对局域网开放,RCON 才监听端口)'))
            return
        if not has_lan_server_properties(inst_dir):
            if loader not in ("fabric", "forge", "neoforge"):
                inline_notice(
                    self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                    t('该实例没有加载器(原版),而 Lan Server Properties 需要加载器。\n先给这个实例装个加载器再回来。'))
                return
            ret = action_question(
                self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                t("临时方案需要 Lan Server Properties mod\n(自动开 RCON,但每次进世界需手动'对局域网开放')。\n\n是否自动从 Modrinth 下载并安装?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if ret != QMessageBox.StandardButton.Yes:
                return
            self._install_lan_server_properties(inst)
            return
        msg = ensure_rcon_config(inst_dir)
        if "\n" in msg:
            inline_notice(self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])), msg)
        else:
            self.show_status(msg)

    def _add_online_mod_menu_items(self, menu, inst):
        """在实例右键菜单加「一键配置 <联机mod>」项——仅当该实例版本+加载器支持时才显示。"""
        import launcher_app.runtime.online_mods as lan_tools
        gv = inst.get("base")
        loader = inst.get("loader") or ""
        if loader not in ("fabric", "forge", "neoforge"):
            return
        for slug, name in lan_tools.ONLINE_MODS.items():
            try:
                ok = lan_tools.mod_supported(slug, gv, loader)
            except Exception:
                continue
            if ok:
                it = menu.addAction(
                    t('一键配置 {v0}…').format(v0=(name)),
                    lambda _c=False, s=slug: self._one_click_online_mod_for(inst, s))
                it.setToolTip(t('{v0}:{v1}+{v2} 可用,自动下载安装').format(v0=(name), v1=(gv), v2=(loader)))

    def _one_click_online_mod_for(self, inst, slug: str):
        """一键配置联机 mod(Essential / e4mc):按版本+加载器判断是否支持,支持才装。
        已装 → 提示就绪;不支持 → 说明不支持;支持且未装 → 确认后后台下载。"""
        inst = self._capture(inst)
        import launcher_app.runtime.online_mods as lan_tools
        inst_dir = self._request(inst).game_dir
        loader = inst.get("loader") or ""
        gv = inst["base"]
        name = lan_tools.ONLINE_MODS.get(slug, slug)
        # 不支持 → 明确说明
        if loader not in ("fabric", "forge", "neoforge"):
            inline_notice(self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                                    t('该实例没有加载器(原版),{v0} 是 mod 需要加载器。\n先装个 Fabric/Forge 再回来。').format(v0=(name)))
            return
        if not lan_tools.mod_supported(slug, gv, loader):
            inline_notice(self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
                                    t('{v0} 暂不支持 {v1}+{v2}。\n可以换个版本,或到「联机」看别的方案。').format(v0=(name), v1=(gv), v2=(loader)))
            return
        # 已装?
        mods_dir = os.path.join(inst_dir, "mods")
        has = any(name and (slug in f.lower() or name.split("(")[0].strip().lower() in f.lower())
                  for f in os.listdir(mods_dir) if f.endswith(".jar")) if os.path.isdir(mods_dir) else False
        ret = action_question(
            self.parent, t('一键配置 · {v0}').format(v0=(inst['id'])),
            (t('✅ {v0} 支持 {v1}+{v2}。\n\n{v3}').format(v0=(name), v1=(gv), v2=(loader), v3=('已检测到,重装/更新吗?' if has else '自动从 Modrinth 下载并安装到该实例吗?'))),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if ret != QMessageBox.StandardButton.Yes:
            return
        self.show_status(f"正在为 {inst['id']} 安装 {name}…")

        from functools import partial
        self.submit(partial(self._request(inst).install_online, slug))


    def _one_click_config_for(self, inst):
        """对指定实例执行一键配置(自动:bridge-mod 优先,不兼容则提示走 RCON)。
        菜单里两个显式入口(bridge / RCON)之外的兜底逻辑。
        已装但版本旧(outdated)→ 走 bridge 提示(触发更新)。"""
        inst = self._capture(inst)
        loader = inst.get("loader")
        if loader in ("fabric", "forge", "neoforge"):
            # 与 bridge 入口共用同一个后台检测,避免在 UI 线程同步访问 GitHub 卡住界面
            self._check_bridge_async(inst, self._on_config_auto_ready)
            return
        self.show_status(
            f"bridge-mod 暂不可用于 {inst['base']}+{loader or '原版'},改走 RCON 临时方案")
        self._one_click_rcon_for(inst)

    def _on_config_auto_ready(self, inst, payload):
        """自动模式的检测结果:bridge 已装/可用 → 走 bridge 提示;否则回退 RCON。"""
        status = (payload or {}).get("status")
        info = (payload or {}).get("info")
        if status != "not_installed" or info:
            self._on_bridge_status_ready(inst, payload)
            return
        self.show_status(
            f"bridge-mod 暂不可用于 {inst['base']}+{inst['loader'] or '原版'},改走 RCON 临时方案")
        self._one_click_rcon_for(inst)

    def _install_bridge_mod(self, inst):
        request = self._request(inst)
        self.show_status(f"正在为 {inst['id']} 下载 bridge-mod…")
        self.submit(request.install_bridge)


    def _install_lan_server_properties(self, inst):
        request = self._request(inst)
        self.show_status(f"正在为 {inst['id']} 下载 Lan Server Properties…")
        self.submit(request.install_lan_properties)
