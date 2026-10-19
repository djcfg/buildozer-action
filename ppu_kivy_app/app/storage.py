"""Офлайн-хранилище приложения.

Всё лежит в user_data_dir/cache/:

    docs.json     — тексты Google Docs  {"doc:<имя>": {"text", "ts"}}
    sheets.json   — данные листов        {"sheet:<имя листа>": {"rows", "ts"}}
    folders.json  — списки файлов Drive {"folder:<папка>": {"files", "ts"}}
    media.json    — скачанные фото/PDF  {"<file_id>": {"name", "mime", "path", "ts", "size"}}
    media/        — сами файлы
    meta.json     — служебное (время последней полной синхронизации)

Записи пишутся атомарно (tmp + os.replace), чтобы обрыв процесса не повреждал кэш.
"""

import json
import logging
import os
import re
import shutil
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DOC_PREFIX = "doc:"
SHEET_PREFIX = "sheet:"
FOLDER_PREFIX = "folder:"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def safe_filename(name: str, fallback: str = "file") -> str:
    """Имя файла, безопасное для файловой системы Android."""
    cleaned = re.sub(r'[^\wА-Яа-я.\- ]+', '_', str(name or "")).strip(' ._')
    cleaned = cleaned[:120]
    return cleaned or fallback


class OfflineStore:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.cache_dir = os.path.join(base_dir, "cache")
        self.media_dir = os.path.join(self.cache_dir, "media")
        os.makedirs(self.media_dir, exist_ok=True)

        self._docs_path = os.path.join(self.cache_dir, "docs.json")
        self._sheets_path = os.path.join(self.cache_dir, "sheets.json")
        self._folders_path = os.path.join(self.cache_dir, "folders.json")
        self._media_path = os.path.join(self.cache_dir, "media.json")
        self._meta_path = os.path.join(self.cache_dir, "meta.json")

    # ---------------- низкоуровневые helpers ----------------
    def _load(self, path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.error("Кэш %s повреждён: %s", path, exc)
            return {}

    def _save(self, path: str, data: dict):
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as exc:
            logger.error("Не удалось сохранить %s: %s", path, exc)

    # ---------------- документы ----------------
    def doc_keys(self) -> List[str]:
        return list(self._load(self._docs_path).keys())

    def get_doc(self, name: str) -> Optional[Tuple[str, str]]:
        """Возвращает (текст, время_загрузки) или None."""
        entry = self._load(self._docs_path).get(DOC_PREFIX + name)
        if not entry:
            return None
        return entry.get("text", ""), entry.get("ts", "")

    def save_doc(self, name: str, text: str):
        data = self._load(self._docs_path)
        data[DOC_PREFIX + name] = {"text": text, "ts": _now()}
        self._save(self._docs_path, data)

    def drop_doc(self, name: str):
        data = self._load(self._docs_path)
        data.pop(DOC_PREFIX + name, None)
        self._save(self._docs_path, data)

    # ---------------- таблицы ----------------
    def sheet_keys(self) -> List[str]:
        return list(self._load(self._sheets_path).keys())

    def get_sheet(self, title: str) -> Optional[Tuple[List[List[str]], str]]:
        entry = self._load(self._sheets_path).get(SHEET_PREFIX + title)
        if not entry:
            return None
        return entry.get("rows", []), entry.get("ts", "")

    def save_sheet(self, title: str, rows: List[List[str]]):
        data = self._load(self._sheets_path)
        data[SHEET_PREFIX + title] = {"rows": rows, "ts": _now()}
        self._save(self._sheets_path, data)

    # ---------------- списки файлов ----------------
    def get_folder(self, folder: str) -> Optional[Tuple[List[Dict], str]]:
        entry = self._load(self._folders_path).get(FOLDER_PREFIX + folder)
        if not entry:
            return None
        return entry.get("files", []), entry.get("ts", "")

    def save_folder(self, folder: str, files: List[Dict]):
        data = self._load(self._folders_path)
        data[FOLDER_PREFIX + folder] = {"files": files, "ts": _now()}
        self._save(self._folders_path, data)

    # ---------------- медиа ----------------
    def get_media(self, file_id: str) -> Optional[Dict]:
        entry = self._load(self._media_path).get(file_id)
        if entry and entry.get("path") and os.path.exists(entry["path"]):
            return entry
        return None

    def save_media(self, file_id: str, data: bytes, name: str, mime: str) -> Dict:
        index = self._load(self._media_path)
        ext = os.path.splitext(name)[1][:8]
        fname = f"{safe_filename(file_id)}{ext or ('.pdf' if 'pdf' in (mime or '').lower() else '')}"
        path = os.path.join(self.media_dir, fname)

        # файл мог быть сохранён под другим именем — убираем старый, чтобы не копить дубли
        old = index.get(file_id)
        if old and old.get("path") and old["path"] != path and os.path.exists(old["path"]):
            try:
                os.remove(old["path"])
            except OSError:
                pass

        with open(path, "wb") as f:
            f.write(data)

        entry = {
            "name": name,
            "mime": mime or "",
            "path": path,
            "ts": _now(),
            "size": len(data),
        }
        index[file_id] = entry
        self._save(self._media_path, index)
        return entry

    def media_count(self) -> int:
        return len(self._load(self._media_path))

    # ---------------- мета / статистика / очистка ----------------
    @property
    def last_sync(self) -> str:
        return self._load(self._meta_path).get("last_sync", "")

    def set_last_sync(self, value: str):
        data = self._load(self._meta_path)
        data["last_sync"] = value
        self._save(self._meta_path, data)

    def touch_sync(self):
        self.set_last_sync(_now())

    def stats(self) -> Dict[str, object]:
        docs = self._load(self._docs_path)
        sheets = self._load(self._sheets_path)
        folders = self._load(self._folders_path)
        media = self._load(self._media_path)
        text_bytes = sum(len(str(e.get("text", ""))) for e in docs.values())
        return {
            "docs": len(docs),
            "sheets": len(sheets),
            "folders": len(folders),
            "media": len(media),
            "media_bytes": sum(int(e.get("size", 0)) for e in media.values()),
            "text_bytes": text_bytes,
            "cache_bytes": self._dir_size(self.cache_dir),
            "last_sync": self.last_sync,
            "cache_dir": self.cache_dir,
        }

    def clear(self, what: str = "all") -> int:
        """what: all | text | media. Возвращает число удалённых записей."""
        removed = 0
        if what in ("all", "text"):
            for path in (self._docs_path, self._sheets_path, self._folders_path):
                removed += len(self._load(path))
                self._save(path, {})
        if what in ("all", "media"):
            removed += len(self._load(self._media_path))
            self._save(self._media_path, {})
            if os.path.isdir(self.media_dir):
                shutil.rmtree(self.media_dir, ignore_errors=True)
                os.makedirs(self.media_dir, exist_ok=True)
        return removed

    @staticmethod
    def _dir_size(path: str) -> int:
        total = 0
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total


def human_size(num: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if abs(num) < 1024:
            return f"{num:.0f} {unit}" if unit == "Б" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} ТБ"


def age_text(ts: str) -> str:
    """Человекочитаемый возраст записи кэша."""
    if not ts:
        return "нет в кэше"
    try:
        then = datetime.strptime(ts, "%Y-%m-%d %H:%M")
    except ValueError:
        return ts
    delta = datetime.now() - then
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "только что"
    if minutes < 60:
        return f"{minutes} мин назад"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ч назад"
    return f"{hours // 24} дн назад ({ts})"
