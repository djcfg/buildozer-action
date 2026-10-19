"""Экраны приложения (Kivy).

Контент строится программно из узлов навигации (см. app.nav), поэтому изменение
состава техники/оборудования не требует правки разметки.
"""

import logging
import os
import shutil
from typing import Dict, List, Optional

from kivy.core.window import Window
from kivy.factory import Factory
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scatter import Scatter
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from . import nav
from .config import PHONE_KEYS
from .parsing import build_contacts, format_record_text, parse_faq, rows_to_records
from .platform_utils import dial_number, open_external_file, show_toast
from .service import PPUService, Result
from .storage import age_text, human_size

logger = logging.getLogger(__name__)

COLOR_PANEL = (0.17, 0.19, 0.24, 1)
COLOR_HEADER = (0.20, 0.25, 0.32, 1)
COLOR_TEXT = (0.93, 0.94, 0.96, 1)
COLOR_MUTED = (0.62, 0.66, 0.72, 1)
COLOR_ACCENT = (0.16, 0.45, 0.68, 1)
COLOR_OK = (0.24, 0.52, 0.30, 1)
COLOR_WARN = (0.66, 0.42, 0.13, 1)
COLOR_ERROR = (0.72, 0.25, 0.22, 1)

H_MARGIN = dp(20)


# ---------------------------------------------------------------- helpers
def make_label(text: str, size: str = '14sp', color=COLOR_TEXT, bold: bool = False,
               halign: str = 'left') -> Label:
    """Многострочный Label, растягивающийся по ширине окна.

    Реагируем ТОЛЬКО на texture_size: привязка к size вызывала рекурсию
    (height -> size -> texture_size -> height).
    """
    widget = Label(
        text=text,
        font_size=size,
        color=color,
        bold=bold,
        halign=halign,
        valign='top',
        markup=True,
        size_hint_y=None,
    )

    def _fit(inst, *_):
        inst.text_size = (max(1, Window.width - H_MARGIN), None)
        inst.height = inst.texture_size[1]

    widget.bind(texture_size=_fit)
    _fit(widget)
    return widget


def make_status_label(height_dp: int = 34) -> Label:
    """Строка статуса: фиксированная высота, длинный текст обрезается многоточием."""
    widget = Label(
        text="",
        font_size=sp(11),
        color=COLOR_MUTED,
        halign='left',
        valign='middle',
        size_hint_y=None,
        height=dp(height_dp),
        shorten=True,
        shorten_from='right',
        max_lines=2,
    )
    # text_size обязательно привязываем к СОБСТВЕННОЙ ширине виджета,
    # иначе текст выйдет за границы виджета и наедет на соседние кнопки
    widget.bind(size=widget.setter('text_size'))
    return widget


def make_button(text: str, on_press, color=COLOR_ACCENT, height: int = 48,
                fixed_width: float = 0) -> Factory.Button:
    widget = Factory.PpuButton(
        text=text,
        size_hint_y=None,
        height=dp(height),
        background_color=color,
    )
    if fixed_width:
        widget.size_hint_x = None
        widget.width = dp(fixed_width)
    widget.bind(on_release=lambda _inst: on_press())
    return widget


def spacer(height: int = 8) -> BoxLayout:
    return BoxLayout(size_hint_y=None, height=dp(height))


