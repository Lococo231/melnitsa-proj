"""Selectable, GUI-independent export for the desktop mill operator workflow.

A single exporter is used for JSON and XLSX. XLSX uses XlsxWriter (already
required by the project), so a frozen executable does not need openpyxl.
"""
from __future__ import annotations

import json
from pathlib import Path


def _as_text(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def save_selected_export(payload: dict, path: str | Path) -> None:
    """Save selected sections, not unrelated app data, to a path ending in .json/.xlsx.

    User-entered strings are treated as text in Excel, never as formulas.
    Nested inputs (e.g. original chamber media rows) are retained as JSON in
    the snapshot sheet; the JSON export preserves their complete structure.
    """
    path = Path(path)
    if path.suffix.lower() == '.json':
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                        encoding='utf-8')
        return
    if path.suffix.lower() != '.xlsx':
        raise ValueError('Поддерживается экспорт только в .xlsx и .json')
    import xlsxwriter

    wb = xlsxwriter.Workbook(str(path), {'strings_to_formulas': False,
                                        'strings_to_urls': False})
    heading = wb.add_format({'bold': True, 'bg_color': '#DDE8EE',
                             'border': 1, 'valign': 'top'})
    cell = wb.add_format({'text_wrap': True, 'valign': 'top'})

    def put(ws, row, col, value, fmt=None):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            ws.write_number(row, col, value, fmt)
        else:
            # Never interpret strings beginning with =, +, @ as formulae.
            ws.write_string(row, col, _as_text(value)[:32767], fmt)

    def sheet_for(name):
        ws = wb.add_worksheet(name[:31])
        ws.freeze_panes(1, 0)
        ws.set_column(0, 0, 28)
        ws.set_column(1, 20, 34)
        return ws

    def write_rows(title, rows):
        ws = sheet_for(title)
        if not rows:
            put(ws, 0, 0, 'Состояние', heading)
            put(ws, 1, 0, 'Нет данных')
            return
        headers = list(dict.fromkeys(k for row in rows for k in row.keys()))
        for column, header in enumerate(headers):
            put(ws, 0, column, header, heading)
        for r, values in enumerate(rows, 1):
            for c, name in enumerate(headers):
                put(ws, r, c, values.get(name, ''), cell)

    try:
        ws = sheet_for('Сводка')
        put(ws, 0, 0, 'Дата экспорта', heading)
        put(ws, 0, 1, payload.get('created_at', ''))
        put(ws, 1, 0, 'Разделы', heading)
        put(ws, 1, 1, ', '.join(payload.get('selected', [])))
        if 'segments' in payload:
            write_rows('Журнал симуляций', payload['segments'])
        for key, title in (
            ('sim_status', 'Результат режима'),
            ('recommendations', 'Рекомендации'),
            ('sample_table', 'Таблица проб'),
            ('start_table', 'Начальная загрузка'),
            ('journal_initial', 'Исходное состояние'),
        ):
            if key in payload:
                write_rows(title, payload[key])
        if 'journal_tables' in payload:
            for key, rows in payload['journal_tables'].items():
                write_rows(f'Журнал {key}', rows)
        if 'current_config' in payload:
            write_rows('Текущая конфигурация', [
                {'Параметр': name, 'Значение': _as_text(value)}
                for name, value in payload['current_config'].items()
            ])
        if 'segment_details' in payload:
            for segment in payload['segment_details']:
                write_rows(f'Симуляция {segment["index"]}', [
                    {'Параметр': k, 'Значение': _as_text(v)}
                    for k, v in segment.get('snapshot', {}).items()
                ])
    finally:
        wb.close()
