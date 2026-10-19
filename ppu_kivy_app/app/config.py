"""Настройки приложения.

Хранятся в user_data_dir/settings.json и редактируются на экране «Настройки»,
поэтому при изменении перечня техники / имён документов не нужно пересобирать APK.

Форматstorage (JSON):
    AUTOS / EQUIPMENTS / VKS_TVS : str  — списки через ';' (как в .env)
    DOC_NAMES                    : dict — {имя позиции: имя Google Doc}
    OBSCHIE_SVED                 : str  — имя/ID документа «Общие сведения»
    SPREADSHEET_NAME             : str  — имя таблицы (лист «ppu_info» в боте)
    PHONES                       : dict — {код справочника: имя листа}
    CREDENTIALS_FILE             : str  — путь к credentials.json на устройстве
"""

import json
import logging
import os
import re
from typing import Dict, List, Tuple

SETTINGS_FILE = "settings.json"

# Коды телефонных справочников (как callback_data в боте) -> имена листов по умолчанию
PHONE_KEYS: List[Tuple[str, str, str]] = [
    ("ТелефоныНач", "☎ Телефоны Начальство", "Телефоны начальство"),
    ("ТелефоныВод", "☏ Телефоны Водители", "Телефоны водители"),
    ("ТелефоныТех", "☏ Телефоны Тех.персонал", "Телефоны тех.персонал"),
    ("ТелефоныПроч", "☏ Телефоны Прочие", "Телефоны прочие"),
]

# Спец. позиции меню оборудования (совпадают с логикой main3.py)
VKS_MENU_NAME = "ВКС Yealink + ТВ"
MKSS_MENU_NAME = "МКСС (спутники)"
MKSS_ITEM_NAME = "МКСС"
EQUIP_ITEM_NAME = "Оборудование"

logger = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    """Нормализовать имя позиции (как в боте) — для сопоставления ключей DOC_* из .env."""
    return re.sub(r'[^A-Za-zА-Яа-я0-9\-]+', '_', name.strip()).strip('_').upper()


def split_list(raw: str) -> List[str]:
    """Разбить поле списка на элементы (';' — как в .env)."""
    if not raw:
        return []
    return [item.strip() for item in re.split(r'[;\n]', str(raw)) if item.strip()]


def parse_env(text: str) -> Dict[str, str]:
    """Развернуть содержимое .env в dict (без python-dotenv, чтобы не тянуть зависимость)."""
    result: Dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip().lstrip('\ufeff')
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key:
            result[key] = value
    return result


class Settings:
    """Доступ к настройкам с удобными свойствами."""

    def __init__(self, data: dict):
        self._data = data

    # ---------- списки ----------
    @property
    def autos(self) -> List[str]:
        return split_list(self._data.get("AUTOS", ""))

    @property
    def equipments(self) -> List[str]:
        return split_list(self._data.get("EQUIPMENTS", ""))

    @property
    def vks_tvs(self) -> List[str]:
        return split_list(self._data.get("VKS_TVS", ""))

    @property
    def all_items(self) -> List[str]:
        """Все позиции, для которых могут быть свои документы/листы."""
        items = list(self.autos)
        for item in self.equipments:
            if item not in items:
                items.append(item)
        for item in self.vks_tvs:
            if item not in items:
                items.append(item)
        for special in (EQUIP_ITEM_NAME, MKSS_ITEM_NAME):
            if special not in items:
                items.append(special)
        return items

    # ---------- документы ----------
    @property
    def doc_names(self) -> Dict[str, str]:
        return dict(self._data.get("DOC_NAMES") or {})

    def doc_name(self, item: str) -> str:
        """Имя/ID Google Doc с ТТХ (или общей информацией) для позиции."""
        return str(self.doc_names.get(item, "")).strip()

    @property
    def general_doc(self) -> str:
        return str(self._data.get("OBSCHIE_SVED", "")).strip()

    @property
    def faq_doc(self) -> str:
        """Префикс имён документов «Прочие сведения» (в боте — «Прочие <позиция>»)."""
        return str(self._data.get("FAQ_PREFIX", "Прочие")).strip() or "Прочие"

    def faq_doc_name(self, item: str) -> str:
        return f"{self.faq_doc} {item}"

    def faq_title(self, item: str) -> str:
        """Заголовок FAQ-документа в том же нормализованном виде, что и ключи DOC_NAMES."""
        return normalize_name(f"{self.faq_doc}_{item}")

    # ---------- таблицы ----------
    @property
    def spreadsheet_name(self) -> str:
        return str(self._data.get("SPREADSHEET_NAME", "ppu_info")).strip() or "ppu_info"

    @property
    def phones(self) -> Dict[str, str]:
        data = dict(self._data.get("PHONES") or {})
        for key, _label, default in PHONE_KEYS:
            data.setdefault(key, default)
        return data

    def sheet_for_phone(self, key: str) -> str:
        return str(self.phones.get(key, "")).strip()

    def sheet_for(self, kind: str, item: str) -> str:
        """Имя листа по типу данных: networks/resources/settings (как в боте)."""
        prefix = {"networks": "Сети", "resources": "Ресурсы", "settings": "Настройки"}[kind]
        return f"{prefix}_{item}"

    # ---------- доступ к Google ----------
    @property
    def credentials_file(self) -> str:
        return str(self._data.get("CREDENTIALS_FILE", "")).strip()

    # ---------- служебное ----------
    @property
    def raw(self) -> dict:
        return self._data

    def set_list(self, key: str, items: List[str]):
        self._data[key] = "; ".join(items)

    def set_doc_name(self, item: str, doc_name: str):
        self._data.setdefault("DOC_NAMES", {})[item] = doc_name

    def remove_doc_name(self, item: str):
        (self._data.get("DOC_NAMES") or {}).pop(item, None)

    def set_value(self, key: str, value: str):
        self._data[key] = value


