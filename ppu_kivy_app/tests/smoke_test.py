"""Быстрая проверка ядра приложения без UI (не требует Android/Telegram).

Запуск из папки ppu_kivy_app:
    python tests/smoke_test.py

Проверяется: настройки + импорт .env, офлайн-кэш, разбор FAQ/таблиц/телефонов,
дерево меню и поведение сервисного слоя без сети (с подставным Google-клиентом).
"""

import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from app.config import SettingsStore  # noqa: E402
from app.google_api import GoogleApiError  # noqa: E402
from app.parsing import build_contacts, parse_faq, rows_to_records  # noqa: E402
from app.runner import Runner, set_ui_poster  # noqa: E402
from app.service import PPUService  # noqa: E402
from app.storage import OfflineStore  # noqa: E402
from app import nav  # noqa: E402

ENV_SAMPLE = """
TELEGRAM_TOKEN=не_нужен_приложению
BOT_PASSWORD=тоже_не_нужен
AUTOS=Автомобиль 1;Автомобиль 2
EQUIPMENTS=ВКС Yealink + ТВ;МКСС (спутники);Рация
VKS_TVS=ОШ СМГ-1;ОШ СМГ-2
DOC_Автомобиль_1=ТТХ Автомобиль 1
TTX_Автомобиль_2=ТТХ Автомобиль 2
DOC_ОШ_СМГ-1=ТТХ ОШ СМГ-1
TTX_EQUIP=Оборудование общая информация
TTX_MKSS=МКСС ТТХ
OBSCHIE_SVED=Прочие сведения
"""

DOC_FAQ = """вступление без заголовка
***Вопрос первый***
ответ один
***Вопрос второй***
ответ два
"""

SHEET = [
    ["ФИО", "Телефон", "Примечание"],
    ["Иванов И.И.", "+7 (999) 123-45-67", "начальник"],
    ["", "", ""],
    ["Петров П.П.", "внутренний 123", "водитель"],
]


class FakeClient:
    """Подставной Google-клиент: сеть эмулируется, ошибок — нет."""

    def __init__(self):
        self.calls = []

    def fetch_doc_text(self, name):
        self.calls.append(("doc", name))
        return DOC_FAQ if name.startswith("Прочие") else f"Содержимое документа «{name}»"

    def fetch_sheet_rows(self, title):
        self.calls.append(("sheet", title))
        return SHEET

    def list_folder_media(self, folder):
        self.calls.append(("folder", folder))
        return [{"id": f"id_{folder}", "name": "схема.pdf", "mimeType": "application/pdf"}]

    def download_file(self, file_id):
        self.calls.append(("download", file_id))
        return b"%PDF-1.4 fake"


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("  OK —", message)


