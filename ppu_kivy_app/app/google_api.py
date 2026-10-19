"""Доступ к Google Docs / Sheets / Drive.

В боте (main3.py) использовались gspread + httpx. Для APK-приложения:
  * зависимости упрощены до `requests` (есть готовый recipe для python-for-android,
    и он не требует event loop — все сетевые вызовы выполняются в фоновых потоках);
  * чтение таблиц переведено на REST Sheets API (gspread не нужен);
  * права — только read-only.

Все методы синхронные и вызываются ТОЛЬКО из фоновых потоков (см. app.runner.Runner).
"""

import logging
import os
import re
import threading
from typing import Dict, List, Optional
from urllib.parse import quote

import requests
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
MIME_DOC = "application/vnd.google-apps.document"
MIME_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_FOLDER = "application/vnd.google-apps.folder"

FILE_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{20,}$')


class GoogleApiError(Exception):
    """Ошибка доступа к Google API (неверные credentials, нет файла/листа, нет сети)."""


def _ca_bundle() -> Optional[str]:
    """Путь к хранилищу корневых сертификатов (на Android его надо указывать явно)."""
    for env in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        path = os.environ.get(env)
        if path and os.path.exists(path):
            return path
    try:
        import certifi
        return certifi.where()
    except Exception:
        return None