# ---------------------------------------------------------------- base screen
class BaseScreen(Screen):
    def __init__(self, root: "Root", **kwargs):
        super().__init__(**kwargs)
        self.root_app = root
        self.node: Dict = {}
        self.force_refresh = False

        layout = BoxLayout(orientation='vertical', size_hint=(1, 1),
                           spacing=dp(4), padding=dp(8))

        top = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(44), spacing=dp(6))
        self.back_btn = make_button("‹ Назад", root.back, COLOR_PANEL, height=44, fixed_width=92)
        top.add_widget(self.back_btn)
        self.title_label = Label(text="", font_size=sp(17), bold=True, color=COLOR_TEXT,
                                 halign='left', valign='middle')
        self.title_label.bind(size=self.title_label.setter('text_size'))
        top.add_widget(self.title_label)
        self.refresh_btn = make_button("🔄", self._do_refresh, COLOR_PANEL, height=44, fixed_width=52)
        top.add_widget(self.refresh_btn)
        layout.add_widget(top)

        self.status_label = make_status_label()
        layout.add_widget(self.status_label)

        self.scroll = ScrollView(do_scroll_x=False, bar_width=dp(3))
        self.content = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4))
        self.content.bind(minimum_height=self.content.setter('height'))
        self.scroll.add_widget(self.content)
        layout.add_widget(self.scroll)

        self.add_widget(layout)

    def _do_refresh(self):
        self.force_refresh = True
        self.render(dict(self.node))

    def set_status(self, text: str, color=COLOR_MUTED):
        self.status_label.text = text
        self.status_label.color = color

    def clear_content(self):
        self.content.clear_widgets()

    def add(self, widget):
        self.content.add_widget(widget)

    def show_message(self, text: str, error: bool = False):
        self.clear_content()
        self.add(make_label(text, '14sp', COLOR_ERROR if error else COLOR_TEXT))

    def render(self, node: Dict):
        raise NotImplementedError


# ---------------------------------------------------------------- menu
class MenuScreen(BaseScreen):
    def render(self, node: Dict):
        self.node = node
        self.force_refresh = False
        self.refresh_btn.disabled = True
        self.refresh_btn.opacity = 0.3
        self.title_label.text = node.get("title", "")
        self.set_status("")
        self.clear_content()

        entries: List = node.get("entries", [])
        if not entries:
            self.add(make_label(
                "Здесь пока ничего нет — заполните списки техники/оборудования "
                "на экране «⚙ Настройки».", '14sp', COLOR_WARN))

        for text, child in entries:
            self.add(make_button(text, lambda child=child: self.root_app.open(child),
                                 COLOR_ACCENT, height=50))

        if node.get("hint"):
            self.add(spacer(10))
            self.add(make_label(f"Раздел: {node['hint']}", '11sp', COLOR_MUTED))


# ---------------------------------------------------------------- document text
class TextScreen(BaseScreen):
    def render(self, node: Dict):
        self.node = node
        self.refresh_btn.disabled = False
        self.refresh_btn.opacity = 1
        self.title_label.text = node.get("title", "")
        self.clear_content()

        static_text = node.get("static_text")
        if static_text is not None:
            self.set_status(f"Фрагмент документа «{node.get('doc', '')}»")
            self.add(make_label(static_text.strip() or "(нет текста)", '14sp'))
            return

        doc_name = (node.get("doc") or "").strip()
        if not doc_name:
            self.set_status("")
            self.show_message(
                "Документ не настроен.\n\nОткройте «⚙ Настройки» и укажите имя Google Doc "
                "для этой позиции (или импортируйте значения из .env).", error=True)
            return

        self.set_status("⏳ Обновляю из Google…" if self.force_refresh else "⏳ Загрузка…")
        self.root_app.service.get_doc(doc_name, force=self.force_refresh, on_done=self._on_doc)
        self.force_refresh = False

    def _on_doc(self, result: Result):
        if not result.ok:
            self.set_status("⚠ " + (result.error or "Ошибка"), COLOR_ERROR)
            self.show_message(f"Не удалось загрузить документ:\n\n{result.error}", error=True)
            return

        text = result.value or ""
        self.set_status(
            f"{'📦 из кэша' if result.source == 'cache' else '🌐 загружено'} · "
            f"{age_text(result.ts)} · {len(text)} симв.",
            COLOR_OK if result.source == 'net' else COLOR_MUTED)
        self.clear_content()
        self.add(make_label(text.strip() or "(документ пустой)", '14sp'))