class SettingsStore:
    """Загрузка/сохранение settings.json."""

    DEFAULTS = {
        "AUTOS": "",
        "EQUIPMENTS": "",
        "VKS_TVS": "",
        "DOC_NAMES": {},
        "OBSCHIE_SVED": "",
        "FAQ_PREFIX": "Прочие",
        "SPREADSHEET_NAME": "ppu_info",
        "PHONES": {key: default for key, _label, default in PHONE_KEYS},
        "CREDENTIALS_FILE": "",
    }

    def __init__(self, base_dir: str):
        self.path = os.path.join(base_dir, SETTINGS_FILE)
        self._data = self._load()

    def _load(self) -> dict:
        data = json.loads(json.dumps(self.DEFAULTS))  # глубокая копия дефолтов
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                if isinstance(stored, dict):
                    for key, value in stored.items():
                        if key == "DOC_NAMES" and isinstance(value, dict) and isinstance(data.get(key), dict):
                            data["DOC_NAMES"].update(value)
                        elif key == "PHONES" and isinstance(value, dict) and isinstance(data.get(key), dict):
                            data["PHONES"].update(value)
                        else:
                            data[key] = value
            except Exception as exc:  # повреждённый файл не должен ломать запуск
                logger.error("Не удалось прочитать %s: %s", self.path, exc)
        return data

    def save(self) -> str:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        return self.path

    @property
    def data(self) -> dict:
        return self._data

    def settings(self) -> Settings:
        return Settings(self._data)

    # ---------- импорт из .env ----------
    def import_env(self, text: str) -> Dict[str, int]:
        """Слить значения из .env в настройки. Возвращает счётчики импортированного."""
        env = parse_env(text)
        # ключи .env нормализуем по верхнему регистру: в реальном файле они и так заглавные,
        # но правки руками (DOC_Автомобиль_1) не должны ломать импорт
        env_upper = {key.upper(): value for key, value in env.items()}
        stats = {"lists": 0, "docs": 0, "other": 0}

        for key in ("AUTOS", "EQUIPMENTS", "VKS_TVS"):
            if env_upper.get(key):
                self._data[key] = env_upper[key]
                stats["lists"] += 1

        if env_upper.get("OBSCHIE_SVED"):
            self._data["OBSCHIE_SVED"] = env_upper["OBSCHIE_SVED"]
            stats["other"] += 1

        docs = self._data.setdefault("DOC_NAMES", {})
        settings = self.settings()
        for item in settings.all_items:
            norm = normalize_name(item)
            value = env_upper.get(f"DOC_{norm}") or env_upper.get(f"TTX_{norm}")
            if value:
                docs[item] = value
                stats["docs"] += 1

        # отдельные общие документы бота: TTX_EQUIP / TTX_MKSS
        if env_upper.get("TTX_EQUIP"):
            docs[EQUIP_ITEM_NAME] = env_upper["TTX_EQUIP"]
            stats["docs"] += 1
        if env_upper.get("TTX_MKSS"):
            docs[MKSS_ITEM_NAME] = env_upper["TTX_MKSS"]
            stats["docs"] += 1

        phones = self._data.setdefault("PHONES", {})
        for key, _label, _default in PHONE_KEYS:
            value = env_upper.get(f"PHONES_{normalize_name(key)}") or env_upper.get(f"SHEET_{normalize_name(key)}")
            if value:
                phones[key] = value
                stats["other"] += 1

        self.save()
        return stats