class GoogleApiClient:
    """Клиент Google API для service account."""

    def __init__(self, credentials_file: str, spreadsheet_name: str = "ppu_info"):
        if not credentials_file or not os.path.exists(credentials_file):
            raise GoogleApiError(
                "Файл credentials.json не найден. Укажите его на экране «Настройки»."
            )
        self.credentials_file = credentials_file
        self.spreadsheet_name = spreadsheet_name
        self._creds = None
        self._lock = threading.Lock()
        self._spreadsheet_id: Optional[str] = None
        self._verify = _ca_bundle()

    # ---------------- токен ----------------
    def _ensure_creds(self):
        with self._lock:
            if self._creds is None:
                try:
                    self._creds = service_account.Credentials.from_service_account_file(
                        self.credentials_file, scopes=SCOPES
                    )
                except Exception as exc:
                    raise GoogleApiError(f"Не удалось прочитать credentials.json: {exc}") from exc
            if self._creds.expired or not self._creds.valid:
                try:
                    self._creds.refresh(_GoogleRequest())
                except Exception as exc:
                    raise GoogleApiError(f"Google не принял учётные данные: {exc}") from exc
            return self._creds.token

    def _get(self, url: str, params: dict = None, stream=False, allow_redirects=True):
        token = self._ensure_creds()
        headers = {'Authorization': f'Bearer {token}'}
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=60,
                stream=stream,
                allow_redirects=allow_redirects,
                verify=self.verify if self.verify else True,
            )
        except requests.RequestException as exc:
            raise GoogleApiError(f"Сетевая ошибка: {exc}") from exc
        if response.status_code in (401, 403):
            raise GoogleApiError(
                f"Доступ запрещён (HTTP {response.status_code}). "
                f"Проверьте, что у service account есть доступ к документу/таблице."
            )
        if response.status_code == 404:
            raise GoogleApiError("Не найдено (HTTP 404).")
        if not response.ok:
            raise GoogleApiError(f"HTTP {response.status_code}: {response.text[:200]}")
        return response

    # ---------------- поиск файлов ----------------
    def _search(self, query: str, fields: str = "files(id, name, mimeType)") -> List[Dict]:
        params = {
            'q': query,
            'fields': fields,
            'supportsAllDrives': 'true',
            'includeItemsFromAllDrives': 'true',
        }
        response = self._get(DRIVE_FILES, params)
        return response.json().get('files', [])

    def find_file_id(self, name_or_id: str, mime_type: str) -> str:
        """ID файла по имени (или сам ID, если передали похожее на ID значение)."""
        candidate = (name_or_id or "").strip()
        if not candidate:
            raise GoogleApiError("Не задано имя документа.")
        if FILE_ID_RE.match(candidate) and mime_type != MIME_FOLDER:
            return candidate
        files = self._search(f"name = '{candidate}' and mimeType = '{mime_type}' and trashed = false")
        if not files:
            raise GoogleApiError(f"Документ «{candidate}» не найден в Google Drive.")
        if len(files) > 1:
            logger.warning("Несколько файлов с именем %s, беру первый", candidate)
        return files[0]['id']

    def spreadsheet_id(self) -> str:
        if not self._spreadsheet_id:
            self._spreadsheet_id = self.find_file_id(self.spreadsheet_name, MIME_SHEET)
        return self._spreadsheet_id

    # ---------------- документы ----------------
    def fetch_doc_text(self, name_or_id: str) -> str:
        """Текст Google Docs: сначала REST export, затем резервный URL экспорта."""
        doc_id = self.find_file_id(name_or_id, MIME_DOC)
        try:
            response = self._get(
                f"{DRIVE_FILES}/{doc_id}/export",
                {'mimeType': 'text/plain', 'supportsAllDrives': 'true'},
            )
            return self._decode(response.content)
        except GoogleApiError as first_error:
            logger.warning("Drive export не сработал (%s), пробую docs.google.com", first_error)

        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        try:
            response = self._get(export_url)
            return self._decode(response.content)
        except GoogleApiError as second_error:
            raise GoogleApiError(
                f"Не удалось загрузить документ «{name_or_id}»: {second_error}"
            ) from second_error

    @staticmethod
    def _decode(raw: bytes) -> str:
        for enc in ("utf-8", "cp1251"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    # ---------------- таблицы ----------------
    def fetch_sheet_rows(self, title: str) -> List[List[str]]:
        sid = self.spreadsheet_id()
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{quote(title, safe='')}?majorDimension=ROWS"
        rows = self._get(url).json().get('values', [])
        return [[str(cell) for cell in row] for row in rows]

    # ---------------- файлы в папке ----------------
    def list_folder_media(self, folder_name: str) -> List[Dict]:
        """Фото/PDF из папки Drive с точным именем (как search_files_in_drive в боте)."""
        folders = self._search(
            f"name = '{folder_name}' and mimeType = '{MIME_FOLDER}'", fields="files(id)"
        )
        if not folders:
            return []
        folder_id = folders[0]['id']
        files = self._search(
            f"'{folder_id}' in parents and (mimeType contains 'image/' "
            f"or mimeType = 'application/pdf') and trashed = false",
            fields="files(id, name, mimeType)",
        )
        return sorted(files, key=lambda item: item.get('name', '').lower())

    def download_file(self, file_id: str) -> bytes:
        url = f"{DRIVE_FILES}/{file_id}"
        token = self._ensure_creds()
        try:
            response = requests.get(
                url,
                params={'alt': 'media', 'supportsAllDrives': 'true'},
                headers={'Authorization': f'Bearer {token}'},
                timeout=180,
                verify=self.verify if self.verify else True,
            )
        except requests.RequestException as exc:
            raise GoogleApiError(f"Сетевая ошибка: {exc}") from exc
        if not response.ok:
            raise GoogleApiError(f"Не удалось скачать файл (HTTP {response.status_code}).")
        return response.content


class _HttpResponse:
    """Минимальный ответ в формате, который ожидает google-auth (status_code/data/headers)."""

    def __init__(self, response: requests.Response):
        self.status_code = response.status_code
        self.data = response.content
        self.headers = dict(response.headers)


class _GoogleRequest:
    """Адаптер для google-auth: creds.refresh(request) без google.auth.transport.requests.

    transport-requests тянет httplib2, который на Android собирается болезненно,
    поэтому используем обычный requests.
    """

    def __call__(self, method: str, url: str, headers=None, body=None):
        try:
            response = requests.request(
                method, url, headers=headers or {}, data=body, timeout=60,
                verify=_ca_bundle() or True,
            )
        except requests.RequestException as exc:
            raise GoogleApiError(f"Не удалось обновить токен Google: {exc}") from exc
        return _HttpResponse(response)
