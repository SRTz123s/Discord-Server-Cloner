import os
import sys
import json
import asyncio

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame

from qfluentwidgets import (
    FluentWindow,
    NavigationItemPosition,
    FluentIcon as FIC,
    setTheme,
    Theme,
    setThemeColor,
    SubtitleLabel,
    StrongBodyLabel,
    BodyLabel,
    CaptionLabel,
    LineEdit,
    PasswordLineEdit,
    CheckBox,
    PrimaryPushButton,
    PushButton,
    TextBrowser,
    SimpleCardWidget,
    SettingCardGroup,
    SettingCard,
    HyperlinkCard,
    SwitchButton,
    ComboBox,
    ColorPickerButton,
    FluentStyleSheet,
)
import qfluentwidgets

# --- backend (discord.py 1.7.3, user token) ---
import discord
from discord import Client, Intents

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.cloner import Cloner, set_log_callback, logs_enabled
import utils.cloner as cloner_module

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "utils", "config.json")

BLURPLE = QColor(88, 101, 242)        # #5865F2
BLURPLE_DARK = QColor(30, 31, 34)     # #1e1f22
BLURPLE_DARKER = QColor(24, 25, 28)
GREEN = "#3ba55d"
RED = "#ed4245"
YELLOW = "#faa61a"
GREY = "#d4d7dc"


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {
            "token": False,
            "prefix": "!",
            "logs": True,
            "copy_settings": {
                "categories": True,
                "channels": True,
                "roles": True,
                "permissions": True,
                "emojis": True,
            },
        }
    data.setdefault("copy_settings", {})
    for k in ("categories", "channels", "roles", "permissions", "emojis"):
        data["copy_settings"].setdefault(k, True)
    return data


def save_config(data):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


class CloneWorker(QThread):
    log_signal = pyqtSignal(str, str)
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, token, src, tgt, copy_settings, logs_enabled):
        super().__init__()
        self.token = token
        self.src = src
        self.tgt = tgt
        self.copy_settings = copy_settings
        self.logs_enabled = logs_enabled

    def _on_log(self, line, ltype):
        self.log_signal.emit(line, ltype)

    def run(self):
        set_log_callback(self._on_log)
        cloner_module.logs_enabled = self.logs_enabled
        # discord.py 1.7.3 calls asyncio.get_event_loop() in this thread;
        # on Python 3.12 a fresh thread has none, so create/set one first.
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        try:
            client = Client(intents=Intents.all())

            @client.event
            async def on_ready():
                self.status_signal.emit(f"Статус: {client.user}")
                self._on_log(f"Авторизован как {client.user}", "add")
                try:
                    await self._do_clone(client)
                except Exception as e:
                    self._on_log(f"Ошибка клонирования: {e}", "error")
                self._on_log("Клонирование завершено.", "add")
                self.status_signal.emit("Статус: Завершено")
                await client.close()

            client.run(self.token, bot=False)
        except discord.errors.LoginFailure:
            self._on_log("Неверный токен. Авторизация не удалась.", "error")
            self.status_signal.emit("Статус: Ошибка авторизации")
        except Exception as e:
            self._on_log(f"Ошибка запуска: {e}", "error")
            self.status_signal.emit("Статус: Ошибка")
        self.finished_signal.emit()

    async def _do_clone(self, client):
        import time
        start = time.time()
        try:
            guild_from = client.get_guild(int(self.src))
        except Exception:
            guild_from = None
        try:
            guild_to = client.get_guild(int(self.tgt))
        except Exception:
            guild_to = None

        if guild_from is None:
            self._on_log(
                f"Не найден исходный сервер (ID {self.src}). Вы должны состоять в нём.",
                "error")
            return
        if guild_to is None:
            self._on_log(f"Не найден целевой сервер (ID {self.tgt}).", "error")
            return

        if not any(self.copy_settings.get(k, False) for k in
                   ("categories", "channels", "roles", "emojis")):
            self._on_log("Ничего не выбрано для копирования (только название/иконка).",
                         "warning")

        await Cloner.guild_create(guild_to, guild_from)
        await Cloner.channels_delete(guild_to)
        if self.copy_settings.get("roles"):
            await Cloner.roles_create(guild_to, guild_from)
        if self.copy_settings.get("categories"):
            await Cloner.categories_create(guild_to, guild_from)
        if self.copy_settings.get("channels"):
            await Cloner.channels_create(guild_to, guild_from)
        if self.copy_settings.get("emojis"):
            await Cloner.emojis_create(guild_to, guild_from)

        self._on_log(
            f"Сервер склонирован за {round(time.time() - start, 2)} сек.", "add")


class ClonerPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.running = False
        self.config_data = load_config()
        self._build()

    # ------------------------------------------------------------------
    def _card(self, title=None):
        card = SimpleCardWidget(self)
        card.setContentsMargins(18, 18, 18, 18)
        layout = QVBoxLayout(card)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)
        if title:
            layout.addWidget(StrongBodyLabel(title))
        card._vlayout = layout
        return card

    def _field(self, card, label, placeholder, password=False, default=""):
        box = QVBoxLayout()
        box.setSpacing(4)
        lab = CaptionLabel(label)
        lab.setTextColor(QColor(181, 186, 193), QColor(181, 186, 193))
        box.addWidget(lab)
        if password:
            entry = PasswordLineEdit()
        else:
            entry = LineEdit()
        entry.setPlaceholderText(placeholder)
        entry.setMinimumHeight(36)
        if default:
            entry.setText(default)
        box.addWidget(entry)
        card._vlayout.addLayout(box)
        return entry

    def _build(self):
        scroll = qfluentwidgets.ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)
        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # Title
        title = SubtitleLabel("Discord Server Cloner")
        title.setObjectName("clonerTitle")
        root.addWidget(title)
        root.addWidget(BodyLabel(
            "Склонируйте структуру одного сервера Discord на другой через user-токен."))

        # Inputs card
        in_card = self._card("Данные подключения")
        self.token_entry = self._field(
            in_card, "Discord Token (user-аккаунт)", "Вставьте ваш токен",
            password=True,
            default=self.config_data.get("token")
            if isinstance(self.config_data.get("token"), str) else "")
        self.src_entry = self._field(
            in_card, "ID сервера-источника (копировать ИЗ)",
            "Например: 123456789012345678")
        self.tgt_entry = self._field(
            in_card, "ID целевого сервера (куда клонировать)",
            "Например: 987654321098765432")
        hint = BodyLabel(
            "Discord убрал возможность создавать серверы через бота.\n"
            "Создайте пустой сервер вручную и введите его ID как целевой.")
        hint.setTextColor(QColor(181, 186, 193), QColor(181, 186, 193))
        in_card._vlayout.addWidget(hint)
        root.addWidget(in_card)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.start_btn = PrimaryPushButton("▶  Начать клонирование")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.clicked.connect(self.start_clone)
        self.clear_btn = PushButton("Очистить логи")
        self.clear_btn.setMinimumHeight(42)
        self.clear_btn.clicked.connect(self.clear_logs)
        btn_row.addWidget(self.start_btn, stretch=1)
        btn_row.addWidget(self.clear_btn)
        root.addLayout(btn_row)

        # Log card
        log_card = self._card("Лог")
        self.log_box = TextBrowser()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(220)
        self.log_box.setStyleSheet(
            "QTextBrowser{background-color:#111214;color:#d4d7dc;"
            "border-radius:8px;padding:8px;}")
        log_card._vlayout.addWidget(self.log_box)
        root.addWidget(log_card)
        root.addStretch(1)

    # ------------------------------------------------------------------
    def _append_log(self, line, ltype):
        color = {"add": GREEN, "delete": GREEN, "error": RED,
                 "warning": YELLOW}.get(ltype, GREY)
        self.log_box.append(f'<span style="color:{color}">{line}</span>')
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_logs(self):
        self.log_box.clear()

    def start_clone(self):
        if self.running:
            return
        token = self.token_entry.text().strip()
        src = self.src_entry.text().strip()
        tgt = self.tgt_entry.text().strip()
        if not token:
            self._append_log("Введите Discord Token.", "error")
            return
        if not src or not tgt:
            self._append_log("Введите ID исходного и целевого серверов.", "error")
            return

        copy_settings = load_config().get("copy_settings", {})
        self.config_data["token"] = token
        self.config_data["logs"] = True
        save_config(self.config_data)

        self.running = True
        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳  Клонирование...")
        self._append_log("Запуск клонера...", "info")

        self.worker = CloneWorker(token, src, tgt, copy_settings, True)
        self.worker.log_signal.connect(self._append_log)
        self.worker.status_signal.connect(self._set_status)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()

    def _set_status(self, text):
        w = self.window()
        if hasattr(w, "set_status"):
            w.set_status(text)

    def _on_finished(self):
        self.running = False
        self.start_btn.setEnabled(True)
        self.start_btn.setText("▶  Начать клонирование")


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_data = load_config()
        _, self._accent_hex, _ = _load_appearance()

        scroll = qfluentwidgets.ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)
        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        root.addWidget(SubtitleLabel("Настройки"))
        root.addWidget(BodyLabel(
            "Храните токен в программе, чтобы не вводить его каждый раз. "
            "Настройки сохраняются автоматически в utils/config.json."))

        # --- Account ---
        acc_group = SettingCardGroup("Аккаунт", self)
        self.token_card = SettingCard(
            FIC.PEOPLE, "Discord Token",
            "Сохраняется локально на этом компьютере в config.json")
        token_row = QHBoxLayout()
        token_row.setContentsMargins(0, 0, 0, 0)
        token_row.setSpacing(10)
        self.token_edit = PasswordLineEdit()
        self.token_edit.setPlaceholderText("Вставьте user-токен Discord")
        self.token_edit.setMinimumHeight(34)
        if isinstance(self.config_data.get("token"), str):
            self.token_edit.setText(self.config_data["token"])
        token_save = PushButton("Сохранить")
        token_save.setMinimumHeight(34)
        token_save.clicked.connect(self._save_token)
        token_row.addWidget(self.token_edit, stretch=1)
        token_row.addWidget(token_save)
        self.token_card.hBoxLayout.addLayout(token_row)
        self.token_card.hBoxLayout.addStretch(1)
        acc_group.addSettingCard(self.token_card)
        root.addWidget(acc_group)

        # --- Cloner options ---
        clone_group = SettingCardGroup("Настройки клонирования", self)
        cs = self.config_data.get("copy_settings", {})
        self.clone_switches = {}
        opts = [
            ("categories", "Категории", FIC.COPY),
            ("channels", "Каналы", FIC.SEND),
            ("roles", "Роли", FIC.PEOPLE),
            ("permissions", "Права", FIC.CERTIFICATE),
            ("emojis", "Эмодзи", FIC.HEART),
        ]
        for key, label, icon in opts:
            card = SettingCard(icon, label, "Копировать при клонировании")
            btn = SwitchButton()
            btn.setChecked(cs.get(key, True))
            btn.checkedChanged.connect(
                lambda c, k=key: self._on_clone_toggle(k, c))
            card.hBoxLayout.addWidget(btn)
            card.hBoxLayout.addStretch(1)
            self.clone_switches[key] = btn
            clone_group.addSettingCard(card)
        root.addWidget(clone_group)

        # --- Appearance (like ZapretGUI) ---
        app_group = SettingCardGroup("Внешний вид", self)

        theme_card = SettingCard(
            FIC.BRUSH, "Тема оформления", "Тёмная / светлая / авто")
        theme_combo = ComboBox()
        theme_combo.addItems(["Тёмная", "Светлая", "Как в системе"])
        theme_combo.setCurrentIndex(self._current_theme_index())
        theme_combo.currentTextChanged.connect(self._on_theme)
        theme_card.hBoxLayout.addWidget(theme_combo)
        theme_card.hBoxLayout.addStretch(1)
        app_group.addSettingCard(theme_card)

        color_card = SettingCard(
            FIC.PALETTE, "Цвет акцента",
            "Цвет кнопок, переключателей и индикаторов")
        try:
            initial_color = QColor(self._accent_hex)
        except Exception:
            initial_color = BLURPLE
        accent_btn = ColorPickerButton(initial_color, "Выбрать")
        accent_btn.colorChanged.connect(self._on_accent)
        color_card.hBoxLayout.addWidget(accent_btn)
        color_card.hBoxLayout.addStretch(1)
        app_group.addSettingCard(color_card)

        mica_card = SettingCard(
            FIC.APPLICATION, "Эффект Mica",
            "Полупрозрачный фон в стиле Windows 11")
        mica_btn = SwitchButton()
        mica_btn.setChecked(
            self.window().isMicaEffectEnabled()
            if hasattr(self.window(), "isMicaEffectEnabled") else True)
        mica_btn.checkedChanged.connect(self._on_mica)
        mica_card.hBoxLayout.addWidget(mica_btn)
        mica_card.hBoxLayout.addStretch(1)
        app_group.addSettingCard(mica_card)

        root.addWidget(app_group)
        root.addStretch(1)

    # ------------------------------------------------------------------
    def _current_theme_index(self):
        try:
            from qfluentwidgets import qconfig
            theme = qconfig.theme
            return {Theme.DARK: 0, Theme.LIGHT: 1, Theme.AUTO: 2}.get(theme, 0)
        except Exception:
            return 0

    def _save_token(self):
        token = self.token_edit.text().strip()
        self.config_data["token"] = token
        save_config(self.config_data)
        w = self.window()
        if hasattr(w, "cloner_page"):
            w.cloner_page.token_entry.setText(token)
        self.save_info("Токен сохранён в программе.")

    def save_info(self, msg):
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.success(title="Сохранено", content=msg,
                        parent=self.window(),
                        position=InfoBarPosition.TOP_RIGHT, duration=2000)

    def _on_clone_toggle(self, key, checked):
        self.config_data.setdefault("copy_settings", {})
        self.config_data["copy_settings"][key] = bool(checked)
        save_config(self.config_data)

    def _on_theme(self, text):
        mapping = {"Тёмная": Theme.DARK, "Светлая": Theme.LIGHT,
                   "Как в системе": Theme.AUTO}
        setTheme(mapping.get(text, Theme.DARK))
        _persist_appearance(theme=text)

    def _on_accent(self, color):
        setThemeColor(color)
        _persist_appearance(accent=color.name())

    def _on_mica(self, checked):
        w = self.window()
        if hasattr(w, "setMicaEffectEnabled"):
            w.setMicaEffectEnabled(checked)
        _persist_appearance(mica=bool(checked))


