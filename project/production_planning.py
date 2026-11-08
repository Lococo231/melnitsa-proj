"""Производственные критерии и оценка догрузки поверх существующего ядра.

Точки контроля -- локальная технологическая карта предприятия, а не прямые
критерии ГОСТ/EN. Числа по Блейну являются ПРОКСИ исходной модели.
"""
from __future__ import annotations
from copy import deepcopy
import math

from model import (piece_count, mass_for_count_t, chamber_info, cohort_mass, config_at_time, initial_cohorts,
                   mass_kg, quality_at, throughput_at)

# Подтверждённый в постановке профиль предприятия. Другие профили добавляются
# через конфигурацию/корректировку этих карт ТОЛЬКО по данным техотдела.
# Цели из сохранённого HTML 1233223_fixed_norm.html. Это НАСТРОЙКИ
# технологической карты, а НЕ требования ГОСТ 31108-2020.
PROFILES = {
    'ЦЕМ I 42,5Н': {
        'r008': {'max': 2.0}, 'r0045': {'min': 33., 'max': 36.},
        'blaine_proxy': {'min': 3200., 'max': 3500.}},
    'ЦЕМ I 42,5Б': {
        'r008': {'max': 1.5}, 'r0045': {'min': 30., 'max': 34.},
        'blaine_proxy': {'min': 3500., 'max': 3800.}},
    'ЦЕМ I 52,5Н': {
        'r0045': {'min': 28., 'max': 32.},
        'blaine_proxy': {'min': 3800., 'max': 4200.}},
    'ЦЕМ II/А-Ш 42,5Н': {
        'r008': {'max': 3.0}, 'r0045': {'min': 34., 'max': 38.},
        'blaine_proxy': {'min': 3000., 'max': 3400.}},
    'ЦЕМ II/А-И 42,5Н': {
        'r008': {'max': 3.0}, 'r0045': {'min': 34., 'max': 38.},
        'blaine_proxy': {'min': 3000., 'max': 3500.}},
    'Без технологических ограничений': {},
}
# Поддержка старых JSON-конфигураций.
LEGACY_PROFILES = {'ЦЕМ I 42,5Н · технологическая карта': 'ЦЕМ I 42,5Н'}

DEFAULT_PROFILE = next(iter(PROFILES))
QUALITY_NAMES = {
    'r008': 'R0,08, %',
    'r0045': 'R0,045, %',
    'blaine_proxy': 'Блейн (модельный прокси), см²/г',
}


def profile_name(cfg: dict) -> str:
    name = cfg.get('cement_profile', DEFAULT_PROFILE)
    name = LEGACY_PROFILES.get(name, name)
    return name if name in PROFILES else DEFAULT_PROFILE


def assessments(cfg: dict, quality: dict, q_tph: float | None = None) -> list[dict]:
    """Оценки без округления; округление допустимо лишь в представлении."""
    profile = PROFILES[profile_name(cfg)]
    result = []
    for key, rule in profile.items():
        actual = float(quality[key])
        lo, hi = rule.get('min'), rule.get('max')
        ok = ((lo is None or actual >= lo - 1e-10) and
              (hi is None or actual <= hi + 1e-10))
        result.append(dict(key=key, label=QUALITY_NAMES[key], value=actual,
                           minimum=lo, maximum=hi, ok=ok))
    if q_tph is None:
        q_tph = throughput_at(cfg, float(cfg.get('horizon_h', 0)))
    target = float(cfg.get('target_product_tph', throughput_at(cfg, 0)))
    result.append(dict(key='throughput', label='Производительность, т/ч',
                       value=float(q_tph), minimum=target, maximum=None,
                       ok=q_tph >= target - 1e-10))
    return result


def complies(cfg: dict, quality: dict, q_tph: float | None = None) -> bool:
    return all(row['ok'] for row in assessments(cfg, quality, q_tph))


def _shortfall_rows(cfg: dict, run: dict) -> list[dict]:
    """Подбираем догрузку лишь исходных фракций с сохранением их типа/материала."""
    grouped = {}
    for c in run['cohorts']:
        if c.get('batch', 0):
            continue  # ручные догрузки уже есть в текущем состоянии, не дублируем
        key = (int(c['chamber']), c['type'], c['material'], float(c['d0']),
               float(c.get('aspect', 1.0)))
        part = grouped.setdefault(key, {'nominal': 0.0, 'live': 0.0})
        part['nominal'] += float(c['initial_kg']) / 1000
        part['live'] += cohort_mass(c) / 1000
    rows = []
    for (chamber, kind, material, diameter, aspect), value in grouped.items():
        # Минимальная пробная масса при отсутствии износа не должна вноситься
        # автоматически: вмешательство в нормальную загрузку недопустимо.
        deficit = max(0.0, value['nominal'] - value['live'])
        if deficit <= 1e-9:
            continue
        rows.append(dict(drum=1, chamber=chamber, type=kind, material=material,
                         diameter_mm=diameter, aspect=aspect,
                         nominal_t=value['nominal'], live_t=value['live'],
                         shortfall_t=deficit))
    return rows


