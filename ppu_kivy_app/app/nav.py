"""Построение дерева меню (повторяет структуру кнопок бота из main3.py).

Узел навигации — обычный dict:
    {"screen": <имя экрана>, "title": ..., "entries": [(подпись, узел)], ...params}
"""

from typing import Dict, List, Tuple

from .config import (
    EQUIP_ITEM_NAME, MKSS_ITEM_NAME, MKSS_MENU_NAME, PHONE_KEYS, Settings, VKS_MENU_NAME,
)


def _menu(title: str, entries: List[Tuple[str, Dict]], hint: str = "") -> Dict:
    return {"screen": "menu", "title": title, "entries": entries, "hint": hint}


def doc_node(title: str, doc_name: str) -> Dict:
    return {"screen": "text", "title": title, "doc": doc_name}


def static_node(title: str, text: str, source_doc: str = "") -> Dict:
    """Уже извлечённый из документа фрагмент (элемент FAQ)."""
    return {"screen": "text", "title": title, "static_text": text, "doc": source_doc}


def table_node(title: str, sheet: str) -> Dict:
    return {"screen": "table", "title": title, "sheet": sheet}


def phones_node(title: str, key: str, sheet: str) -> Dict:
    return {"screen": "phones", "title": title, "key": key, "sheet": sheet}


def faq_node(item: str) -> Dict:
    return {"screen": "faq", "title": f"📄 Прочие сведения — {item}", "item": item}


def schemes_node(item: str) -> Dict:
    return {"screen": "schemes", "title": f"✒ Фото/Схемы — {item}", "folder": item}


def settings_node() -> Dict:
    return {"screen": "settings", "title": "⚙ Настройки"}


# ---------------- позиции ----------------
def item_menu(settings: Settings, item: str, kind: str) -> Dict:
    """Меню позиции: 'auto' — техника, 'vks'/'mkss' — оборудование, 'other' — прочее."""
    entries: List[Tuple[str, Dict]] = [
        ("❔ ТТХ", doc_node(f"📋 ТТХ {item}", settings.doc_name(item))),
        ("📄 Прочие сведения", faq_node(item)),
    ]
    if kind == "auto":
        entries.append(("💻 Сеть", table_node(f"🌐 Сети {item}", settings.sheet_for("networks", item))))
        entries.append(("🔑 Ресурсы", table_node(f"📚 Ресурсы {item}", settings.sheet_for("resources", item))))
    elif kind in ("vks", "mkss"):
        entries.append(("💻 Настройки", table_node(f"🌐 Настройки {item}", settings.sheet_for("settings", item))))
    entries.append(("✒ Фото/Схемы", schemes_node(item)))
    return _menu(f"🔧 Меню: {item}", entries)


def vks_menu(settings: Settings) -> Dict:
    entries = [(f"🖥 {item}", item_menu(settings, item, "vks")) for item in settings.vks_tvs]
    return _menu("🖥 ВКС Yealink + ТВ", entries, hint="Оборудование")


def mkss_menu(settings: Settings) -> Dict:
    node = item_menu(settings, MKSS_ITEM_NAME, "mkss")
    node["title"] = f"📡 Меню: МКСС"
    return node


def equipment_menu(settings: Settings) -> Dict:
    entries: List[Tuple[str, Dict]] = [
        ("❔ Общая информация", doc_node("Общая информация по оборудованию",
                                         settings.doc_name(EQUIP_ITEM_NAME))),
    ]
    for item in settings.equipments:
        if item == VKS_MENU_NAME:
            entries.append(("🖥 " + item, vks_menu(settings)))
        elif item == MKSS_MENU_NAME:
            entries.append(("📡 " + item, mkss_menu(settings)))
        elif item in settings.vks_tvs:
            entries.append(("🖥 " + item, item_menu(settings, item, "vks")))
        else:
            entries.append(("📡 " + item, item_menu(settings, item, "other")))
    return _menu("📡 Оборудование", entries)


def tech_menu(settings: Settings) -> Dict:
    entries = [(f"🚛 {item}", item_menu(settings, item, "auto")) for item in settings.autos]
    return _menu("🚒 Техника", entries)


def phones_menu(settings: Settings) -> Dict:
    entries = [
        (label, phones_node(label, key, settings.sheet_for_phone(key)))
        for key, label, _default in PHONE_KEYS
    ]
    return _menu("☎ Телефоны", entries)


def main_menu(settings: Settings) -> Dict:
    entries: List[Tuple[str, Dict]] = [
        ("📜 Общие сведения", doc_node("📜 Общие сведения", settings.general_doc)),
        ("☎ Телефоны", phones_menu(settings)),
        ("🚒 Техника", tech_menu(settings)),
        ("📡 Оборудование", equipment_menu(settings)),
        ("🔄 Полная синхронизация", {"screen": "action", "action": "sync"}),
        ("⚙ Настройки", settings_node()),
    ]
    return _menu("📌 Помощник ППУ", entries)
