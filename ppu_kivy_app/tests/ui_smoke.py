"""UI-проверка на десктопе: открывает все экраны и сохраняет скриншоты.

    python tests/ui_smoke.py

Ничего общего с боевыми данными: каталог app_data_ui, сеть не используется
(кэш заполняется фиктивными документами).
Скриншоты — в tests/screenshots/.
"""

import os
import shutil
import sys

# не глушить traceback Kivy — иначе не видно, где именно падает UI
os.environ.setdefault('KIVY_EXCEPTIONS', '0')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

DATA_DIR = os.path.join(BASE, "app_data_ui")
SHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")

ENV_SAMPLE = """
AUTOS=Автомобиль АЦ-40;Автомобиль АРС-14
EQUIPMENTS=ВКС Yealink + ТВ;МКСС (спутники)
VKS_TVS=ОШ СМГ-1
DOC_АВТОМОБИЛЬ_АЦ-40=ТТХ АЦ-40
DOC_АВТОМОБИЛЬ_АРС-14=ТТХ АРС-14
DOC_ОШ_СМГ-1=ТТХ ОШ СМГ-1
TTX_EQUIP=Каталог оборудования
TTX_MKSS=МКСС ТТХ
OBSCHIE_SVED=Прочие сведения
"""

FAQ_DOC = """***Как заправить бак?***
Проверить уровень, заправить через горловину А.
***Как включить мигалки?***
Тумблер «СПС» слева от руля.
"""

SHEET_NETWORKS = [
    ["Оборудование", "IP-адрес", "Порт", "Пароль"],
    ["Роутер", "192.168.1.1", "80", "admin123"],
    ["Камера №1", "192.168.1.64", "554", ""],
]

SHEET_PHONES = [
    ["Должность", "Телефон", "Кабинет"],
    ["Начальник ППУ", "+7 (495) 111-22-33", "201"],
    ["Дежурный", "внутр. 1234", "105"],
]


def prepare_data():
    """Заполнить настройки и кэш без сети."""
    if os.path.isdir(DATA_DIR):
        shutil.rmtree(DATA_DIR)
    os.makedirs(os.path.join(DATA_DIR, "cache", "media"), exist_ok=True)

    from app.config import SettingsStore
    from app.storage import OfflineStore

    store = SettingsStore(DATA_DIR)
    store.import_env(ENV_SAMPLE)
    store.save()

    cache = OfflineStore(DATA_DIR)
    cache.save_doc("ТТХ АЦ-40", "Тактико-технические характеристики\n\nМасса: 14 т\nЭкипаж: 6 чел\n"
                                "Объём цистерны: 2400 л\n" * 4)
    cache.save_doc("Прочие сведения", "Текст общих сведений о подразделении.\n" * 5)
    cache.save_doc("Прочие Автомобиль АЦ-40", FAQ_DOC)
    cache.save_doc("Каталог оборудования", "Перечень оборудования.\n" * 3)
    cache.save_doc("МКСС ТТХ", "Характеристики МКСС.\n" * 3)
    cache.save_doc("Прочие МКСС", FAQ_DOC)
    cache.save_doc("ТТХ ОШ СМГ-1", "Характеристики ОШ СМГ-1.\n" * 3)
    cache.save_doc("Прочие ОШ СМГ-1", FAQ_DOC)
    cache.save_sheet("Сети_Автомобиль АЦ-40", SHEET_NETWORKS)
    cache.save_sheet("Ресурсы_Автомобиль АЦ-40", SHEET_NETWORKS)
    cache.save_sheet("Настройки_ОШ СМГ-1", SHEET_NETWORKS)
    cache.save_sheet("Настройки_МКСС", SHEET_NETWORKS)
    cache.save_sheet("Телефоны начальство", SHEET_PHONES)
    cache.save_folder("Автомобиль АЦ-40", [
        {"id": "file_pdf_1", "name": "Схема подключения.pdf", "mimeType": "application/pdf"},
        {"id": "file_img_1", "name": "Фотоgeneral.png", "mimeType": "image/png"},
    ])
    cache.save_folder("МКСС", [{"id": "file_pdf_2", "name": "Антенна.pdf", "mimeType": "application/pdf"}])
    cache.set_last_sync("2026-10-18 12:00")
    return store, cache


def main():
    store, cache = prepare_data()
    os.makedirs(SHOT_DIR, exist_ok=True)
    for name in os.listdir(SHOT_DIR):
        if name.endswith(".png"):
            os.remove(os.path.join(SHOT_DIR, name))

    import main as app_main  # после подготовки данных (KV подгружается при импорте)
    from kivy.clock import Clock
    from kivy.core.window import Window
    from app import nav

    app = app_main.PPUApp()
    # строим настоящий UI приложения, но над подготовленными данными
    app.test_data_dir = DATA_DIR

    shots = []

    def snap(name):
        path = os.path.join(SHOT_DIR, name + ".png")
        try:
            # Window.screenshot пишет png на следующем кадре — шаг и так идёт с задержкой
            Window.screenshot(name=path)
            shots.append(path)
            print("screenshot:", name, flush=True)
        except Exception as exc:
            print("screenshot failed:", name, exc, flush=True)

    sequence = [
        ("01_main_menu", lambda root: None),
        ("02_tech", lambda root: root.open(nav.tech_menu(root.service.settings))),
        ("03_auto_item", lambda root: root.open(
            nav.item_menu(root.service.settings, "Автомобиль АЦ-40", "auto"))),
        ("04_ttx", lambda root: root.open(
            nav.doc_node("📋 ТТХ Автомобиль АЦ-40", "ТТХ АЦ-40"))),
        ("05_faq", lambda root: root.open(nav.faq_node("Автомобиль АЦ-40"))),
        ("06_faq_answer", lambda root: root.open(
            nav.static_node("Как заправить бак?", "Проверить уровень, заправить через горловину А.",
                            "Прочие Автомобиль АЦ-40"))),
        ("07_table", lambda root: root.open(
            nav.table_node("🌐 Сети", "Сети_Автомобиль АЦ-40"))),
        ("08_phones", lambda root: root.open(
            nav.phones_node("☎ Телефоны Начальство", "ТелефоныНач", "Телефоны начальство"))),
        ("09_schemes", lambda root: root.open(nav.schemes_node("Автомобиль АЦ-40"))),
        ("10_settings", lambda root: root.open(nav.settings_node())),
        ("11_back_home", lambda root: root.home()),
    ]

    def step(index):
        if index >= len(sequence):
            finish()
            return

        def run(*_):
            name, action = sequence[index]
            root = app.root_view
            try:
                if action is not None:
                    action(root)
            except Exception as exc:
                print("ERROR on", name, exc)
                import traceback
                traceback.print_exc()
            # кадр должен успеть отрисоваться после перехода
            Clock.schedule_once(lambda *_: snap(name), 0.6)
            Clock.schedule_once(lambda *_: step(index + 1), 1.4)

        Clock.schedule_once(run, 0.5)

    def finish():
        print("\nэкранов проверено:", len(shots))
        app.stop()

    Clock.schedule_once(lambda *_: step(0), 1.5)
    Clock.schedule_once(lambda *_: (print("timeout stop"), app.stop()), 40)
    app.run()


if __name__ == "__main__":
    main()
