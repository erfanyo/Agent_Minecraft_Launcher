"""Physical-memory scale: used fill plus independent heap/history markers."""
from launcher_app.core.i18n import t
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from launcher_app.runtime.memory_policy import snapshot, automatic_budget, history_peak, enabled_mod_count, GIB
from launcher_app.runtime.memory_policy import process_usage


def memory_segments(total, available, model, game, budget):
    used = max(0, total - available)
    model = min(used, max(0, model or 0))
    game = min(used - model, max(0, game or 0))
    system = used - model - game
    planned = max(game, budget)
    return system, model, planned, max(0, total-system-model-planned)


class MemoryMeter(QFrame):
    def __init__(self, allocation, history_dir=None, parent=None):
        super().__init__(parent)
        self.allocation = allocation
        self.history_dir = history_dir
        self.state = None
        self.amount = self.peak = 0
        self.basis = ''
        self.segments = (0, 0, 0, 0)
        self.setObjectName('memoryBudgetCard')
        self.setStyleSheet('QFrame#memoryBudgetCard { border: 1px solid rgba(90,150,170,0.35); '
                           'border-radius: 10px; background: rgba(31,47,57,0.20); }')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        title = QLabel(t('内存预算'))
        title.setStyleSheet('font-weight: 600; border: none; background: transparent;')
        layout.addWidget(title)
        legend = QHBoxLayout()
        legend.setSpacing(12)
        self.legend_labels = []
        for text, color in (('系统及其他应用', '#d79b45'), ('本地模型', '#9b72cf'), ('MC 预算', '#42a5c6')):
            chip = QLabel('■  ' + text)
            chip.setStyleSheet(f'color: {color}; border: none; background: transparent;')
            legend.addWidget(chip)
            self.legend_labels.append((chip, t(text)))
        legend.addStretch()
        layout.addLayout(legend)
        self.bar = QWidget(self)
        self.bar.setMinimumHeight(22)
        self.bar.paintEvent = self.paint_bar
        layout.addWidget(self.bar)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(lambda: self.refresh() if self.isVisible() else None)
        self.timer.start()
        self.refresh()

    def refresh(self):
        self.state = snapshot()
        requested = int(self.allocation() or 0)
        self.peak = history_peak(self.history_dir) if self.history_dir else 0
        mods = enabled_mod_count(self.history_dir) if self.history_dir else 0
        if requested > 0:
            self.amount, self.basis = requested, t('手动设置的堆上限')
        else:
            total, available = self.state if self.state else (None, None)
            budget = automatic_budget(total, available, self.peak, mods)
            self.amount, self.basis = budget['gb'], budget['basis']
            if total is None or available is None:
                self.basis = t('无法读取系统内存，保守分配')
            elif self.peak:
                self.basis = t('按历史峰值 {peak} GB 留出余量').format(peak=f'{self.peak / GIB:.1f}')
            else:
                self.basis = t('暂无历史，按 {mods} 个 Mod 估算（每 25 个 Mod 约 1 GB）').format(mods=mods)
            if budget.get('aggressive'):
                self.basis += t('；内存紧张的大整合包模式，保留物理内存 7%')
        try:
            model, game = process_usage(self.history_dir)
        except Exception:
            model, game = None, None
        if self.state:
            total, available = self.state
            self.segments = memory_segments(total, available, model, game, self.amount*GIB)
            system, local, planned, remaining = self.segments
            for (chip, name), amount in zip(self.legend_labels, (system, local, planned)):
                chip.setText(f'■  {name} {amount/GIB:.1f} GB')
            text = t('预计剩余 {remaining} GB / 总计 {total} GB').format(remaining=f'{remaining/GIB:.1f}', total=f'{total/GIB:.1f}')
            excess = sum(self.segments[:3]) - total
            if excess > 0:
                text += '\n' + t('预算超出物理内存 {excess} GB（条形已截断）').format(excess=f'{excess/GIB:.1f}')
        else:
            text = t('暂时无法读取系统内存')
        text += '\n' + t('MC 堆上限 {amount} GB').format(amount=self.amount) + (t('（自动估算，启动时重新计算）') if requested == 0 else t('（手动）'))
        text += f'\n{self.basis}'
        if self.history_dir:
            text += '\n' + (t('实例历史采样峰值 {peak} GB').format(peak=f'{self.peak/GIB:.1f}') if self.peak else t('实例历史峰值：暂无记录，启动游戏后采样'))
        self.setToolTip(t('MC 段为分配预算与当前实测占用的较大值，不是已预留内存；堆外开销仍需留余量。\n本地模型仅统计启动器启动的模型进程，不含显存；外部模型归入其他应用。\n琥珀色区域已扣除单独统计的模型与游戏进程，RSS 分类是近似值。'))
        if model is None or game is None:
            text += '\n' + t('部分进程占用暂未读到，未识别部分保留在系统及其他应用中。')
        if self.state and self.amount * GIB + GIB > self.state[1]:
            text += '\n' + t('内存有点紧，建议先关闭不用的软件；分配上限不代表一定能运行。')
        self.label.setText(text)
        self.bar.setAccessibleName(text)
        self.bar.update()

    def paint_bar(self, event):
        painter = QPainter(self.bar)
        rect = self.bar.rect().adjusted(0, 5, -1, -5)
        painter.fillRect(rect, self.palette().alternateBase())
        if self.state and self.state[0] > 0:
            total, available = self.state
            offset = 0
            for amount, color in zip(self.segments[:3], (QColor('#d79b45'), QColor('#9b72cf'), QColor('#42a5c6'))):
                start = int(min(1, offset/total)*rect.width())
                offset += amount
                end = int(min(1, offset/total)*rect.width())
                painter.fillRect(start, rect.top(), max(0, end-start), rect.height(), color)
        painter.end()
