"""Действия, специфичные для Android (и их десктоп-заглушки для разработки)."""

import logging
import os
import subprocess
import sys
from typing import Optional

from kivy.utils import platform

logger = logging.getLogger(__name__)

IS_ANDROID = platform == "android"


def _activity():
    """Текущая Activity приложения (для Intent)."""
    from jnius import autoclass
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    return PythonActivity.mActivity


def show_toast(text: str):
    if not text:
        return
    if IS_ANDROID:
        try:
            from jnius import autoclass
            Toast = autoclass('android.widget.Toast')
            activity = _activity()
            Toast.makeText(activity, str(text), Toast.LENGTH_LONG).show()
            return
        except Exception:
            logger.exception("Не удалось показать Toast")
    logger.info("TOAST: %s", text)


def dial_number(phone: str):
    """Позвонить: ACTION_DIAL не требует разрешения CALL_PHONE."""
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit() or ch == '+')
    if not digits:
        show_toast("В номере нет цифр")
        return False
    if IS_ANDROID:
        try:
            from jnius import autoclass
            Intent = autoclass('android.content.Intent')
            Uri = autoclass('android.net.Uri')
            activity = _activity()
            intent = Intent(Intent.ACTION_DIAL, Uri.parse(f"tel:{digits}"))
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            return True
        except Exception as exc:
            logger.error("Не удалось открыть телефон: %s", exc)
            show_toast(f"Не удалось набрать номер: {exc}")
            return False
    logger.info("Desktop: звонок на %s", digits)
    show_toast(f"(десктоп) набор: {digits}")
    return True


def open_external_file(path: str, mime: Optional[str] = None) -> bool:
    """Открыть файл во внешнем приложении (например, в PDF-читалке).

    На Android 7+ запрещено отдавать file:// URI, поэтому сначала пробуем content-URI
    через FileProvider, при неудаче — показываем путь к файлу.
    """
    if not path or not os.path.exists(path):
        show_toast("Файл ещё не скачан")
        return False

    if IS_ANDROID:
        for uri in _candidate_uris(path):
            try:
                _view_intent(uri, mime or _guess_mime(path))
                return True
            except Exception as exc:
                logger.warning("ACTION_VIEW (%s) не удался: %s", uri, exc)
        show_toast(f"Нет приложения для открытия. Файл сохранён: {os.path.basename(path)}")
        return False

    # десктоп: открыть в системном просмотрщике
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception as exc:
        logger.error("Не удалось открыть файл: %s", exc)
        show_toast(f"Не удалось открыть: {exc}")
        return False


def _candidate_uris(path: str):
    """URI, которыми можно попробовать отдать файл внешнему приложению (по порядку)."""
    from jnius import autoclass
    Uri = autoclass('android.net.Uri')
    try:
        activity = _activity()
        File = autoclass('java.io.File')
        provider_class = _file_provider_class()
        if provider_class is not None:
            authority = f"{activity.getPackageName()}.fileprovider"
            yield provider_class.getUriForFile(activity, authority, File(path))
    except Exception as exc:
        logger.debug("FileProvider недоступен: %s", exc)
    # file:// работает только на Android <= 6 или при отключённом StrictMode
    yield Uri.fromFile(autoclass('java.io.File')(path))


def _file_provider_class():
    from jnius import autoclass
    for name in (
        'androidx.core.content.FileProvider',
        'android.support.v4.content.FileProvider',
    ):
        try:
            return autoclass(name)
        except Exception:
            continue
    return None


def _view_intent(uri, mime: str):
    from jnius import autoclass
    Intent = autoclass('android.content.Intent')
    activity = _activity()
    intent = Intent(Intent.ACTION_VIEW)
    intent.setDataAndType(uri, mime)
    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    activity.startActivity(intent)


def _guess_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "application/octet-stream")


def external_downloads_dir() -> Optional[str]:
    """Папка загрузок на внешнем хранилище (доступна без разрешений на Android 10+)."""
    if not IS_ANDROID:
        return None
    try:
        from jnius import autoclass
        activity = _activity()
        Environment = autoclass('android.os.Environment')
        dir_file = activity.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
        return dir_file.getAbsolutePath() if dir_file else None
    except Exception as exc:
        logger.debug("Внешняя папка загрузок недоступна: %s", exc)
        return None
