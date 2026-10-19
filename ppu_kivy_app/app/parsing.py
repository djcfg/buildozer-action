"""Разбор контента: FAQ-документов, таблиц и телефонных справочников.

В боте текст размечался под MarkdownV2 Telegram. В приложении разметка не нужна —
данные выводятся обычными виджетами Kivy, поэтому здесь только извлечение структуры.
"""

import re
from typing import Dict, List, Optional, Tuple

FAQ_HEADING_RE = re.compile(r'\*\*\*\s*(.+?)\s*\*\*\*', re.DOTALL)
PHONE_HEADER_RE = re.compile(r'телефон|phone|тел\.?\s*№|№\s*тел', re.IGNORECASE)
PASSWORD_HEADER_RE = re.compile(r'пароль|password', re.IGNORECASE)
DIGITS_RE = re.compile(r'[^\d+]')


def parse_faq(content: str) -> List[Tuple[str, str]]:
    """Разбить текст документа на разделы FAQ: заголовок — ***Заголовок***."""
    if not content:
        return []
    matches = list(FAQ_HEADING_RE.finditer(content))
    sections: List[Tuple[str, str]] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip().replace('\n', ' ')
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if title:
            sections.append((title, body))
    return sections


def clean_text(text: str) -> str:
    """Убрать markdown-разметку, оставив читаемый текст (документы мог быть форматированы вручную)."""
    if not text:
        return ""
    result = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text, flags=re.DOTALL)
    result = re.sub(r'\*{1,2}(.+?)\*{1,2}', r'\1', result, flags=re.DOTALL)
    result = re.sub(r'`{3}[a-zA-Z0-9]*\n?', '`', result)
    return result


def phone_digits(value: str) -> str:
    """Только цифры и '+' — для tel:-вызова."""
    return DIGITS_RE.sub('', str(value or ''))


def rows_to_records(rows: List[List[str]]) -> Tuple[List[str], List[Dict[str, str]]]:
    """Первая строка — заголовки; далее пары {заголовок: значение}. Пустые строки пропускаются."""
    if not rows:
        return [], []
    headers = [str(cell).strip() for cell in rows[0]]
    records: List[Dict[str, str]] = []
    for row in rows[1:]:
        record: Dict[str, str] = {}
        for col_index, header in enumerate(headers):
            value = str(row[col_index]).strip() if col_index < len(row) else ""
            if header and value:
                record[header] = value
        if record:
            records.append(record)
    return headers, records


def format_record_text(record: Dict[str, str]) -> str:
    """Одна запись таблицы в текст для отображения."""
    lines = []
    for header, value in record.items():
        if PASSWORD_HEADER_RE.search(header):
            lines.append(f"{header}: [ {value} ]")
        else:
            lines.append(f"{header}: {value}")
    return "\n".join(lines)


def find_phone_header(headers: List[str]) -> Optional[str]:
    for header in headers:
        if PHONE_HEADER_RE.search(header or ""):
            return header
    return None


def first_non_empty(record: Dict[str, str], skip_keys=()) -> str:
    for key, value in record.items():
        if key in skip_keys:
            continue
        if value and value.strip():
            return value.strip()
    return ""


def build_contacts(rows: List[List[str]]) -> List[Dict[str, object]]:
    """Справочник -> список контактов {title, lines, phone, phone_display}.

    Логика та же, что в TextFormatter.format_phone_list бота: первый столбец — имя/должность,
    столбцы с «телефон» в заголовке — номера.
    """
    headers, records = rows_to_records(rows)
    if not records:
        return []

    phone_header = find_phone_header(headers)
    contacts: List[Dict[str, object]] = []
    for record in records:
        phone_raw = record.get(phone_header, "") if phone_header else ""
        if not phone_raw:
            for header, value in record.items():
                if PHONE_HEADER_RE.search(header or ""):
                    phone_raw = value
                    break

        digits = phone_digits(phone_raw)
        title = first_non_empty(record, skip_keys=(phone_header,) if phone_header else ())
        lines = [
            f"{header}: {value}"
            for header, value in record.items()
            if header != phone_header and value
        ]
        contacts.append({
            "title": title or (phone_raw or "Без имени"),
            "lines": lines,
            "phone": digits,
            "phone_display": phone_raw,
        })
    return contacts


def format_sheet_table(rows: List[List[str]], max_col_width: int = 40) -> str:
    """Таблица как моноширинный текст — запасной вывод, если записей очень много."""
    if not rows:
        return ""
    widths: List[int] = []
    for row in rows:
        for index, cell in enumerate(row):
            text = str(cell)
            if len(text) > max_col_width:
                text = text[:max_col_width - 1] + "…"
            row[index] = text
            while len(widths) <= index:
                widths.append(0)
            widths[index] = max(widths[index], len(text))

    lines = []
    for row in rows:
        cells = []
        for index, width in enumerate(widths):
            cell = row[index] if index < len(row) else ""
            cells.append(cell.ljust(width))
        lines.append(" | ".join(cells).rstrip())
    return "\n".join(lines)
