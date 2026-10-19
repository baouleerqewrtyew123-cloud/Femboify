"""
БЛОК 10 — ГРАФИЧЕСКИЙ ИНТЕРФЕЙС С КОТИКОМ (arch_gui.py)
Запуск: sudo python3 Arch.py --gui
Установка идёт в отдельном потоке. Окно только показывает состояние и отвечает на вопросы.
"""

import logging
import re
import sys
import threading
import time

try:
    from PySide6.QtCore import QObject, QPropertyAnimation, Qt, QTimer, QUrl, Signal
    from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter
    from PySide6.QtWidgets import (
        QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QInputDialog,
        QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
        QPlainTextEdit, QProgressBar, QPushButton, QToolButton, QVBoxLayout, QWidget,
    )
except ImportError:
    sys.exit("PySide6 не найден. Установите: sudo pacman -S pyside6")

C = {
    "base": "#1e1e2e", "mantle": "#181825", "crust": "#11111b",
    "surface0": "#313244", "surface1": "#45475a", "overlay0": "#6c7086",
    "text": "#cdd6f4", "subtext0": "#a6adc8", "flamingo": "#f2cdcd",
    "pink": "#f5c2e7", "rosewater": "#f5e0dc", "green": "#a6e3a1",
    "red": "#f38ba8", "peach": "#fab387",
}

STYLE = f"""
QWidget#root {{ background: {C['base']}; }}
QLabel {{ color: {C['text']}; font-size: 13px; }}
QLabel#title {{ font-size: 28px; font-weight: bold; color: {C['flamingo']}; }}
QLabel#subtitle {{ color: {C['subtext0']}; font-size: 12px; }}
QLabel#stageTitle {{ font-size: 19px; font-weight: bold; }}
QLabel#desc {{ color: {C['subtext0']}; }}
QLabel#percent {{ font-size: 34px; font-weight: bold; color: {C['pink']}; }}
QLabel#caption {{ color: {C['overlay0']}; font-size: 12px; }}
QFrame#card {{ background: {C['mantle']}; border-radius: 16px; }}
QFrame#result {{ background: {C['surface0']}; border-radius: 12px; }}
QPushButton {{ background: {C['surface0']}; color: {C['text']}; border: none;
    border-radius: 10px; padding: 10px 18px; font-size: 13px; }}
QPushButton:hover {{ background: {C['surface1']}; }}
QPushButton:disabled {{ color: {C['overlay0']}; background: {C['mantle']}; }}
QPushButton#primary {{ background: {C['flamingo']}; color: {C['crust']}; font-weight: bold; }}
QPushButton#primary:hover {{ background: {C['rosewater']}; }}
QPushButton#primary:disabled {{ background: {C['surface0']}; color: {C['overlay0']}; }}
QPushButton#danger:hover {{ background: {C['red']}; color: {C['crust']}; }}
QToolButton {{ background: transparent; color: {C['subtext0']}; border: none; padding: 4px; }}
QProgressBar {{ background: {C['surface0']}; border: none; border-radius: 7px; height: 14px; }}
QProgressBar::chunk {{ background: {C['flamingo']}; border-radius: 7px; }}
QListWidget {{ background: {C['crust']}; color: {C['subtext0']}; border: none;
    border-radius: 10px; padding: 8px; font-size: 13px; }}
QPlainTextEdit {{ background: {C['crust']}; color: {C['subtext0']}; border: 1px solid {C['surface0']};
    border-radius: 8px; font-family: monospace; font-size: 12px; padding: 8px; }}
"""

CAPTIONS = {
    "idle": "Котик спокоен",
    "curious": "Котик наблюдает за установкой",
    "happy": "Котик доволен!",
    "sad": "Котик грустит: что-то пошло не так",
    "sleepy": "Котик ждёт, это может занять время",
    "question": "Котик ждёт ваш ответ",
}

# ---------- БЛОК 10.1 — КОТИК ----------

GRID_W, GRID_H = 16, 16
PALETTE = {"O": "#11111b", "E": "#11111b", "B": "#f5e0dc", "F": "#f2cdcd",
           "K": "#f5c2e7", "T": "#89b4fa"}
