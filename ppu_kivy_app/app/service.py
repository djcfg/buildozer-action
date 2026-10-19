"""Сервис данных: кэш-ориентированная работа с Google Docs / Sheets / Drive.

Приоритет всегда у локального кэша (приложение должно работать офлайн),
сеть используется при обновлении и при первом обращении.
"""

import logging
import os
from typing import Callable, Dict, List, Optional, Tuple

from .config import (
    EQUIP_ITEM_NAME, MKSS_ITEM_NAME, MKSS_MENU_NAME, PHONE_KEYS, Settings, SettingsStore,
    VKS_MENU_NAME,
)
from .google_api import GoogleApiClient, GoogleApiError
from .runner import Runner, in_ui_thread
from .storage import OfflineStore

logger = logging.getLogger(__name__)


class Result:
    """Итоп асинхронной операции; приходит в UI-поток."""

    def __init__(self, ok: bool, value=None, ts: str = "", source: str = "", error: str = None):
        self.ok = ok
        self.value = value
        self.ts = ts
        self.source = source          # 'cache' | 'net'
        self.error = error

    @classmethod
    def cached(cls, value, ts: str) -> "Result":
        return cls(True, value, ts, "cache")

    @classmethod
    def loaded(cls, value, ts: str = "") -> "Result":
        return cls(True, value, ts, "net")

    @classmethod
    def failed(cls, error) -> "Result":
        return cls(False, error=str(error) or "Неизвестная ошибка")


