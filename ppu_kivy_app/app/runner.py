"""Фоновое выполнение сетевых задач.

UI Kivy нельзя блокировать, а запросы к Google синхронные. Поэтому работа идёт
в пуле потоков, а результаты передаются в UI-поток через `kivy.clock.Clock.schedule_once`
(документированный способ межпоточного взаимодействия Kivy, работает и на Android).

Для автотестов без запущенного event loop способ доставки можно подменить
через `set_ui_poster()` (см. tests/smoke_test.py).
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:  # в окружении без Kivy (тесты ядра) откатываемся к прямому вызову
    from kivy.clock import Clock
    _HAS_KIVY = True
except Exception:  # pragma: no cover
    Clock = None
    _HAS_KIVY = False


def _clock_poster(action: Callable):
    if _HAS_KIVY:
        Clock.schedule_once(lambda _dt: action())
    else:
        action()


_poster = _clock_poster


def set_ui_poster(poster: Optional[Callable]):
    """Переопределить способ возврата колбэка в поток UI (для тестов)."""
    global _poster
    _poster = poster or _clock_poster


def in_ui_thread(func: Optional[Callable]) -> Optional[Callable]:
    """Обернуть колбэк так, чтобы он был вызван в поток UI."""
    if func is None:
        return None

    def wrapper(*args):
        poster = _poster
        try:
            poster(lambda: func(*args))
        except Exception:
            logger.exception("Не удалось передать колбэк в UI-поток")

    return wrapper


class Runner:
    def __init__(self, max_workers: int = 3):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ppu-net")
        self._pending = 0
        self._cond = threading.Condition()

    def submit(self, work: Callable, on_success: Callable = None, on_error: Callable = None):
        """Выполнить `work()` в фоне; результат или исключение — в UI-потоке."""
        success_cb = in_ui_thread(on_success)
        error_cb = in_ui_thread(on_error)

        with self._cond:
            self._pending += 1

        def task():
            try:
                result = work()
            except Exception as exc:
                logger.exception("Фоновая задача завершилась ошибкой")
                if error_cb:
                    error_cb(exc)
            else:
                if success_cb:
                    success_cb(result)
            finally:
                with self._cond:
                    self._pending -= 1
                    self._cond.notify_all()

        self._pool.submit(task)

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Дождаться завершения всех фоновых задач (используется в тестах)."""
        with self._cond:
            return self._cond.wait_for(lambda: self._pending == 0, timeout=timeout)

    def shutdown(self):
        try:
            self._pool.shutdown(wait=False)
        except Exception:
            pass