# ---------------------------------------------------------------- faq
class FaqScreen(BaseScreen):
    def render(self, node: Dict):
        self.node = node
        self.refresh_btn.disabled = False
        self.refresh_btn.opacity = 1
        self.title_label.text = node.get("title", "")
        self.clear_content()

        item = node.get("item", "")
        doc_name = self.root_app.service.settings.faq_doc_name(item)
        self.set_status("⏳ Загрузка списка вопросов…")
        self.root_app.service.get_doc(doc_name, force=self.force_refresh, on_done=self._on_doc)
        self.force_refresh = False

    def _on_doc(self, result: Result):
        if not result.ok:
            self.set_status("⚠ " + (result.error or "Ошибка"), COLOR_ERROR)
            self.show_message(
                f"Не удалось загрузить «Прочие сведения»:\n\n{result.error}", error=True)
            return

        content = result.value or ""
        sections = parse_faq(content)
        source = f"{'📦 из кэша' if result.source == 'cache' else '🌐 загружено'} · {age_text(result.ts)}"
        self.clear_content()

        if not sections:
            # заголовков *** нет — показываем документ целиком, как делал бот
            self.set_status(source + " · заголовки вопросов не найдены, показан весь текст")
            self.add(make_label(content.strip() or "(документ пустой)", '14sp'))
            return

        self.set_status(f"{source} · вопросов: {len(sections)}")
        self.add(make_label("Выберите вопрос, чтобы посмотреть ответ:", '12sp', COLOR_MUTED))
        for title, body in sections:
            display = title if len(title) <= 70 else title[:67] + "…"
            self.add(make_button("▫ " + display,
                                 lambda title=title, body=body: self.root_app.open(
                                     nav.static_node(title, body, self.node.get("item", ""))),
                                 COLOR_PANEL, height=46))


# ---------------------------------------------------------------- table
class TableScreen(BaseScreen):
    def render(self, node: Dict):
        self.node = node
        self.refresh_btn.disabled = False
        self.refresh_btn.opacity = 1
        self.title_label.text = node.get("title", "")
        self.clear_content()

        sheet = (node.get("sheet") or "").strip()
        if not sheet:
            self.show_message("Имя листа не задано.", error=True)
            return

        self.set_status("⏳ Загрузка таблицы…")
        self.root_app.service.get_sheet(sheet, force=self.force_refresh, on_done=self._on_rows)
        self.force_refresh = False

    def _on_rows(self, result: Result):
        sheet = self.node.get("sheet", "")
        if not result.ok:
            self.set_status("⚠ " + (result.error or "Ошибка"), COLOR_ERROR)
            self.show_message(f"Не удалось загрузить лист «{sheet}»:\n\n{result.error}", error=True)
            return

        headers, records = rows_to_records(result.value or [])
        source = f"{'📦 из кэша' if result.source == 'cache' else '🌐 загружено'} · {age_text(result.ts)}"
        self.clear_content()

        if not records:
            self.set_status(source)
            self.show_message(f"Данные в листе «{sheet}» не найдены.")
            return

        self.set_status(f"{source} · записей: {len(records)}")
        self.add(make_label(" · ".join(h for h in headers if h), '11sp', COLOR_MUTED))
        for index, record in enumerate(records, start=1):
            self.add(make_label(f"🔹 {index}", '12sp', COLOR_MUTED, bold=True))
            self.add(make_label(format_record_text(record), '14sp'))
            self.add(spacer(10))


# ---------------------------------------------------------------- phones
class PhonesScreen(BaseScreen):
    def render(self, node: Dict):
        self.node = node
        self.refresh_btn.disabled = False
        self.refresh_btn.opacity = 1
        self.title_label.text = node.get("title", "")
        self.clear_content()

        sheet = (node.get("sheet") or "").strip()
        if not sheet:
            self.show_message("Лист справочника не задан в настройках.", error=True)
            return

        self.set_status("⏳ Загрузка справочника…")
        self.root_app.service.get_sheet(sheet, force=self.force_refresh, on_done=self._on_rows)
        self.force_refresh = False

    def _on_rows(self, result: Result):
        if not result.ok:
            self.set_status("⚠ " + (result.error or "Ошибка"), COLOR_ERROR)
            self.show_message(f"Не удалось загрузить справочник:\n\n{result.error}", error=True)
            return

        contacts = build_contacts(result.value or [])
        source = f"{'📦 из кэша' if result.source == 'cache' else '🌐 загружено'} · {age_text(result.ts)}"
        self.clear_content()

        if not contacts:
            self.set_status(source)
            self.show_message("Нет данных для отображения.")
            return

        self.set_status(f"{source} · записей: {len(contacts)}")
        for contact in contacts:
            self.add(make_label(f"👤 {contact['title']}", '15sp', COLOR_TEXT, bold=True))
            for line in contact.get("lines", []):
                self.add(make_label("    " + line, '12sp', COLOR_MUTED))
            display = contact.get("phone_display") or ""
            phone = contact.get("phone") or ""
            if phone:
                self.add(make_button(f"📞 {display}", lambda phone=phone: dial_number(phone),
                                     COLOR_OK, height=44))
            elif display:
                self.add(make_label(f"📞 {display} (в номере нет цифр)", '13sp', COLOR_MUTED))
            self.add(spacer(12))