class PPUService:
    def __init__(self, store: SettingsStore, cache: OfflineStore, runner: Runner):
        self.store = store
        self.cache = cache
        self.runner = runner
        self._client: Optional[GoogleApiClient] = None
        self._client_signature: Tuple[str, str] = ("", "")

    # ---------------- настройки и клиент ----------------
    @property
    def settings(self) -> Settings:
        return self.store.settings()

    def client(self) -> GoogleApiClient:
        """Клиент пересоздаётся, если изменились credentials или имя таблицы."""
        settings = self.settings
        signature = (settings.credentials_file, settings.spreadsheet_name)
        if self._client is None or self._client_signature != signature:
            self._client = GoogleApiClient(settings.credentials_file, settings.spreadsheet_name)
            self._client_signature = signature
        return self._client

    def credentials_ready(self) -> bool:
        path = self.settings.credentials_file
        return bool(path and os.path.exists(path))

    # ---------------- документы ----------------
    def get_doc(self, name: str, force: bool, on_done: Callable[[Result], None]):
        cached = self.cache.get_doc(name)
        if cached and not force:
            on_done(Result.cached(cached[0], cached[1]))
            return

        def work():
            text = self.client().fetch_doc_text(name)
            self.cache.save_doc(name, text)
            return text

        self.runner.submit(
            work,
            on_success=lambda text: on_done(Result.loaded(text, self.cache.get_doc(name)[1])),
            on_error=lambda exc: self._fallback(cached, on_done, exc),
        )

    # ---------------- таблицы ----------------
    def get_sheet(self, title: str, force: bool, on_done: Callable[[Result], None]):
        cached = self.cache.get_sheet(title)
        if cached and not force:
            on_done(Result.cached(cached[0], cached[1]))
            return

        def work():
            rows = self.client().fetch_sheet_rows(title)
            self.cache.save_sheet(title, rows)
            return rows

        self.runner.submit(
            work,
            on_success=lambda rows: on_done(Result.loaded(rows, self.cache.get_sheet(title)[1])),
            on_error=lambda exc: self._fallback(cached, on_done, exc),
        )

    # ---------------- списки файлов ----------------
    def get_folder(self, folder: str, force: bool, on_done: Callable[[Result], None]):
        cached = self.cache.get_folder(folder)
        if cached and not force:
            on_done(Result.cached(cached[0], cached[1]))
            return

        def work():
            files = self.client().list_folder_media(folder)
            self.cache.save_folder(folder, files)
            return files

        self.runner.submit(
            work,
            on_success=lambda files: on_done(Result.loaded(files, self.cache.get_folder(folder)[1])),
            on_error=lambda exc: self._fallback(cached, on_done, exc),
        )

    # ---------------- медиа ----------------
    def cached_media(self, file_id: str) -> Optional[Dict]:
        return self.cache.get_media(file_id)

    def get_media_offline(self, file_id: str, on_done: Callable[[Result], None]):
        """Отдать уже скачанный файл (без обращения к сети)."""
        entry = self.cache.get_media(file_id)
        if entry:
            on_done(Result.cached(entry, entry.get("ts", "")))
        else:
            on_done(Result.failed("Файл ещё не скачан на устройство"))

    def download_media(self, file_info: Dict, on_done: Callable[[Result], None]):
        """Скачать файл в кэш (если уже скачан — отдать путь из кэша)."""
        file_id = file_info.get("id", "")
        existing = self.cache.get_media(file_id)
        if existing:
            on_done(Result.cached(existing, existing.get("ts", "")))
            return

        def work():
            data = self.client().download_file(file_id)
            return self.cache.save_media(
                file_id, data, file_info.get("name", ""), file_info.get("mimeType", "")
            )

        self.runner.submit(
            work,
            on_success=lambda entry: on_done(Result.loaded(entry, entry.get("ts", ""))),
            on_error=lambda exc: on_done(Result.failed(exc)),
        )

    def cache_folder_media(self, folder: str, on_progress: Callable, on_done: Callable):
        """Кнопка «Кэшировать эти данные»: скачать все файлы папки схем."""
        def work():
            cached = self.cache.get_folder(folder)
            files = cached[0] if cached else self.client().list_folder_media(folder)
            if not cached:
                self.cache.save_folder(folder, files)
            total = len(files)
            done = ok = failed = 0
            for info in files:
                done += 1
                in_ui_thread(on_progress)(done, total, f"Скачиваю {info.get('name', '')}")
                if self.cache.get_media(info.get("id", "")):
                    ok += 1
                    continue
                try:
                    data = self.client().download_file(info["id"])
                    self.cache.save_media(info["id"], data, info.get("name", ""), info.get("mimeType", ""))
                    ok += 1
                except Exception as exc:
                    failed += 1
                    logger.error("Файл %s не скачан: %s", info.get("name"), exc)
            return {"total": total, "ok": ok, "failed": failed}

        self.runner.submit(
            work,
            on_success=lambda stats: on_done(Result.loaded(stats)),
            on_error=lambda exc: on_done(Result.failed(exc)),
        )

    # ---------------- полная синхронизация ----------------
    def sync_plan(self) -> List[Tuple[str, str]]:
        """Список задач полной синхронизации: ('doc'|'sheet'|'folder', имя)."""
        settings = self.settings
        plan: List[Tuple[str, str]] = []

        if settings.general_doc:
            plan.append(("doc", settings.general_doc))

        # телефонные справочники
        for key, _label, _default in PHONE_KEYS:
            title = settings.sheet_for_phone(key)
            if title:
                plan.append(("sheet", title))

        def add_item(item: str, is_auto: bool):
            doc = settings.doc_name(item)
            if doc:
                plan.append(("doc", doc))
            plan.append(("doc", settings.faq_doc_name(item)))
            if is_auto:
                plan.append(("sheet", settings.sheet_for("networks", item)))
                plan.append(("sheet", settings.sheet_for("resources", item)))
            else:
                plan.append(("sheet", settings.sheet_for("settings", item)))
            plan.append(("folder", item))

        for item in settings.autos:
            add_item(item, is_auto=True)

        for item in settings.equipments:
            if item in (VKS_MENU_NAME, MKSS_MENU_NAME):
                continue  # это подменю, а не позиции с данными
            add_item(item, is_auto=False)

        for item in settings.vks_tvs:
            if item not in settings.equipments:
                add_item(item, is_auto=False)

        if MKSS_ITEM_NAME not in settings.equipments and MKSS_ITEM_NAME not in settings.vks_tvs:
            add_item(MKSS_ITEM_NAME, is_auto=False)

        # общая информация по оборудованию
        equip_doc = settings.doc_name(EQUIP_ITEM_NAME)
        if equip_doc and ("doc", equip_doc) not in plan:
            plan.append(("doc", equip_doc))

        # уникальные (первый встреченный порядок)
        unique: List[Tuple[str, str]] = []
        seen = set()
        for task in plan:
            if task not in seen:
                seen.add(task)
                unique.append(task)
        return unique

    def sync_all(self, on_progress: Callable, on_done: Callable):
        """Загрузить все тексты и таблицы в кэш (для автономной работы)."""
        def work():
            plan = self.sync_plan()
            total = len(plan)
            done = ok = missed = failed = 0
            client = self.client()
            for kind, name in plan:
                done += 1
                in_ui_thread(on_progress)(done, total, f"{kind}: {name}")
                try:
                    if kind == "doc":
                        text = client.fetch_doc_text(name)
                        self.cache.save_doc(name, text)
                        ok += 1
                    elif kind == "sheet":
                        rows = client.fetch_sheet_rows(name)
                        self.cache.save_sheet(name, rows)
                        ok += 1
                    else:
                        files = client.list_folder_media(name)
                        self.cache.save_folder(name, files)
                        ok += 1
                except GoogleApiError as exc:
                    # отсутствие листа/документа — штатная ситуация (не у всех позиций всё есть)
                    if "не найден" in str(exc).lower() or "404" in str(exc):
                        missed += 1
                        logger.info("Пропущено %s «%s»: %s", kind, name, exc)
                    else:
                        failed += 1
                        logger.error("Синхронизация %s «%s» не удалась: %s", kind, name, exc)
                except Exception as exc:
                    failed += 1
                    logger.error("Синхронизация %s «%s» не удалась: %s", kind, name, exc)

            self.cache.touch_sync()
            return {"total": total, "ok": ok, "missed": missed, "failed": failed}

        self.runner.submit(
            work,
            on_success=lambda stats: on_done(Result.loaded(stats, self.cache.last_sync)),
            on_error=lambda exc: on_done(Result.failed(exc)),
        )

    # ---------------- служебное ----------------
    @staticmethod
    def _fallback(cached, on_done: Callable, exc: Exception):
        """Если сети нет, но данные в кэше — показываем кэш, иначе ошибку."""
        if cached:
            value, ts = cached
            logger.warning("Сеть недоступна (%s), показываю кэш", exc)
            result = Result.cached(value, ts)
            result.error = f"Нет соединения — показан кэш. {exc}"
            on_done(result)
        else:
            on_done(Result.failed(exc))

    def clear_cache(self, what: str = "all") -> int:
        return self.cache.clear(what)

    def stats(self) -> Dict[str, object]:
        return self.cache.stats()
