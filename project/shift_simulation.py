"""Прогноз сменной работы и *сценарный* подбор изменения загрузки.

Модель качества и закон износа повторно используются из model.py; диаграммы
не рисуются из заранее заданных чисел. Временная ось -- часы фактической
работы, остановки между сменами не приводят к износу.

Это дискретный, локальный поиск по ОДНОЙ фракции и одной операции. Он не
проверяет конструктивную возможность разгрузки и НЕ гарантирует режим цеха.
"""
from __future__ import annotations

from copy import deepcopy
import math
from math import ceil, isfinite

from model import (MATERIALS, chamber_info, cohort_mass, config_at_time,
                   initial_cohorts, make_weights, mass_kg, quality_at,
                   throughput_at, validate, piece_count, mass_for_count_t)
from production_planning import PROFILES, profile_name, assessments

METRIC_KEYS = ('r008', 'r0045', 'blaine_proxy')
MAX_FILL = 0.40  # предварительный верхний технологический предел J
MIN_FILL = 0.18  # предупреждение о слишком малой загрузке


def hours_of_operation(cfg: dict) -> float:
    days = int(cfg.get('simulation_days', 5))
    hours = float(cfg.get('simulation_hours_per_day', 8))
    if not (1 <= days <= 365 and 0 < hours <= 24 and isfinite(hours)):
        raise ValueError('Период симуляции: 1–365 дней, 0–24 ч работы в день')
    return days * hours