def _extra_cohorts(cfg: dict, rows: list[dict], scale: float) -> tuple[list[dict], list[dict]]:
    media = []
    for row in rows:
        candidate = {k: row[k] for k in ('drum', 'chamber', 'type', 'material', 'diameter_mm', 'aspect')}
        count = piece_count(candidate, row['shortfall_t'] * scale)
        if count:
            media.append({**candidate, 'initial_t': mass_for_count_t(candidate, count)})
    shadow = deepcopy(cfg)
    shadow['media'] = media
    return initial_cohorts(shadow), media


def _distance(report: list[dict]) -> float:
    """Нормированная ошибка: только для сравнения кандидатов, не гарантия."""
    total = 0.0
    for x in report:
        value = x['value']
        if x['minimum'] is not None:
            total += max(0.0, x['minimum'] - value) / max(abs(x['minimum']), 1.)
        if x['maximum'] is not None:
            total += max(0.0, value - x['maximum']) / max(abs(x['maximum']), 1.)
    return total


def plan_reload(cfg: dict, run: dict, max_fill: float = 0.40) -> dict:
    """Перебор долей восстановления массы на КОНЕЦ горизонта.

    Повторный запуск simulate_wear не нужен: проверяется оперативная догрузка
    в текущие изношенные когорты, без исторической фальсификации. Q задано
    извне; программа НЕ моделирует его прирост и не гарантирует сохранение Q.
    """
    finish = float(cfg['horizon_h'])
    operating_cfg = config_at_time(cfg, finish)
    q = throughput_at(cfg, finish)
    current = quality_at(operating_cfg, run['cohorts'])
    baseline_check = assessments(cfg, current, q)
    shortfalls = _shortfall_rows(cfg, run)
    if all(x['ok'] for x in baseline_check):
        return dict(status='Нормы расчётной модели соблюдены; технологическая догрузка не требуется',
                    feasible=True, rows=[], total_t=0.0, quality=current,
                    checks=baseline_check, fill=chamber_info(cfg, run['cohorts']),
                    scale=0.0, evaluated=1)
    if not shortfalls:
        return dict(status='Нормы не выполнены; восстановить исходную массу нечем. Нужна смена состава загрузки или режима.',
                    feasible=False, rows=[], total_t=0.0, quality=current,
                    checks=baseline_check, fill=chamber_info(cfg, run['cohorts']),
                    scale=0.0, evaluated=1)
    best = None
    count = 0
    # Только восстановления потерянной массы, без неограниченного переполнения.
    for scale in (0., 0.25, 0.50, 0.75, 1., 1.25, 1.5, 2.):
        extra, media = _extra_cohorts(cfg, shortfalls, scale)
        all_cohorts = run['cohorts'] + extra
        fill = chamber_info(cfg, all_cohorts)
        if any(c['fill_j'] > max_fill for c in fill):
            continue
        quality = quality_at(operating_cfg, all_cohorts)
        checks = assessments(cfg, quality, q)
        count += 1
        total = sum(row['initial_t'] for row in media)
        candidate = dict(scale=scale, quality=quality, checks=checks, fill=fill,
                         rows=media, total_t=total, feasible=all(x['ok'] for x in checks),
                         penalty=_distance(checks))
        if best is None or (candidate['feasible'] and not best['feasible']) or (
            candidate['feasible'] == best['feasible'] and
            ((candidate['total_t'] < best['total_t']) if candidate['feasible']
             else (candidate['penalty'],candidate['total_t']) < (best['penalty'],best['total_t']))):
            best = candidate
        if candidate['feasible']:
            break  # возрастающая масса: первая удовлетворяющая цель минимальна в сетке
    if best is None:
        return dict(status='Догрузка по проверенным сценариям запрещена: превышен предел заполнения камер',
                    feasible=False, rows=[], total_t=0.0, quality=current,
                    checks=baseline_check, fill=chamber_info(cfg, run['cohorts']),
                    scale=0.0, evaluated=0)
    outcome = 'Расчётный сценарий найден; требуется подтверждение технолога и лаборатории' if best['feasible'] else (
        'Целевые показатели не достигнуты ни одним проверенным вариантом восстановления массы; '
        'предложение НЕ является решением по нормативам')
    best['status'] = outcome
    best['evaluated'] = count
    return best


def starting_media(cfg: dict) -> list[dict]:
    result = []
    for source in cfg['media']:
        row = dict(source)
        piece = mass_kg(row, float(row['diameter_mm']))
        result.append({
            'Камера': int(row['chamber']), 'Тип': row['type'],
            'Материал': row['material'], 'Ø, мм': float(row['diameter_mm']),
            'L/D': float(row.get('aspect', 1.)),
            'Задано, т': float(row['initial_t']),
            'Начальная масса, т': mass_for_count_t(row, piece_count(row, row['initial_t'])),
            'Количество, шт': piece_count(row, row['initial_t']),
        })
    return result