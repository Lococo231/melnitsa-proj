"""Функции работы с данными GUI без зависимости от PySide6.

Единственный источник расчётных значений -- model.py. Интерфейс не подменяет
физические характеристики клинкера пользовательскими регуляторами.
"""
from __future__ import annotations

import csv
import io
import math
from copy import deepcopy

from model import CLASSES, MATERIALS, throughput_at, validate

FIELDS = {
    'Подача и клинкер': [
        ('throughput_mode', 'Способ определения производительности', 'mode'),
        ('fresh_feed_tph', 'Измеренная производительность, т/ч', 'float'),
        ('measured_total_t', 'Выпуск за период, т', 'float'),
        ('measured_hours', 'Длительность измерения, ч', 'float'),
        ('recycle_ratio', 'Возврат сепаратора, т/т', 'float'),
        ('material_hold_t', 'Запас материала в мельнице, т', 'float'),
        ('moisture_pct', 'Измеренная влажность, %', 'float'),
        ('temperature_c', 'Измеренная температура, °C', 'float'),
    ],
    'Прогноз износа': [
        ('horizon_h', 'Горизонт моделирования, ч', 'float'),
        ('step_h', 'Шаг по времени, ч', 'float'),
        ('reload_threshold_pct', 'Порог рекомендации догрузки, %', 'float'),
    ],
}
MODES = ['Измеренная подача, т/ч', 'Масса / время']
MEDIA_FIELDS = [
    ('chamber','Камера'), ('type','Тип'), ('material','Материал'),
    ('diameter_mm','Диаметр, мм'), ('initial_t','Масса, т'),
    ('aspect','L/D цильпебса')
]
RELOAD_FIELDS = [
    ('hour','Час догрузки'), ('chamber','Камера'), ('type','Тип'),
    ('material','Материал'), ('diameter_mm','Диаметр, мм'),
    ('tons','Добавить, т'), ('aspect','L/D цильпебса')
]
THROUGHPUT_FIELDS = [('hour','Начало, ч'), ('tph','Подача, т/ч')]
NUMERIC_KEYS = {'hour','tph','diameter_mm','initial_t','tons','aspect'}


def is_valid_input(config: dict) -> bool:
    if not isinstance(config, dict):
        raise ValueError('Ожидается JSON-объект параметров мельницы')
    validate(config)
    return True


def numeric(value, label='число') -> float:
    try:
        result = float(str(value).strip().replace(',', '.'))
    except (ValueError, TypeError) as error:
        raise ValueError(f'Некорректное значение «{label}»') from error
    if not math.isfinite(result):
        raise ValueError(f'Число «{label}» должно быть конечным')
    return result


def default_table_row(kind: str, cfg: dict) -> dict:
    """Вставка без диалога: допустимая строка с заводскими единицами измерения."""
    if kind == 'media':
        chamber = len(cfg['mills'][0]['chambers'])
        return dict(drum=1, chamber=chamber, type='Шары', material='Сталь',
                    diameter_mm=40., initial_t=1., aspect=1.)
    if kind == 'manual_reloads':
        chamber = len(cfg['mills'][0]['chambers'])
        source = next((r for r in cfg['media'] if int(r['chamber']) == chamber), None)
        source = source or (cfg['media'][0] if cfg['media'] else None)
        if source is None:
            raise ValueError('Для догрузки нужна хотя бы одна фракция мелющих тел')
        return dict(drum=1, hour=round(cfg['horizon_h']/2, 1),
                    chamber=int(source['chamber']), type=source['type'],
                    material=source['material'], diameter_mm=source['diameter_mm'],
                    tons=0.5, aspect=source.get('aspect', 1.))
    if kind == 'throughput_schedule':
        t = round(cfg['horizon_h']/2, 1)
        occupied = {float(r['hour']) for r in cfg.get('throughput_schedule', [])}
        while t in occupied and t < cfg['horizon_h']:
            t += 1.
        if t in occupied or t > cfg['horizon_h']:
            t = 0.
        if t in occupied:
            raise ValueError('Все временные точки заняты, измените существующие интервалы')
        return dict(hour=t, tph=throughput_at(cfg, t))
    raise ValueError('Неизвестный тип таблицы')


def row_from_cells(kind: str, values: dict, existing: dict | None = None) -> dict:
    row = deepcopy(existing or {})
    row.update(values)
    if kind in ('media', 'manual_reloads'):
        row['drum'] = 1
        row['chamber'] = int(numeric(row['chamber'], 'Камера'))
    fields = {'media': MEDIA_FIELDS, 'manual_reloads': RELOAD_FIELDS,
              'throughput_schedule': THROUGHPUT_FIELDS}[kind]
    for key, label in fields:
        if key in NUMERIC_KEYS:
            row[key] = numeric(row[key], label)
    return row


def clinker_from_csv(data: bytes | str) -> list[float]:
    content = data.decode('utf-8-sig') if isinstance(data, bytes) else data
    try:
        dialect = csv.Sniffer().sniff(content[:2048], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(content), dialect=dialect))
    by_class = {r['class'].strip(): numeric(r['percent'], r['class']) for r in rows}
    if len(rows) != len(CLASSES) or set(by_class) != set(CLASSES):
        raise ValueError('Грансостав должен содержать 10 классов class,percent')
    values = [by_class[c] for c in CLASSES]
    if any(v < 0 for v in values) or not 99 <= sum(values) <= 101:
        raise ValueError('Доли неотрицательные; сумма должна быть около 100%')
    return values


def merge_lab_parameters(cfg: dict, incoming: dict) -> dict:
    if not isinstance(incoming, dict):
        raise ValueError('Лабораторный протокол должен быть JSON-объектом')
    allowed = {'bond_test', 'work_index_kwh_t', 'grindability',
               'abrasion_factor', 'feed_bulk_density'}
    if not allowed.intersection(incoming):
        raise ValueError('В протоколе нет лабораторных параметров')
    result = deepcopy(cfg)
    for key in allowed.intersection(incoming):
        result[key] = incoming[key]
    if 'bond_test' in incoming:
        result['work_index_kwh_t'] = None
    is_valid_input(result)
    return result