def main():
    workdir = tempfile.mkdtemp(prefix="ppu_smoke_")
    print("Каталог теста:", workdir)
    # без запущенного event loop Kivy колбэки выполняем сразу в этом же потоке
    set_ui_poster(lambda action: action())

    # ---- настройки и импорт .env ----
    store = SettingsStore(workdir)
    stats = store.import_env(ENV_SAMPLE)
    settings = store.settings()
    check(settings.autos == ["Автомобиль 1", "Автомобиль 2"], "список AUTOS разобран")
    check(settings.doc_name("Автомобиль 1") == "ТТХ Автомобиль 1", "DOC_* сопоставлен позиции")
    check(settings.doc_name("Автомобиль 2") == "ТТХ Автомобиль 2", "TTX_* (старый ключ) тоже принят")
    check(settings.doc_name("ОШ СМГ-1") == "ТТХ ОШ СМГ-1", "имена с дефисом нормализуются")
    check(settings.doc_name("Оборудование") == "Оборудование общая информация", "TTX_EQUIP импортирован")
    check(settings.general_doc == "Прочие сведения", "OBSCHIE_SVED импортирован")
    check(stats["docs"] >= 5, f"импортировано документов: {stats['docs']}")
    store.save()
    check(os.path.exists(store.path), "settings.json записан")

    # ---- разбор контента ----
    sections = parse_faq(DOC_FAQ)
    check(len(sections) == 2 and sections[0][1] == "ответ один", "FAQ разбит на вопросы")
    headers, records = rows_to_records(SHEET)
    check(headers[1] == "Телефон" and len(records) == 2, "пустая строка таблицы пропущена")
    contacts = build_contacts(SHEET)
    check(contacts[0]["phone"] == "+79991234567", "номер нормализован для звонка")
    check(contacts[1]["phone"] == "123", "номер без плюса тоже годится")

    # ---- меню повторяет структуру бота ----
    main = nav.main_menu(settings)
    labels = [text for text, _ in main["entries"]]
    check("🚒 Техника" in labels and "📡 Оборудование" in labels, "главное меню собрано")
    tech = dict(main["entries"])["🚒 Техника"]
    check(len(tech["entries"]) == 2, "меню техники по числу AUTOS")
    equip = dict(main["entries"])["📡 Оборудование"]
    equip_labels = [text for text, _ in equip["entries"]]
    check(any("ВКС Yealink" in text for text in equip_labels), "ВКС — подменю, а не позиция")
    vks = dict(equip["entries"])["🖥 ВКС Yealink + ТВ"]
    check(len(vks["entries"]) == 2, "список ВКС комплектов")
    auto_item = dict(tech["entries"])["🚛 Автомобиль 1"]
    item_labels = [text for text, _ in auto_item["entries"]]
    check("💻 Сеть" in item_labels and "🔑 Ресурсы" in item_labels, "у техники есть Сеть/Ресурсы")
    vks_item = dict(vks["entries"])["🖥 ОШ СМГ-1"]
    check("💻 Настройки" in [text for text, _ in vks_item["entries"]], "у ВКС есть Настройки")

    # ---- сервис: офлайн-чтение и синхронизация ----
    cache = OfflineStore(workdir)
    runner = Runner(max_workers=2)
    service = PPUService(store, cache, runner)
    service.client = lambda: FakeClient()  # подменяем сетевой слой

    results = {}
    service.get_doc("ТТХ Автомобиль 1", force=False, on_done=lambda r: results.__setitem__("doc", r))
    runner.wait_idle()
    check(results["doc"].ok and "Содержимое" in results["doc"].value, "документ загружен и закеширован")
    check(cache.get_doc("ТТХ Автомобиль 1") is not None, "документ есть в кэше")

    results.clear()
    service.get_doc("ТТХ Автомобиль 1", force=False, on_done=lambda r: results.__setitem__("doc", r))
    runner.wait_idle()
    check(results["doc"].source == "cache", "повторное чтение — из кэша (без сети)")

    results.clear()
    plan = service.sync_plan()
    service.sync_all(lambda *args: None, lambda r: results.__setitem__("sync", r))
    runner.wait_idle(timeout=120)
    check(results["sync"].ok and results["sync"].value["ok"] == len(plan),
          f"полная синхронизация: {results['sync'].value['ok']} объектов")
    check(cache.last_sync, "записано время синхронизации")

    # кэширование медиа (фото/PDF) по кнопке — пока сетевой слой работает
    results.clear()
    service.cache_folder_media("Автомобиль 1", lambda *args: None,
                               lambda r: results.__setitem__("media", r))
    runner.wait_idle()
    check(results["media"].ok and results["media"].value["ok"] == 1, "файл схемы скачан в кэш")
    media_entry = cache.get_media("id_Автомобиль 1")
    check(media_entry and os.path.exists(media_entry["path"]), "файл лежит на устройстве")

    # офлайн-режим: без клиента и без сети данные берутся из кэша
    service.client = lambda: (_ for _ in ()).throw(GoogleApiError("сети нет"))
    results.clear()
    service.get_sheet("Телефоны начальство", force=False, on_done=lambda r: results.__setitem__("sheet", r))
    runner.wait_idle()
    check(results["sheet"].ok and results["sheet"].source == "cache", "таблица офлайн — из кэша")

    results.clear()
    service.get_media_offline("id_Автомобиль 1", lambda r: results.__setitem__("m2", r))
    runner.wait_idle()
    check(results["m2"].ok, "скачанный файл доступен офлайн")

    stats = cache.stats()
    check(stats["docs"] >= 1 and stats["media"] == 1, f"статистика кэша: {stats['docs']} док., 1 медиа")
    removed = cache.clear("media")
    check(removed == 1 and cache.get_media("id_Автомобиль 1") is None, "очистка кэша медиа работает")

    # ошибочная сеть: недокументированный объект должен отдавать ошибку, а не падать
    def boom():
        raise GoogleApiError("нет доступа к Internet")

    service.client = boom
    results.clear()
    service.get_doc("Новый документ", force=True, on_done=lambda r: results.__setitem__("err", r))
    runner.wait_idle()
    check(not results["err"].ok and "Internet" in results["err"].error, "сетевая ошибка показана пользователю")

    runner.shutdown()
    print("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ ✓")


if __name__ == "__main__":
    main()