def operation_day(hour: float, hours_per_day: float) -> str:
    """0 ч -> первый день, 8 ч при смене 8 ч -> второй день, 0 ч."""
    day = int(max(0, hour) // hours_per_day) + 1
    within = max(0, hour) % hours_per_day
    if hour > 0 and abs(within) < 1e-8:
        day -= 1
        within = hours_per_day
    return f'день {day}, час {within:g} из {hours_per_day:g}'


def _clock_grid(cfg: dict, observations: int = 130) -> tuple[list[float], set[float]]:
    end = hours_of_operation(cfg)
    # Не более 400 шагов модельного износа, как и в simulate_wear().
    original_steps = max(1, ceil(end / max(float(cfg['step_h']), end / 400)))
    # При небольшом периоде используем почасовую сетку даже если базовый
    # шаг износа по умолчанию равен 10 ч: иначе потеряем границу смены.
    steps = max(original_steps, min(400, ceil(end)))
    obs_steps = min(steps, max(2, observations))
    observable = {round(end * i / obs_steps, 9) for i in range(obs_steps+1)}
    ticks = set(round(end * i / steps, 9) for i in range(steps+1)) | observable
    # Границы рабочих дней учитываем отдельно от равномерной сетки.
    for day in range(1, int(cfg.get('simulation_days', 5))+1):
        t = round(day*float(cfg.get('simulation_hours_per_day',8.)), 9)
        ticks.add(t)
        observable.add(t)
    # Точные моменты Q и заранее внесённых догрузок, иначе ошибка в интеграле.
    for row in cfg.get('manual_reloads', []):
        if 0 <= row['hour'] <= end:
            ticks.add(float(row['hour']))
            observable.add(float(row['hour']))
    for row in cfg.get('throughput_schedule', []):
        if 0 <= row['hour'] <= end:
            ticks.add(float(row['hour']))
            observable.add(float(row['hour']))
    return sorted(ticks), observable


def _install_manual(cfg: dict, cohorts: list[dict], when: float) -> None:
    for idx, r in enumerate(cfg.get('manual_reloads', [])):
        if abs(float(r['hour']) - when) > 1e-6:
            continue
        item = {**r, 'initial_t': float(r['tons']), 'drum': 1}
        pieces = piece_count(item, item['initial_t'])
        if not pieces:
            continue
        actual_t = mass_for_count_t(item, pieces)
        cohorts.append({**item, 'initial_t': actual_t, 'id': 100000+idx,
                        'batch': 100000+idx,
                        'd0': item['diameter_mm'], 'd': item['diameter_mm'],
                        'n': pieces, 'initial_kg': actual_t*1000,
                        'cumulative_loss_kg': 0.})


def _wear_step(cfg: dict, cohorts: list[dict], ref_w: float, start: float, end: float) -> None:
    if end <= start or not cohorts:
        return
    infos = chamber_info(cfg, cohorts)
    weights = make_weights(cfg, cohorts, infos)
    total = sum(weights)
    if total <= 1e-12:
        return
    q = throughput_at(cfg, start)
    # Та же удельная модель износа, что в model.simulate_wear.
    interval_kg = q * (end-start) * cfg['wear_g_t'] / 1000 * total / ref_w
    for c, w in zip(cohorts, weights):
        if w <= 0 or c['n'] <= 0:
            continue
        old = cohort_mass(c)
        lost = min(old, interval_kg * w/total)
        c['cumulative_loss_kg'] += lost
        new = max(0., old-lost)
        c['d'] = c['d0']*(new/max(c['initial_kg'], 1e-12))**(1/3)
        if c['d'] < cfg['retention_mm']:
            c['removed_kg'] = c.get('removed_kg', 0.) + cohort_mass(c)
            c['n'] = 0.


def _quality_row(cfg: dict, cohorts: list[dict], hour: float) -> dict:
    q = quality_at(config_at_time(cfg, hour), cohorts, samples=2)
    tph = throughput_at(cfg, hour)
    report = assessments(cfg, q, tph)
    return {'hour': float(hour), 'r008': float(q['r008']),
            'r0045': float(q['r0045']), 'blaine_proxy': float(q['blaine_proxy']),
            'throughput': tph, 'ok': all(x['ok'] for x in report),
            'violations': [x['label'] for x in report if not x['ok']]}


def _calculate(cfg: dict, ticks: list[float], observed: set[float],
               ref_w: float, cohorts: list[dict], start: float = 0.,
               action: dict | None = None, stop_at_first_bad: bool = False,
               save_states: bool = False):
    results = []
    states = {}
    end = ticks[-1]
    ticks = [t for t in ticks if t >= start-1e-7]
    for i, t in enumerate(ticks):
        # Ручная догрузка при t = h применяется до контроля состояния.
        _install_manual(cfg, cohorts, t)
        if action is not None and abs(t-action['hour']) < 1e-6:
            _change_media(cfg, cohorts, action)
        if t in observed or i == 0 or i == len(ticks)-1:
            entry = _quality_row(cfg, cohorts, t)
            results.append(entry)
            if save_states:
                states[t] = deepcopy(cohorts)
            if stop_at_first_bad and not entry['ok']:
                return results, states
        if t < end-1e-9:
            _wear_step(cfg, cohorts, ref_w, t, ticks[i+1])
    return results, states


def _group_key(c: dict) -> tuple:
    return (int(c['chamber']), c['type'], c['material'],
            float(c['d0']), float(c.get('aspect', 1.)))


def _removal_distribution(group: list[dict], pieces: int) -> list[int]:
    """Снимаем ЦЕЛЫЕ тела с отдельных партий методом наибольших остатков."""
    numbers = [int(c['n']) for c in group]
    total = sum(numbers)
    if not 0 <= pieces <= total:
        raise ValueError('Выгрузка больше доступного количества мелющих тел')
    if total == 0:
        return [0 for _ in group]
    shares = [pieces * n / total for n in numbers]
    taken = [min(n, int(math.floor(s))) for n, s in zip(numbers, shares)]
    missing = pieces - sum(taken)
    order = sorted(range(len(group)), key=lambda i:(shares[i]-taken[i], numbers[i]), reverse=True)
    for index in order:
        if missing <= 0:
            break
        if taken[index] < numbers[index]:
            taken[index] += 1
            missing -= 1
    assert sum(taken) == pieces
    return taken


def _change_media(cfg: dict, cohorts: list[dict], action: dict) -> None:
    direction = action['direction']
    target = action['target']
    key = (int(target['chamber']), target['type'], target['material'],
           float(target['diameter_mm']), float(target.get('aspect',1.)))
    row = {k: v for k, v in zip(('chamber','type','material','diameter_mm','aspect'), key)}
    row['drum'] = 1
    if direction == 'add':
        pieces = int(action.get('pieces', piece_count(row, action.get('tons', 0.))))
        if pieces <= 0:
            return
        real_t = mass_for_count_t(row, pieces)
        new = initial_cohorts({**cfg, 'media': [{**row, 'initial_t': real_t}]})[0]
        new['id'] = max((c.get('id', 0) for c in cohorts), default=0) + 1
        new['batch'] = 200000 + new['id']
        cohorts.append(new)
        return
    if direction != 'remove':
        raise ValueError('Операция должна быть add или remove')
    group = [c for c in cohorts if _group_key(c) == key and c['n'] > 0]
    available_pieces = sum(int(c['n']) for c in group)
    if not group:
        return
    avg_kg = sum(cohort_mass(c) for c in group) / available_pieces
    pieces = int(action.get('pieces', math.floor(action.get('tons',0.)*1000/avg_kg + 0.5)))
    allocation = _removal_distribution(group, pieces)
    for c, n_removed in zip(group, allocation):
        if not n_removed:
            continue
        original_count = int(c['n'])
        remaining_count = original_count - n_removed
        fraction = remaining_count / original_count
        c['n'] = remaining_count
        c['initial_kg'] *= fraction
        c['cumulative_loss_kg'] *= fraction
        if 'removed_kg' in c:
            c['removed_kg'] *= fraction
    # Физический диаметр оставшихся тел при выгрузке не изменяется.


def _reference_weight(cfg: dict) -> float:
    c = initial_cohorts(cfg)
    value = sum(make_weights(cfg, c, chamber_info(cfg,c), use_factors=False))
    if value <= 0:
        raise ValueError('Для расчёта износа нужны действующие мелющие тела')
    return value


def _candidates(cfg: dict, cohorts: list[dict], hour: float, limit: int = 160):
    """Предлагаем не проценты тел, а точное целое число штук; масса производная."""
    seen = set()
    seen_actions = set()
    infos = chamber_info(cfg, cohorts)
    fill_by_ch = {x['chamber']: x['fill_j'] for x in infos}
    for c in cohorts:
        if not c['n']:
            continue
        key = _group_key(c)
        if key in seen:
            continue
        seen.add(key)
        group = [p for p in cohorts if _group_key(p) == key and p['n'] > 0]
        total_pieces = sum(int(p['n']) for p in group)
        live_t = sum(cohort_mass(p) for p in group) / 1000.
        nominal_t = sum(float(r['initial_t']) for r in cfg['media'] if
                        (int(r['chamber']), r['type'], r['material'],
                         float(r['diameter_mm']), float(r.get('aspect',1.))) == key)
        row = dict(zip(('chamber','type','material','diameter_mm','aspect'), key))
        row['drum'] = 1
        for direction in ('add','remove'):
            for fraction in (.05,.10,.15,.20,.25,.30,.35):
                desired_t = max(nominal_t, live_t) * fraction
                if direction == 'add':
                    pieces = piece_count(row, desired_t)
                    real_t = mass_for_count_t(row, pieces)
                else:
                    if not total_pieces:
                        continue
                    pieces = int(math.floor(desired_t * 1000. / (live_t * 1000. / total_pieces) + 0.5))
                    if pieces >= total_pieces:
                        continue
                    allocation = _removal_distribution(group, pieces)
                    real_t = sum(n * mass_kg(p, p['d']) for p,n in zip(group,allocation)) / 1000.
                if pieces <= 0 or real_t <= 0:
                    continue
                token = (key, direction, pieces)
                if token in seen_actions:
                    continue
                seen_actions.add(token)
                action = {'hour':hour, 'direction':direction, 'pieces':pieces,
                          'tons':real_t, 'target':{k:row[k] for k in
                          ('chamber','type','material','diameter_mm','aspect')}}
                # Предварительная оценка изменения заполнения камер.
                density = MATERIALS[key[2]]['rho']
                chamber = infos[key[0]-1]
                delta_j = (real_t*1000. / density) / (.585*chamber['volume_m3'])
                fill_new = fill_by_ch[key[0]] + (delta_j if direction=='add' else -delta_j)
                if MIN_FILL <= fill_new <= MAX_FILL:
                    yield action


def _time_in_spec(rows: list[dict], start: float, end: float) -> float:
    """Сколько часов подряд от вмешательства до ПЕРВОГО нарушения."""
    if not rows or not rows[0]['ok']:
        return 0.
    for row in rows[1:]:
        if not row['ok']:
            return max(0., row['hour'] - start)
    return end-start


def simulate_shifts(cfg: dict, optimize: bool = True,
                    observations: int = 120, candidate_limit: int = 150) -> dict:
    """Базовая линия и наилучшая из проверенных ОДИНОЧНЫХ коррекций.

    Критерий: максимальная непрерывная длительность соблюдения всех
    технологических диапазонов после вмешательства; при равенстве -- меньший
    тоннаж. Никакой ложной гарантии сохранения Q нет (Q задаётся извне).
    """
    cfg = deepcopy(cfg)
    end = hours_of_operation(cfg)
    cfg['horizon_h'] = end
    validate(cfg)
    grid, obs = _clock_grid(cfg, observations)
    ref = _reference_weight(cfg)
    base_rows, base_states = _calculate(cfg, grid, obs, ref,
                                        initial_cohorts(cfg), save_states=True)
    outcome = {'hours':end, 'days':int(cfg.get('simulation_days',5)),
               'hours_per_day':float(cfg.get('simulation_hours_per_day',8)),
               'profile':profile_name(cfg), 'baseline':base_rows,
               'optimized':None, 'action':None, 'evaluated':0,
               'first_bad':next((r for r in base_rows if not r['ok']),None)}
    first = outcome['first_bad']
    if first is None:
        outcome['status'] = 'Все рассчитанные контрольные точки соответствуют выбранным целям. Коррекция не требуется.'
        return outcome
    if not optimize:
        outcome['status'] = 'В прогнозе обнаружен выход за технологические цели.'
        return outcome
    idx = base_rows.index(first)
    # Вмешательство при первой предшествующей точке; если t=0 не в норме,
    # действие предлагается до запуска. Время всегда лежит на расчётной сетке.
    when = base_rows[max(0, idx-1)]['hour']
    start_cohorts = deepcopy(base_states[when])
    remaining = [t for t in grid if t >= when - 1e-7]
    # Проверяем качество на каждом из предусмотренных контрольных моментов.
    observed = {r['hour'] for r in base_rows if r['hour'] >= when}
    observed.add(when)
    # Этап 1: быстрый первичный отбор по ~15 точкам. На всех выбранных
    # вариантах проверяем и промежуточную точку после начала операции.
    all_observed = sorted(observed)
    stride = max(1, ceil(len(all_observed) / 15))
    coarse_observed = set(all_observed[::stride]) | {all_observed[0],all_observed[-1]}
    if len(all_observed)>1:
        coarse_observed.add(all_observed[1])
    shadow = {**cfg, 'manual_reloads': [r for r in cfg.get('manual_reloads', [])
                                       if r['hour'] > when+1e-7]}
    shortlist = []
    for n, action in enumerate(_candidates(cfg, start_cohorts, when)):
        if n >= candidate_limit:
            break
        trial = deepcopy(start_cohorts)
        try:
            rows, _ = _calculate(shadow, remaining, coarse_observed, ref, trial,
                                 start=when, action=action, stop_at_first_bad=True)
        except (ValueError, ArithmeticError, OverflowError):
            continue
        outcome['evaluated'] += 1
        duration = _time_in_spec(rows, when, end)
        if duration <= 0:
            continue
        shortlist.append({'action': action, 'coarse_hours': duration})
    # Этап 2: перепроверка наиболее перспективных вариантов по ВСЕМ контрольным
    # точкам. Подбор сеточный, следовательно, не заявляем доказательства
    # глобального оптимума непрерывной задачи.
    shortlist.sort(key=lambda row: (row['coarse_hours'], -row['action']['tons']), reverse=True)
    top = None
    for candidate in shortlist[:12]:
        action = candidate['action']
        try:
            rows, _ = _calculate(shadow, remaining, observed, ref,
                                 deepcopy(start_cohorts), start=when,
                                 action=action, stop_at_first_bad=True)
        except (ValueError, ArithmeticError, OverflowError):
            continue
        duration = _time_in_spec(rows, when, end)
        if duration <= 0:
            continue
        score = (duration, -action['tons'])
        if top is None or score > top['score']:
            top = {'action': action, 'score': score, 'valid_hours': duration}
    if top is None:
        outcome['status'] = ('Не найдено одиночной догрузки/выгрузки, возвращающей все показатели в допустимые пределы. '
                             'Требуется изменение режима или состава нескольких фракций, проверка технологом.')
        return outcome
    action = top['action']
    suffix, _ = _calculate(shadow, remaining, observed, ref,
                            deepcopy(start_cohorts), start=when, action=action)
    # Сравнение строго на общей оси: до вмешательства обе траектории совпадают.
    prefix = [r for r in base_rows if r['hour'] < when-1e-7]
    outcome['optimized'] = prefix + suffix
    outcome['action'] = {**action, 'valid_hours':top['valid_hours'],
                         'valid_to':when+top['valid_hours']}
    outcome['status'] = ('Подобран один сценарий изменения загрузки; '
                         'длительность нахождения в диапазонах после него '
                         f'{top["valid_hours"]:g} ч (по дискретным контрольным точкам).')
    return outcome