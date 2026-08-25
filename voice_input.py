# -*- coding: utf-8 -*-
"""
AI 助手·语音输入(骨架,现阶段只写方法,以后按插件落地)。

参考【微信】的经典交互:**按住 Ctrl+Win(或 Ctrl+Alt)说话 → 系统语音识别 →
文字直接填到【当前光标处】**——这是接管光标,不管光标在哪(启动器输入框、
游戏聊天栏、任何文本框),识别文字都插到光标位置。

So 关键三件事:
1. 全局热键:Ctrl+Win(微信式),按下开始说、松开结束;
2. 语音识别(ASR):把音频转文字(本地 whisper / 云端);
3. 插入光标:识别文字 `insert_at_cursor` 到当前聚焦控件的光标处。

分期:
- 现在:写清这套方法/接口 + 常量(全局热键 = ctrl+win),ASR 留占位,`insert_at_cursor` 可测;
- 以后:把 ASR + 全局热键封装成【插件】(经这些接口),AI 面板「🎤」真正启用。
"""
import os


# 微信式全局热键(按住说话):值为修饰键 + 主键的实际形态(供注册热键的插件用)。
GLOBAL_HOTKEY = "ctrl+win"        # 按住 Ctrl 按住 Win 说话(微信默认)
# 备选(某些键盘/系统 Win 键被占时):
GLOBAL_HOTKEY_ALT = "ctrl+alt"


def insert_at_cursor(widget, text: str) -> bool:
    """【接管光标】把文字插入 widget 当前光标处(微信式,光标在哪插到哪)。
    widget 需是有 textCursor 的 QPlainTextEdit / QTextEdit,或有 cursorPosition
    的 QLineEdit。返回是否成功。"""
    text = (text or "").strip()
    if not text:
        return False
    # 1) QTextEdit / QPlainTextEdit(有 textCursor)
    try:
        if hasattr(widget, "textCursor"):
            cursor = widget.textCursor()
            cursor.insertText(text)     # insertText 会在当前光标处插入(有选中则替换)
            widget.setTextCursor(cursor)
            return True
    except Exception:
        pass
    # 2) QLineEdit 等(用 cursorPosition 位置插入)
    try:
        cur = widget.cursorPosition() if hasattr(widget, "cursorPosition") else len(widget.text())
        widget.setText(widget.text()[:cur] + text + widget.text()[cur:])
        return True
    except Exception:
        return False


def record_and_transcribe(audio_path: str = "") -> str:
    """音频转文字(ASR)。⚠️ 现阶段为占位:真实 ASR(本地 whisper/云端)尚未接入,
    返回空字符串。以后按插件落地时在此调用 ASR,结果交给 `insert_at_cursor` 插入光标。"""
    # TODO(插件): 接入 whisper / 云端语音接口 → 返回识别文字。
    return ""


def record_from_mic(seconds: float = 5.0) -> str:
    """从麦克风录 seconds 秒 → 返回识别文字(暂为占位,未接 ASR)。"""
    # TODO(插件): 采集麦克风 → record_and_transcribe。
    return ""


# ---- 全局热键注册(骨架;真正注册热键在插件层用 WinAPI/全局钩子)----
def hold_to_talk_hotkey() -> tuple:
    """按住说话热键(微信式):返回 (modifiers, key) 描述,供插件注册全局热键。
    modifiers: Ctrl / Alt; key: Win(0x5B 左Win) / Alt。
    返回形如 ('ctrl','win')。"""
    return ("ctrl", "win")


class VoiceInputBuddy:
    """语音输入助手(以后接真实 ASR + 全局热键后,由插件替换)。

    当前:hold-to-talk 的语义占位——start() 表示"开始录音通道",
    拿到识别文字走 on_text(text),由调用方插入光标。
    """

    def __init__(self, input_widget, on_text=None):
        self.input_widget = input_widget
        self.on_text = on_text      # 回调(text):拿到识别文字后处理(如 insert_at_cursor)

    def start(self):
        """开始语音输入(按住 Ctrl+Win 说)。当前为占位,不再处理。"""
        # TODO(插件): (按住)录音 → record_and_transcribe → self.on_text(text)。
        pass

    def stop(self):
        pass