# ---------------------------------------------------------------- schemes
class SchemesScreen(BaseScreen):
    def render(self, node: Dict):
        self.node = node
        self.refresh_btn.disabled = False
        self.refresh_btn.opacity = 1
        self.title_label.text = node.get("title", "")
        self.clear_content()

        folder = (node.get("folder") or "").strip()
        if not folder:
            self.show_message("Имя папки в Google Drive не задано.", error=True)
            return

        self.set_status("⏳ Получение списка файлов…")
        self.root_app.service.get_folder(folder, force=self.force_refresh, on_done=self._on_files)
        self.force_refresh = False

    def _on_files(self, result: Result):
        folder = self.node.get("folder", "")
        if not result.ok:
            self.set_status("⚠ " + (result.error or "Ошибка"), COLOR_ERROR)
            self.show_message(f"Не удалось получить список файлов:\n\n{result.error}", error=True)
            return

        files = result.value or []
        source = f"{'📦 из кэша' if result.source == 'cache' else '🌐 загружено'} · {age_text(result.ts)}"
        self.clear_content()

        if not files:
            self.set_status(source)
            self.show_message(f"Фото/документы в папке «{folder}» не найдены.")
            return

        cached = sum(1 for info in files if self.root_app.service.cached_media(info.get("id", "")))
        self.set_status(f"{source} · файлов: {len(files)}, скачано: {cached}")
        self.add(make_button(f"⬇ Кэшировать все файлы ({len(files)})",
                             lambda: self._cache_all(folder), COLOR_WARN, height=46))
        self.add(spacer(8))

        for info in files:
            self.add(self._file_row(info))

    def _file_row(self, info: Dict):
        entry = self.root_app.service.cached_media(info.get("id", ""))
        name = info.get("name", "без имени")
        display = name if len(name) <= 48 else name[:45] + "…"
        mime = info.get("mimeType", "")
        if "image/" in mime or name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            emoji = "🖼"
        elif "pdf" in mime.lower() or name.lower().endswith(".pdf"):
            emoji = "📄"
        else:
            emoji = "📁"

        row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(52), spacing=dp(6))
        caption = Label(
            text=f"{emoji} {display}\n[{'✅ в кэше' if entry else '☁ не кэширован'}]",
            markup=True, font_size=sp(13), color=COLOR_TEXT, halign='left', valign='middle',
        )
        caption.bind(size=caption.setter('text_size'))
        row.add_widget(caption)
        row.add_widget(make_button("Открыть" if entry else "Скачать",
                                   lambda info=info: self._open_file(info),
                                   COLOR_OK if entry else COLOR_ACCENT,
                                   height=48, fixed_width=104))
        return row

    def _open_file(self, info: Dict):
        service = self.root_app.service
        existing = service.cached_media(info.get("id", ""))
        if existing:
            self._show_file(existing)
            return

        self.root_app.set_status(f"⬇ Скачиваю {info.get('name', '')}…")
        service.download_media(info, on_done=lambda result: self._on_downloaded(info, result))

    def _on_downloaded(self, info: Dict, result: Result):
        if not result.ok:
            self.set_status("⚠ Не удалось скачать файл: " + (result.error or ""), COLOR_ERROR)
            show_toast("Файл не скачан")
            return
        self._show_file(result.value)
        self.render(dict(self.node))

    def _show_file(self, entry: Dict):
        path = entry.get("path", "")
        mime = entry.get("mime", "")
        if not path or not os.path.exists(path):
            show_toast("Файл не найден на устройстве")
            return
        if mime.startswith("image/") or os.path.splitext(path)[1].lower() in (
                ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
            self.root_app.open({"screen": "image", "title": entry.get("name", "Схема"),
                                "path": path, "mime": mime})
        elif not open_external_file(path, mime):
            self.set_status(f"Файл сохранён: {path}")

    def _cache_all(self, folder: str):
        root = self.root_app
        if root.busy:
            show_toast("Дождитесь окончания текущей загрузки")
            return
        root.busy = True
        self.set_status("⬇ Кэширую файлы…")

        def on_progress(done, total, text):
            root.set_status(f"⬇ [{done}/{total}] {text}")

        def on_done(result: Result):
            root.busy = False
            if result.ok:
                stats = result.value
                message = f"✅ Скачано {stats['ok']} из {stats['total']} файлов"
                if stats["failed"]:
                    message += f", ошибок: {stats['failed']}"
                root.set_status(message)
                show_toast(message)
            else:
                self.set_status("⚠ " + (result.error or ""), COLOR_ERROR)
            self.render(dict(self.node))

        root.service.cache_folder_media(folder, on_progress, on_done)


# ---------------------------------------------------------------- image viewer
class ImageScreen(BaseScreen):
    def render(self, node: Dict):
        self.node = node
        self.refresh_btn.disabled = True
        self.refresh_btn.opacity = 0.3
        self.title_label.text = node.get("title", "")
        path = node.get("path", "")
        self.set_status(f"Щипок — масштаб. Файл: {os.path.basename(path)}")
        self.clear_content()

        if not path or not os.path.exists(path):
            self.show_message("Файл не найден", error=True)
            return

        holder = BoxLayout(size_hint=(1, 1))
        image = Image(source=path, nocache=True, size_hint=(None, None))

        def _fit(inst, *_):
            if not inst.texture:
                return
            tex_w, tex_h = inst.texture.size
            available_w = Window.width - H_MARGIN
            available_h = Window.height - dp(200)
            ratio = min(available_w / tex_w, available_h / tex_h, 1.0)
            inst.size = (tex_w * ratio, tex_h * ratio)

        image.bind(texture=_fit)
        scatter = Scatter(do_rotation=False, do_scale=True, do_translation=True,
                          scale_min=0.3, scale_max=6.0)
        scatter.add_widget(image)
        holder.add_widget(scatter)

        self.add(holder)
        self.add(make_button("📂 Открыть в другом приложении",
                             lambda: open_external_file(path, node.get("mime")),
                             COLOR_PANEL, height=46))


# ---------------------------------------------------------------- settings
class SettingsScreen(BaseScreen):
    def render(self, node: Dict):
        self.node = node
        self.refresh_btn.disabled = True
        self.refresh_btn.opacity = 0.3
        self.title_label.text = "⚙ Настройки"
        self.clear_content()
        self._inputs: Dict[str, TextInput] = {}

        settings = self.root_app.service.settings

        self.add(make_label(
            "Настройки хранятся в settings.json в папке приложения — пересобирать APK не нужно. "
            "После изменений: «Сохранить» → «Полная синхронизация».", '12sp', COLOR_MUTED))

        self._section("Списки (через ; или с новой строки)")
        self._field("AUTOS", "Техника (AUTOS)", settings.raw.get("AUTOS", ""), multiline=True)
        self._field("EQUIPMENTS", "Оборудование (EQUIPMENTS)", settings.raw.get("EQUIPMENTS", ""), multiline=True)
        self._field("VKS_TVS", "ВКС комплекты (VKS_TVS)", settings.raw.get("VKS_TVS", ""), multiline=True)

        self._section("Документы и таблица")
        self._field("OBSCHIE_SVED", "Документ «Общие сведения»", settings.general_doc)
        self._field("FAQ_PREFIX", "Префикс документов «Прочие …»", settings.faq_doc)
        self._field("SPREADSHEET_NAME", "Имя таблицы Google Sheets", settings.spreadsheet_name)
        for key, caption, _default in PHONE_KEYS:
            self._field(f"PHONES.{key}", caption, settings.sheet_for_phone(key))

        self._section("Имена Google Docs по позициям")
        for item in settings.all_items:
            self._field(f"DOC.{item}", item, settings.doc_name(item))

        self._section("Доступ к Google (service account)")
        self._field("CREDENTIALS_FILE", "Путь к credentials.json", settings.credentials_file)
        self.add(make_button("📂 Выбрать credentials.json на устройстве",
                             self._pick_credentials, COLOR_PANEL, height=46))

        self._section("Действия")
        self.add(make_button("💾 Сохранить настройки", self._save, COLOR_OK, height=50))
        self.add(make_button("📥 Импорт из .env", self._import_env, COLOR_PANEL, height=46))
        self.add(make_button("🔄 Полная синхронизация (текст + таблицы)",
                             lambda: self.root_app.run_action("sync"), COLOR_ACCENT, height=46))
        self.add(make_button("🗑 Очистить кэш", self._clear_cache, COLOR_WARN, height=46))

        self._section("Состояние кэша")
        self.add(make_label(self._stats_text(self.root_app.service.stats()), '12sp', COLOR_MUTED))

    @staticmethod
    def _stats_text(stats: Dict) -> str:
        return (
            f"Документов: {stats['docs']} · листов: {stats['sheets']} · "
            f"списков файлов: {stats['folders']} · медиа: {stats['media']} "
            f"({human_size(stats['media_bytes'])}).\n"
            f"Размер кэша: {human_size(stats['cache_bytes'])}. "
            f"Синхронизация: {stats['last_sync'] or 'не выполнялась'}.\n"
            f"Папка кэша: {stats['cache_dir']}"
        )

    def _section(self, title: str):
        self.add(spacer(14))
        self.add(make_label(title.upper(), '13sp', COLOR_MUTED, bold=True))

    def _field(self, key: str, caption: str, value: str, multiline: bool = False):
        self.add(make_label(caption, '11sp', COLOR_MUTED))
        field = TextInput(
            text=str(value or ""),
            size_hint_y=None,
            height=dp(96 if multiline else 42),
            multiline=multiline,
            font_size=sp(14),
            foreground_color=COLOR_TEXT,
            background_color=COLOR_HEADER,
            hint_text="не задано",
            hint_text_color=(0.45, 0.50, 0.56, 1),
            cursor_color=COLOR_TEXT,
        )
        self._inputs[key] = field
        self.add(field)
        self.add(spacer(4))

    def _save(self):
        data = self.root_app.store.data
        values = {key: field.text.strip() for key, field in self._inputs.items()}

        for key in ("AUTOS", "EQUIPMENTS", "VKS_TVS", "OBSCHIE_SVED",
                    "FAQ_PREFIX", "SPREADSHEET_NAME", "CREDENTIALS_FILE"):
            if key in values:
                data[key] = values[key]

        phones = data.setdefault("PHONES", {})
        docs = data.setdefault("DOC_NAMES", {})
        for key, value in values.items():
            if key.startswith("PHONES."):
                phones[key.split(".", 1)[1]] = value
            elif key.startswith("DOC."):
                item = key.split(".", 1)[1]
                if value:
                    docs[item] = value
                else:
                    docs.pop(item, None)

        try:
            self.root_app.store.save()
        except Exception as exc:
            self.set_status(f"⚠ Не сохранено: {exc}", COLOR_ERROR)
            show_toast("Настройки не сохранены")
            return

        self.root_app.invalidate_client()
        self.set_status("✅ Сохранено", COLOR_OK)
        show_toast("Настройки сохранены")
        self.render(self.node)

    def _pick_credentials(self):
        from kivy.uix.filechooser import FileChooserListView

        start_path = os.path.expanduser("~")
        for candidate in ("/storage/emulated/0/Download", "/sdcard/Download",
                          self.root_app.base_dir, start_path):
            if os.path.isdir(candidate):
                start_path = candidate
                break

        box = BoxLayout(orientation='vertical', spacing=dp(6))
        chooser = FileChooserListView(path=start_path, size_hint=(1, 1),
                                      filters=lambda d, f: [n for n in f if not n.startswith('.')] or f)
        box.add_widget(chooser)

        popup = Popup(title="Выберите credentials.json", content=box, size_hint=(0.95, 0.9))

        def do_pick(*_):
            selection = chooser.selection
            if not selection:
                show_toast("Файл не выбран")
                return
            src = str(selection[0] if not isinstance(selection[0], (list, tuple)) else selection[0][0])
            if os.path.isdir(src):
                show_toast("Нужен файл, а не папка")
                return
            dest = os.path.join(self.root_app.base_dir, "credentials.json")
            try:
                if os.path.abspath(src) != os.path.abspath(dest):
                    shutil.copy(src, dest)
                self.root_app.store.data["CREDENTIALS_FILE"] = dest
                self.root_app.store.save()
            except Exception as exc:
                show_toast(f"Не удалось скопировать: {exc}")
                return
            self.root_app.invalidate_client()
            popup.dismiss()
            show_toast("credentials.json скопирован в папку приложения")
            self.render(self.node)

        row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(44), spacing=dp(6))
        row.add_widget(make_button("✔ Выбрать", do_pick, COLOR_OK, height=44))
        row.add_widget(make_button("Отмена", popup.dismiss, COLOR_PANEL, height=44))
        box.add_widget(row)
        popup.open()

    def _import_env(self):
        box = BoxLayout(orientation='vertical', spacing=dp(6))
        field = TextInput(hint_text="Вставьте содержимое .env (AUTOS=…; DOC_…=…)",
                          font_size=sp(13), foreground_color=COLOR_TEXT,
                          background_color=COLOR_HEADER, cursor_color=COLOR_TEXT)
        box.add_widget(field)

        popup = Popup(title="Импорт из .env", content=box, size_hint=(0.95, 0.85))

        def do_import(*_):
            try:
                stats = self.root_app.store.import_env(field.text)
            except Exception as exc:
                show_toast(f"Ошибка разбора: {exc}")
                return
            popup.dismiss()
            self.root_app.invalidate_client()
            show_toast(f"Импортировано: списков {stats['lists']}, "
                       f"документов {stats['docs']}, прочего {stats['other']}")
            self.render(self.node)

        def load_file(*_):
            for candidate in (
                os.path.join(self.root_app.base_dir, ".env"),
                os.path.join(os.path.dirname(self.root_app.base_dir), ".env"),
                os.path.join(os.path.dirname(os.path.dirname(self.root_app.base_dir)), ".env"),
            ):
                if os.path.isfile(candidate):
                    try:
                        with open(candidate, "r", encoding="utf-8") as handle:
                            field.text = handle.read()
                        show_toast("Файл .env загружен")
                    except Exception as exc:
                        show_toast(f"Не прочитан: {exc}")
                    return
            show_toast(".env рядом с приложением не найден — вставьте текст вручную")

        row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(44), spacing=dp(6))
        row.add_widget(make_button("Импорт", do_import, COLOR_OK, height=44))
        row.add_widget(make_button("Из файла", load_file, COLOR_PANEL, height=44))
        row.add_widget(make_button("Отмена", popup.dismiss, COLOR_PANEL, height=44))
        box.add_widget(row)
        popup.open()

    def _clear_cache(self):
        box = BoxLayout(orientation='vertical', spacing=dp(6))
        box.add_widget(make_label(
            "Тексты и таблицы можно загрузить снова кнопкой синхронизации. "
            "Скачанные фото/PDF удаляются с устройства.", '13sp', COLOR_TEXT))
        popup = Popup(title="Очистка кэша", content=box, size_hint=(0.9, 0.5))

        def make_clear(what):
            def handler(*_):
                removed = self.root_app.service.clear_cache(what)
                popup.dismiss()
                show_toast(f"Удалено записей: {removed}")
                self.render(self.node)
            return handler

        row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(46), spacing=dp(6))
        row.add_widget(make_button("Текст/таблицы", make_clear("text"), COLOR_WARN, height=46))
        row.add_widget(make_button("Медиа", make_clear("media"), COLOR_WARN, height=46))
        row.add_widget(make_button("Всё", make_clear("all"), COLOR_ERROR, height=46))
        box.add_widget(row)
        popup.open()


