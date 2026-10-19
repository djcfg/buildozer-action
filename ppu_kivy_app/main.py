"""Помощник ППУ — офлайн-приложение (Kivy) для Android.

Работает с данными Google Docs / Sheets / Drive без Telegram: тексты и таблицы
полностью кэшируются на устройстве, фото/схемы скачиваются по требованию.

Запуск на десктопе (для проверки интерфейса):
    pip install -r requirements.txt
    python main.py

Сборка APK — см. buildozer.spec (Linux/WSL2).
"""

import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.utils import platform

from app.config import SettingsStore
from app.runner import Runner
from app.service import PPUService
from app.storage import OfflineStore

# стили виджетов должны быть загружены до создания Root
Builder.load_file(os.path.join(BASE_DIR, "ppu_ui.kv"))

from app import screens  # noqa: E402  (импортируем после загрузки KV-стилей)

APP_TITLE = "Помощник ППУ"
BACKGROUND = (0.11, 0.12, 0.15, 1)

logger = logging.getLogger("ppu")


def _setup_logging(data_dir: str):
    """Добавляем ТОЛЬКО файловый логгер.

    Kivy сам настраивает console-лог и перехватывает sys.stderr в логгер,
    поэтому добавлять StreamHandler нельзя: получается цикл
    log -> stderr -> log (RecursionError).
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    already = any(getattr(handler, "_ppu_file_handler", False) for handler in root.handlers)
    if not already:
        try:
            handler = logging.FileHandler(os.path.join(data_dir, "ppu.log"), encoding="utf-8")
        except Exception:
            return
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        handler._ppu_file_handler = True
        root.addHandler(handler)

    # внутренние логи библиотек — только ошибки
    for noisy in ("urllib3", "google", "charset_normalizer", "idna"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class PPUApp(App):
    title = APP_TITLE

    def build(self):
        # на Android данные лежат в private data приложения, на десктопе — рядом с main.py
        data_dir = getattr(self, "test_data_dir", None)
        if not data_dir:
            data_dir = os.path.join(BASE_DIR, "app_data") if platform != "android" else self.user_data_dir
        os.makedirs(data_dir, exist_ok=True)
        _setup_logging(data_dir)

        Window.clearcolor = BACKGROUND
        if platform != "android":
            Window.size = (420, 800)

        self.store = SettingsStore(data_dir)
        self.cache = OfflineStore(data_dir)
        self.runner = Runner(max_workers=3)
        self.service = PPUService(self.store, self.cache, self.runner)

        self.root_view = screens.Root(
            service=self.service, store=self.store, base_dir=data_dir
        )
        # первый рендер — после появления окна (нужны реальные размеры для переноса строк)
        Clock.schedule_once(lambda _dt: self.root_view.home(), 0)
        logger.info("Запуск. data_dir=%s, credentials=%s",
                    data_dir, self.store.settings().credentials_file)
        return self.root_view

    def on_pause(self):
        return True

    def on_stop(self):
        try:
            self.store.save()
        except Exception:
            logger.exception("Не удалось сохранить настройки")
        self.runner.shutdown()


if __name__ == "__main__":
    PPUApp().run()