SPRITE = [
    "....OO....OO....",
    "...OFFO..OFFO...",
    "..OBBBBBBBBBBO..",
    ".OBBBBBBBBBBBBO.",
    ".OBBEBBBBBBEBBO.",
    ".OBBEBBBBBBEBBO.",
    ".OBBBBBKKBBBBBO.",
    ".OBBBBBBBBBBBBO.",
    "..OBBBBBBBBBBO..",
    "...OBBBBBBBBO...",
    "...OBBFFFFBBO...",
    "..OBBFFFFFFBBO..",
    "..OBFFFFFFFFBO..",
    ".OBBBFFFFFFBBBO.",
    "..OOOOOOOOOOOO..",
    "................",
]
TAIL_UP = [(15, 13), (15, 12), (15, 11), (15, 10)]
TAIL_DOWN = [(14, 14), (15, 14), (15, 13)]


def build_frame(mood, blink, tick):
    grid = [list(row.ljust(GRID_W, ".")) for row in SPRITE]
    if blink or mood in ("happy", "sleepy"):
        for x in (4, 11):
            grid[4][x] = "B"
            grid[5][x] = "O"
    if mood == "happy":
        grid[6][2] = "K"
        grid[6][13] = "K"
    if mood == "sad":
        grid[7][4] = "T"
    period = 2 if mood in ("curious", "question") else 5
    tail_up = (tick // period) % 2 == 0
    if mood == "happy":
        tail_up = True
    if mood in ("sad", "sleepy"):
        tail_up = False
    for x, y in (TAIL_UP if tail_up else TAIL_DOWN):
        grid[y][x] = "F"
    return grid


class PixelCat(QWidget):
    """Котик, нарисованный кодом. Моргает, машет хвостом, меняет выражение по настроению."""

    def __init__(self):
        super().__init__()
        self.mood = "idle"
        self._tick = 0
        self._blink = 0
        self.setMinimumSize(220, 220)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(120)

    def set_mood(self, mood):
        self.mood = mood
        self.update()

    def _step(self):
        self._tick += 1
        if self._blink > 0:
            self._blink -= 1
        elif self._tick % 33 == 0:
            self._blink = 2
        self.update()

    def paintEvent(self, _event):
        grid = build_frame(self.mood, self._blink > 0, self._tick)
        cell = max(1, min(self.width() // GRID_W, (self.height() - 30) // GRID_H))
        x0 = (self.width() - cell * GRID_W) // 2
        bob = cell // 3 if self.mood == "happy" and (self._tick // 3) % 2 else 0
        y0 = (self.height() - cell * GRID_H) // 2 - bob
        p = QPainter(self)
        for y, row in enumerate(grid):
            for x, ch in enumerate(row):
                if ch != ".":
                    p.fillRect(x0 + x * cell, y0 + y * cell, cell, cell, QColor(PALETTE[ch]))
        if self.mood == "sleepy":
            font = p.font()
            font.setPointSize(max(10, cell + 4))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(C["subtext0"]))
            p.drawText(x0 + GRID_W * cell - cell, y0 + cell * 2, "z")
        p.end()


# ---------- БЛОК 10.2 — СВЯЗЬ ПОТОКА И ОКНА ----------

class Bridge(QObject):
    """Сигналы из рабочего потока в окно. Окно живёт в главном потоке, поэтому всё безопасно."""

    log_line = Signal(str)
    stage_event = Signal(str, int, str)
    question = Signal(str)
    finished = Signal(object)


class QtLogHandler(logging.Handler):
    """Отправляет строки журнала в окно (только кратко, полный журнал в файле)."""

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.setLevel(logging.INFO)
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            self.bridge.log_line.emit(self.format(record))
        except Exception:
            self.handleError(record)


# ---------- БЛОК 10.3 — ОКНО УСТАНОВЩИКА ----------

class InstallerWindow(QMainWindow):
    def __init__(self, core, stages, runner, log_path):
        super().__init__()
        self.core = core
        self.stages = stages
        self.runner = runner
        self.log_path = log_path
        self.total = len(stages)
        self.done_count = 0
        self.running = False
        self.thread = None
        self.mood = "idle"
        self._answer = None
        self._answer_event = threading.Event()
        self._last_output = time.monotonic()
        self.item_for_stage = {}

        self.bridge = Bridge()
        self.bridge.log_line.connect(self._append_log)
        self.bridge.stage_event.connect(self._on_stage_event)
        self.bridge.question.connect(self._on_question)
        self.bridge.finished.connect(self._on_finished)
        core.log.addHandler(QtLogHandler(self.bridge))
        core.PROMPTER = self.gui_prompt
        core.INTERACTIVE_ANSWER = self.gui_prompt

        self.setWindowTitle("Arch Setup")
        self.resize(1100, 740)
        self.setMinimumSize(900, 640)
        self._build_ui()
        self._sleep_timer = QTimer(self)
        self._sleep_timer.timeout.connect(self._check_sleepy)
        self._sleep_timer.start(5000)
        self._set_buttons()

    # ----- Интерфейс -----

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(14)

        title = QLabel("Arch Setup")
        title.setObjectName("title")
        subtitle = QLabel(f"Arch Linux · KDE Plasma Wayland · {self.core.PROGRAM_VERSION}")
        subtitle.setObjectName("subtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        middle = QHBoxLayout()
        middle.setSpacing(20)

        cat_card = QFrame()
        cat_card.setObjectName("card")
        cat_layout = QVBoxLayout(cat_card)
        cat_layout.setContentsMargins(18, 18, 18, 14)
        self.cat = PixelCat()
        cat_layout.addWidget(self.cat, 1)
        self.cat_caption = QLabel(CAPTIONS["idle"])
        self.cat_caption.setObjectName("caption")
        self.cat_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cat_layout.addWidget(self.cat_caption)
        middle.addWidget(cat_card, 4)

        info_card = QFrame()
        info_card.setObjectName("card")
        info = QVBoxLayout(info_card)
        info.setContentsMargins(24, 22, 24, 22)
        info.setSpacing(10)
        self.stage_title = QLabel("Готово к запуску")
        self.stage_title.setObjectName("stageTitle")
        self.stage_desc = QLabel("Нажмите «Начать». Вопросы установщика появятся в отдельных окнах.")
        self.stage_desc.setObjectName("desc")
        self.stage_desc.setWordWrap(True)
        info.addWidget(self.stage_title)
        info.addWidget(self.stage_desc)

        row = QHBoxLayout()
        self.percent = QLabel("0%")
        self.percent.setObjectName("percent")
        self.counter = QLabel(f"Выполнено этапов: 0 из {self.total}")
        self.counter.setObjectName("desc")
        row.addWidget(self.percent)
        row.addStretch(1)
        row.addWidget(self.counter)
        info.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, self.total)
        self.progress.setValue(0)
        info.addWidget(self.progress)

        self.stage_list = QListWidget()
        self.stage_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stage_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._fill_stage_list()
        info.addWidget(self.stage_list, 1)

        self.result_card = QFrame()
        self.result_card.setObjectName("result")
        rl = QVBoxLayout(self.result_card)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        rl.addWidget(self.result_label)
        self.result_fx = QGraphicsOpacityEffect(self.result_card)
        self.result_card.setGraphicsEffect(self.result_fx)
        self.result_card.hide()
        info.addWidget(self.result_card)

        middle.addWidget(info_card, 6)
        outer.addLayout(middle, 1)

        self.console_btn = QToolButton()
        self.console_btn.setText("▸ Подробный вывод")
        self.console_btn.setCheckable(True)
        self.console_btn.toggled.connect(self._toggle_console)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(200)
        self.console.hide()
        outer.addWidget(self.console_btn)
        outer.addWidget(self.console)

        bottom = QHBoxLayout()
        self.log_btn = QPushButton("Открыть лог")
        self.log_btn.clicked.connect(self._open_log)
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.clicked.connect(self._cancel_clicked)
        self.start_btn = QPushButton("Начать")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._start_clicked)
        bottom.addWidget(self.log_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.start_btn)
        outer.addLayout(bottom)

    def _fill_stage_list(self):
        last_block = None
        for i, (block, title, _func) in enumerate(self.stages):
            if block != last_block:
                head = QListWidgetItem(block)
                head.setFlags(Qt.ItemFlag.ItemIsEnabled)
                head.setForeground(QColor(C["flamingo"]))
                font = QFont()
                font.setBold(True)
                head.setFont(font)
                self.stage_list.addItem(head)
                last_block = block
            item = QListWidgetItem(f"○  {title}")
            item.setForeground(QColor(C["overlay0"]))
            self.stage_list.addItem(item)
            self.item_for_stage[i] = item

    def _set_item(self, index, mark, color, bold=False):
        item = self.item_for_stage.get(index)
        if item is None:
            return
        title = self.stages[index][1]
        item.setText(f"{mark}  {title}")
        item.setForeground(QColor(color))
        font = item.font()
        font.setBold(bold)
        item.setFont(font)
        self.stage_list.scrollToItem(item)

    def _set_mood(self, mood):
        self.mood = mood
        self.cat.set_mood(mood)
        self.cat_caption.setText(CAPTIONS[mood])

    def _mood_if_running(self, mood):
        if self.running:
            self._set_mood(mood)

    def _set_buttons(self):
        self.start_btn.setEnabled(not self.running)
        self.cancel_btn.setEnabled(self.running)

    def _toggle_console(self, checked):
        self.console.setVisible(checked)
        self.console_btn.setText("▾ Скрыть вывод" if checked else "▸ Подробный вывод")

    def _show_result(self, text, color):
        self.result_label.setText(text)
        self.result_label.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")
        self.result_card.show()
        self._fade = QPropertyAnimation(self.result_fx, b"opacity", self)
        self._fade.setDuration(500)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _reset_ui(self):
        self.console.clear()
        self.result_card.hide()
        self.done_count = 0
        self.progress.setRange(0, self.total)
        self.progress.setValue(0)
        self.percent.setText("0%")
        self.counter.setText(f"Выполнено этапов: 0 из {self.total}")
        for i in range(self.total):
            self._set_item(i, "○", C["overlay0"])
        self.stage_title.setText("Запуск…")
        self.stage_desc.setText("Подготовка установки")

    # ----- Нажатия кнопок -----

    def _start_clicked(self):
        if self.running:
            return
        reply = QMessageBox.question(
            self, "Начать установку",
            "Начать установку?\n\nВопросы установщика и программ будут появляться в отдельных окнах. "
            "Пароль sudo, если его спросит makepkg, вводится в окне программы.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._reset_ui()
        self.core.CANCEL_EVENT.clear()
        self.running = True
        self._last_output = time.monotonic()
        self._set_buttons()
        self._set_mood("curious")
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _cancel_clicked(self):
        if not self.running:
            return
        reply = QMessageBox.question(
            self, "Отмена",
            "Остановить установку?\nТекущая команда будет прервана вместе с дочерними процессами.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._request_cancel()

    def _request_cancel(self):
        self.core.CANCEL_EVENT.set()
        self._answer = None
        self._answer_event.set()
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Останавливаем…")

    def _open_log(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.log_path))

    def closeEvent(self, event):
        if self.running:
            reply = QMessageBox.question(
                self, "Выход",
                "Установка ещё идёт. Остановить её и закрыть окно?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._request_cancel()
            if self.thread is not None:
                self.thread.join(timeout=10)
        event.accept()

    # ----- Рабочий поток -----

    def _worker(self):
        result = self.runner(self.stages, self.log_path, self._emit_event)
        self.bridge.finished.emit(result)

    def _emit_event(self, kind, index, title):
        self.bridge.stage_event.emit(kind, index, title)

    def gui_prompt(self, text):
        """Вызывается из рабочего потока. Ждёт ответа пользователя из окна. None = отмена."""
        if self.core.CANCEL_EVENT.is_set():
            return None
        self._answer = None
        self._answer_event.clear()
        self.bridge.question.emit(text)
        self._answer_event.wait()
        if self.core.CANCEL_EVENT.is_set():
            return None
        return self._answer if self._answer is not None else ""

    # ----- Обработка событий (главный поток) -----

    def _append_log(self, text):
        self.console.appendPlainText(text)
        self._last_output = time.monotonic()
        if self.mood == "sleepy":
            self._set_mood("curious")

    def _on_stage_event(self, kind, index, title):
        if kind == "start":
            self.stage_title.setText(f"Этап {index + 1} из {self.total}")
            self.stage_desc.setText(title)
            self.progress.setRange(0, 0)  # неопределённый режим: честно, без выдуманных процентов
            self._set_item(index, "●", C["flamingo"], bold=True)
            self._set_mood("curious")
        elif kind in ("done", "skip"):
            self.done_count = index + 1
            self.progress.setRange(0, self.total)
            self.progress.setValue(self.done_count)
            self.percent.setText(f"{round(self.done_count / self.total * 100)}%")
            self.counter.setText(f"Выполнено этапов: {self.done_count} из {self.total}")
            if kind == "done":
                self._set_item(index, "✓", C["green"])
                self._set_mood("happy")
                QTimer.singleShot(2500, lambda: self._mood_if_running("curious"))
            else:
                self._set_item(index, "·", C["subtext0"])
                self._set_mood("idle")
                QTimer.singleShot(2500, lambda: self._mood_if_running("curious"))
        elif kind == "fail":
            self._set_item(index, "✗", C["red"], bold=True)
            self._set_mood("sad")
        elif kind == "cancel":
            self._set_item(index, "–", C["peach"])

    def _on_question(self, text):
        self._set_mood("question")
        if re.search(r"\[[yYnN]/[yYnN]\]", text):
            default = (QMessageBox.StandardButton.No if "[y/N]" in text
                       else QMessageBox.StandardButton.Yes)
            reply = QMessageBox.question(
                self, "Вопрос установщика", text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, default,
            )
            answer = "y" if reply == QMessageBox.StandardButton.Yes else "n"
        elif "password" in text.lower() or "пароль" in text.lower():
            value, ok = QInputDialog.getText(
                self, "Пароль", text, QLineEdit.EchoMode.Password)
            answer = value if ok else ""
        else:
            value, ok = QInputDialog.getText(self, "Ответ установщика", text)
            answer = value if ok else ""
        self._answer = answer
        self._answer_event.set()
        if self.running and not self.core.CANCEL_EVENT.is_set():
            self._set_mood("curious")

    def _check_sleepy(self):
        if self.running and self.mood == "curious" and time.monotonic() - self._last_output > 45:
            self._set_mood("sleepy")

    def _on_finished(self, result):
        self.running = False
        self.thread = None
        self.cancel_btn.setText("Отмена")
        self._set_buttons()
        code = result["code"]
        self.progress.setRange(0, self.total)
        if code == 0:
            self.progress.setValue(self.total)
            self.percent.setText("100%")
            self.stage_title.setText("Готово!")
            self.stage_desc.setText("Все этапы выполнены.")
            self._set_mood("happy")
            self._show_result(
                f"✓ Всё готово! Котик доволен.\n\nЖурнал: {self.log_path}", C["green"])
        elif code == 2:
            self.stage_title.setText("Готово с пропусками")
            self.stage_desc.setText("Часть пунктов не выполнена. Подробности в отчёте на рабочем столе.")
            self._set_mood("idle")
            lines = [f"  - {name}: {reason}" for name, reason in self.core.SKIPPED[:6]]
            more = len(self.core.SKIPPED) - len(lines)
            if more > 0:
                lines.append(f"  … и ещё {more}")
            self._show_result(
                "Пропущено или не выполнено:\n" + "\n".join(lines) + f"\n\nЖурнал: {self.log_path}",
                C["peach"])
        elif code == 130:
            self.stage_title.setText("Установка отменена")
            self.stage_desc.setText("Уже выполненные шаги сохранены. Повторный запуск продолжит с места остановки.")
            self._set_mood("idle")
            self._show_result(f"Установка отменена пользователем.\n\nЖурнал: {self.log_path}", C["peach"])
        else:
            self.stage_title.setText("Установка остановлена с ошибкой")
            self.stage_desc.setText(f"Блок: {result['block']}\nЭтап: {result['stage']}")
            self._set_mood("sad")
            self._show_result(
                f"✗ {result['message']}\n\n"
                f"Что делать: {result['advice']}\n\n"
                f"Блок: {result['block']}\nЭтап: {result['stage']}\n"
                f"Полный журнал с командами и выводом: {result['log_path']}",
                C["red"])
            self.log_btn.setEnabled(True)


# ---------- БЛОК 10.4 — ЗАПУСК ОКНА ----------

def run(core, stages, runner):
    """Открывает окно. runner(stages, log_path, on_event) выполняет этапы и возвращает результат."""
    try:
        log_path = core.setup_logging()
    except OSError as e:
        print(f"ОШИБКА: не удалось создать лог-файл: {e}")
        return 1
    core.log.info("=== Новый запуск (окно) ===")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = InstallerWindow(core, stages, runner, log_path)
    window.show()
    return app.exec()