# ---------------------------------------------------------------- root
class Root(BoxLayout):
    """Контейнер: менеджер экранов + нижняя панель (дом/статус/синхронизация/настройки)."""

    def __init__(self, service: PPUService, store, base_dir: str, **kwargs):
        super().__init__(orientation='vertical', size_hint=(1, 1), **kwargs)
        self.service = service
        self.store = store
        self.base_dir = base_dir
        self.busy = False
        self.stack: List[Dict] = []

        self.sm = ScreenManager(transition=SlideTransition(duration=0.12))
        self.screens: Dict[str, BaseScreen] = {
            "menu": MenuScreen(root=self, name="menu"),
            "text": TextScreen(root=self, name="text"),
            "faq": FaqScreen(root=self, name="faq"),
            "table": TableScreen(root=self, name="table"),
            "phones": PhonesScreen(root=self, name="phones"),
            "schemes": SchemesScreen(root=self, name="schemes"),
            "image": ImageScreen(root=self, name="image"),
            "settings": SettingsScreen(root=self, name="settings"),
        }
        for screen in self.screens.values():
            self.sm.add_widget(screen)
        self.add_widget(self.sm)

        bar = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(54),
                        spacing=dp(4), padding=dp(4))
        bar.add_widget(make_button("🏠", self.home, COLOR_PANEL, height=48, fixed_width=56))
        self.status_label = make_status_label(height_dp=54)
        bar.add_widget(self.status_label)
        bar.add_widget(make_button("🔄", lambda: self.run_action("sync"), COLOR_PANEL,
                                   height=48, fixed_width=56))
        bar.add_widget(make_button("⚙", lambda: self.open(nav.settings_node()), COLOR_PANEL,
                                   height=48, fixed_width=56))
        self.add_widget(bar)

    # ---------- навигация ----------
    def open(self, node: Dict):
        if node.get("screen") == "action":
            self.run_action(node.get("action"))
            return

        screen = self.screens.get(node.get("screen"))
        if screen is None:
            logger.warning("Неизвестный экран: %s", node.get("screen"))
            return

        if self.stack and self.stack[-1] == node:
            screen.render(node)
            return

        self.stack.append(node)
        self.sm.transition.direction = 'left'
        self.sm.current = node.get("screen")
        screen.render(node)

    def back(self):
        if len(self.stack) > 1:
            self.stack.pop()
        else:
            self.home()
            return
        node = self.stack[-1]
        self.sm.transition.direction = 'right'
        self.sm.current = node.get("screen")
        self.screens[node.get("screen")].render(node)

    def home(self):
        self.stack = [nav.main_menu(self.service.settings)]
        self.sm.transition.direction = 'right'
        self.sm.current = "menu"
        self.screens["menu"].render(self.stack[0])
        self.refresh_status_line()

    def refresh_status_line(self):
        stats = self.service.stats()
        if not self.service.credentials_ready():
            self.set_status("⚠ credentials.json не настроены — откройте ⚙ Настройки")
            return
        self.set_status(
            f"Офлайн-копия: документов {stats['docs']}, листов {stats['sheets']}, "
            f"файлов {stats['media']}. Синхронизация: {stats['last_sync'] or 'не выполнялась'}"
        )

    def set_status(self, text: str):
        self.status_label.text = text

    def invalidate_client(self):
        """После изменения настроек учётные данные/таблицу перечитываем."""
        self.service._client = None
        self.service._client_signature = ("", "")

    # ---------- действия ----------
    def run_action(self, action: Optional[str]):
        if action != "sync":
            return
        if self.busy:
            show_toast("Дождитесь окончания синхронизации")
            return
        if not self.service.credentials_ready():
            show_toast("Сначала укажите credentials.json")
            self.open(nav.settings_node())
            return

        self.busy = True
        total = len(self.service.sync_plan())
        self.set_status(f"🔄 Синхронизация: объектов {total}…")

        def on_progress(done, done_total, text):
            self.set_status(f"🔄 [{done}/{done_total}] {text}")

        def on_done(result: Result):
            self.busy = False
            if result.ok:
                stats = result.value
                message = (f"✅ Синхронизировано {stats['ok']} из {stats['total']}"
                           f" (нет в Drive: {stats['missed']}, ошибок: {stats['failed']})")
                show_toast(message)
            else:
                message = "⚠ Синхронизация не удалась: " + (result.error or "")
            self.set_status(message)
            self._rerender_current()

        self.service.sync_all(on_progress, on_done)

    def _rerender_current(self):
        screen = self.screens.get(self.sm.current)
        if screen is not None and screen.node:
            screen.render(dict(screen.node))
        else:
            self.home()