def _persist_appearance(**kw):
    data = load_config()
    data.setdefault("appearance", {})
    data["appearance"].update(kw)
    save_config(data)


def _load_appearance():
    data = load_config().get("appearance", {})
    theme_text = data.get("theme", "Тёмная")
    accent = data.get("accent", "#5865F2")
    mica = data.get("mica", True)
    return theme_text, accent, mica


class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        scroll = qfluentwidgets.ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)
        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        root.addWidget(SubtitleLabel("О программе"))
        card = SimpleCardWidget(self)
        card.setContentsMargins(18, 18, 18, 18)
        v = QVBoxLayout(card)
        v.setSpacing(10)
        v.addWidget(StrongBodyLabel("Discord Server Cloner"))
        v.addWidget(BodyLabel(
            "Утилита для копирования структуры сервера Discord\n"
            "(каналы, категории, роли, права, эмодзи) с одного сервера на другой.\n\n"
            "Интерфейс выполнен в стиле ZapretGUI (Fluent UI / qfluentwidgets).\n"
            "Для работы требуется user-токен Discord и права управления на целевом сервере."))
        root.addWidget(card)
        root.addStretch(1)


class SupportPage(QWidget):
    LINKS = {
        "telegram": "https://t.me/srcvz",
        "github": "https://github.com/SRTz123s/Discord-Server-Cloner",
        "donate": "https://www.donationalerts.com/r/spiritvvm",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        scroll = qfluentwidgets.ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)
        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        root.addWidget(SubtitleLabel("Поддержка"))
        root.addWidget(BodyLabel(
            "Поддержите проект: свяжитесь с автором, посмотрите исходный код "
            "или оставьте донат."))

        group = SettingCardGroup("Ссылки", self)
        group.addSettingCard(HyperlinkCard(
            self.LINKS["telegram"], "Перейти в Telegram",
            FIC.SEND, "Написать в Telegram",
            "Вопросы, баг-репорты и предложения — в личку автору.",
            self))
        group.addSettingCard(HyperlinkCard(
            self.LINKS["github"], "Открыть GitHub",
            FIC.GITHUB, "Исходный код на GitHub",
            "Полный открытый исходный код программы.",
            self))
        group.addSettingCard(HyperlinkCard(
            self.LINKS["donate"], "Перейти к донату",
            FIC.HEART, "Поддержать донатом",
            "DonationAlerts — любая сумма помогает развитию.",
            self))
        root.addWidget(group)
        root.addStretch(1)


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()

        theme_text, accent, mica = _load_appearance()
        theme_map = {"Тёмная": Theme.DARK, "Светлая": Theme.LIGHT,
                     "Как в системе": Theme.AUTO}
        setTheme(theme_map.get(theme_text, Theme.DARK))
        try:
            setThemeColor(QColor(accent))
        except Exception:
            setThemeColor(BLURPLE)
        self.setMicaEffectEnabled(bool(mica))

        self.setWindowTitle("Discord Server Cloner")
        self.resize(1000, 720)
        self.setMinimumSize(820, 600)

        self._status_text = "Ожидание"

        self.cloner_page = ClonerPage(self)
        self.support_page = SupportPage(self)
        self.settings_page = SettingsPage(self)
        self.about_page = AboutPage(self)
        self.cloner_page.setObjectName("clonerPage")
        self.support_page.setObjectName("supportPage")
        self.settings_page.setObjectName("settingsPage")
        self.about_page.setObjectName("aboutPage")

        self.addSubInterface(self.cloner_page, FIC.COPY, "Клонировать")
        self.addSubInterface(self.support_page, FIC.HEART, "Поддержка")
        self.addSubInterface(self.settings_page, FIC.SETTING, "Настройки")
        self.addSubInterface(self.about_page, FIC.INFO, "О программе",
                             NavigationItemPosition.BOTTOM)

        # status in title bar via avatar area text
        try:
            self.navigationInterface.setStatusBarWidget(None)
        except Exception:
            pass

        self.navigationInterface.addSeparator()

    def set_status(self, text):
        self._status_text = text
        self.setWindowTitle(f"Discord Server Cloner  —  {text}")


if __name__ == "__main__":
    import sys as _sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(_sys.argv)
    app.setStyleSheet(FluentStyleSheet.FLUENT_WINDOW.value)
    w = MainWindow()
    w.show()
    _sys.exit(app.exec())
