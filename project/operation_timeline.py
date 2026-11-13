"""Рабочая хронология одного барабана, с изменениями на часах наработки.

Раздельные журналы: марки цемента (технологические целевые карты), операции
над мелющими телами (строго целые штуки), параметры оборудования. Состояние
пересчитывается в каждой точке, а не строится из неподвижных иллюстраций.

Это модель, не управление установкой. Геометрические изменения разрешены как
сценарии замены конфигурации: диаметр работающего барабана физически не меняется.
"""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
import math
import os

from model import (MATERIALS, mass_kg, piece_count, initial_cohorts, cohort_mass,
                   chamber_info, throughput_at, quality_at, config_at_time,
                   coefficient_at)
from production_planning import PROFILES, profile_name, assessments
from shift_simulation import (_clock_grid, _wear_step, _install_manual,
                              _reference_weight, _candidates, _change_media,
                              hours_of_operation, operation_day, MAX_FILL, MIN_FILL)

METRICS = (('r008', 'R0,08'), ('r0045', 'R0,045'), ('blaine_proxy', 'Блейн'))
PARAMETERS = {
    'rpm': ('Частота вращения', 'об/мин', 0.01, 40),
    'power_kw': ('Мощность привода', 'кВт', 0, 30000),
    'diameter_m': ('Диаметр барабана', 'м', 1, 10),
    'fresh_feed_tph': ('Производительность', 'т/ч', 0.01, 20000),
    'recycle_ratio': ('Возврат сепаратора', 'доли', 0, 20),
    'material_hold_t': ('Запас материала', 'т', 0.01, 10000),
    'moisture_pct': ('Влажность клинкера', '%', 0, 50),
    'temperature_c': ('Температура', '°C', -50, 300),
}


def _at_hour(event: dict) -> float:
    return float(event['hour'])


def _find_group(c: dict, target: dict) -> bool:
    return (int(c['chamber']) == int(target['chamber'])
            and c['type'] == target['type']
            and c['material'] == target['material']
            and abs(float(c['d0']) - float(target['diameter_mm'])) < 1e-6
            and abs(float(c.get('aspect', 1)) - float(target.get('aspect', 1))) < 1e-6)


def _group_mass(cohorts: list[dict], target: dict) -> float:
    return sum(cohort_mass(c) for c in cohorts if _find_group(c, target)) / 1000


def _group_count(cohorts: list[dict], target: dict) -> int:
    return sum(int(c['n']) for c in cohorts if _find_group(c, target))


def _description(target: dict) -> str:
    return (f"К{int(target['chamber'])} {target['type']} {target['material']} "
            f"Ø{float(target['diameter_mm']):g} мм, L/D={float(target.get('aspect',1)):g}")


def _range_label(bound: dict | None) -> str:
    if not bound:
        return 'Не задан'
    lo = bound.get('min')
    hi = bound.get('max')
    if lo is None: return f'≤ {hi:g}'
    if hi is None: return f'≥ {lo:g}'
    return f'{lo:g}–{hi:g}'


def _validate_events(cfg: dict, horizon: float) -> None:
    total = 0
    for name in ('cement_events', 'media_events', 'parameter_events'):
        rows = cfg.get(name, [])
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError(f'{name}: требуется список не более 200 записей')
        total += len(rows)
        for event in rows:
            h = _at_hour(event)
            if not math.isfinite(h) or h < 0 or h > horizon:
                raise ValueError(f'{name}: час изменения должен быть в пределах 0–{horizon:g}')
    if total > 300:
        raise ValueError('Слишком много изменений: максимум 300')
    for event in cfg.get('cement_events', []):
        if event['profile'] not in PROFILES:
            raise ValueError('Неизвестная технологическая карта: ' + str(event['profile']))
    for event in cfg.get('parameter_events', []):
        key = event['parameter']
        if key not in PARAMETERS:
            raise ValueError('Недопустимое изменение параметра: ' + str(key))
        value = float(event['value'])
        _, _, low, high = PARAMETERS[key]
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{PARAMETERS[key][0]}: диапазон от {low} до {high}')
    for event in cfg.get('media_events', []):
        if event.get('direction') not in ('add', 'remove'):
            raise ValueError('Операция с мелющими телами: «добавить» или «выгрузить»')
        target = event.get('target') or {}
        if int(target.get('chamber', -1)) not in range(1, len(cfg['mills'][0]['chambers'])+1):
            raise ValueError('Операция относится к несуществующей камере')
        if target.get('type') not in ('Шары', 'Цильпебс'):
            raise ValueError('Неизвестный тип мелющих тел')
        if target.get('material') not in MATERIALS:
            raise ValueError('Неизвестный материал мелющих тел')
        if not (float(target.get('diameter_mm', 0)) > 0 and float(target.get('aspect', 0)) > 0):
            raise ValueError('Диаметр и L/D мелющего тела должны быть больше нуля')
        # Выгрузка в момент события округляется по фактической массе изношенных тел.
        tons = float(event.get('tons', 0))
        pieces = event.get('pieces')
        if pieces is None and (not math.isfinite(tons) or tons <= 0):
            raise ValueError('Для операции укажите положительную массу или целое число штук')
        if pieces is not None and (isinstance(pieces, bool) or not isinstance(pieces, int) or pieces <= 0):
            raise ValueError('Количество мелющих тел должно быть положительным целым числом')
        if event['direction'] == 'add' and pieces is None and piece_count(target, tons) == 0:
            raise ValueError('Масса догрузки меньше массы, требуемой хотя бы для одного тела')


def _set_parameter(cfg: dict, key: str, value: float) -> float:
    if key in ('rpm', 'power_kw'):
        previous = float(cfg['mills'][0][key])
        cfg['mills'][0][key] = value
    elif key == 'diameter_m':
        mill = cfg['mills'][0]
        previous = float(mill['diameter_m'])
        mill['diameter_m'] = value
        # Смена геометрической конфигурации — сценарий реконструкции,
        # сохраняем корректный геометрический смысл диаметра камер.
        for ch in mill['chambers']:
            if abs(ch.get('diameter_m', previous)-previous) < 1e-6:
                ch['diameter_m'] = value
            elif ch['diameter_m'] > value:
                ch['diameter_m'] = value
    else:
        previous = float(cfg[key])
        cfg[key] = value
        if key == 'fresh_feed_tph':
            cfg['throughput_mode'] = 'Измеренная подача, т/ч'
            # После явной смены Q оператором прежний график дозатора не
            # переопределяет заданную уставку на следующих часах.
            cfg['throughput_schedule'] = []
    return previous


def _runtime_quality_config(cfg: dict, hour: float) -> dict:
    """Лёгкое представление для read-only quality_at вместо deepcopy всего JSON.

    Модель качества не изменяет словари входной конфигурации. При добавлении
    записи в модель это допущение нужно снова проверить.
    """
    view = dict(cfg)
    view['throughput_mode'] = 'Измеренная подача, т/ч'
    view['fresh_feed_tph'] = throughput_at(cfg, hour)
    return view


def _config_row(cfg: dict, cohorts: list[dict], hour: float, reference: float,
                wear_cumulative_t: float) -> dict:
    q = quality_at(_runtime_quality_config(cfg, hour), cohorts, samples=2)
    speed = throughput_at(cfg, hour)
    checks = assessments(cfg, q, speed)
    profile = profile_name(cfg)
    row = {'hour': hour, 'profile': profile, 'r008': float(q['r008']),
           'r0045': float(q['r0045']), 'blaine_proxy': float(q['blaine_proxy']),
           'throughput': speed, 'media_mass_t': sum(cohort_mass(c) for c in cohorts) / 1000,
           'piece_count': sum(int(c['n']) for c in cohorts),
           'wear_cumulative_t': wear_cumulative_t,
           'ok': all(r['ok'] for r in checks),
           'violations': [r['label'] for r in checks if not r['ok']],
           'rpm': float(cfg['mills'][0]['rpm']),
           'diameter_m': float(cfg['mills'][0]['diameter_m']),
           'power_kw': float(cfg['mills'][0]['power_kw']),
           'fresh_feed_tph': speed}
    for key, _ in METRICS:
        bounds = PROFILES[profile].get(key, {})
        row[key + '_minimum'] = bounds.get('min')
        row[key + '_maximum'] = bounds.get('max')
    # Для графика массы состава: одна кривая на номинальный размер/камеру.
    series = {}
    sum_diameter = {}
    names_map = {}
    for c in cohorts:
        key = _description(c)
        weight = cohort_mass(c)/1000
        series[key] = series.get(key, 0.) + weight
        sum_diameter[key] = sum_diameter.get(key, 0.) + c['d']*weight
        full_name = (f"Б{int(c['drum'])}К{int(c['chamber'])} · "
                     f"{c['type']} · {c['material']} · Ø{float(c['d0']):g}")
        names_map[full_name] = key
    row['media_by_fraction_t'] = series
    row['diameter_by_fraction_mm'] = {
        key: (sum_diameter[key]/mass if mass>0 else 0.)
        for key,mass in series.items()}
    coefficients = coefficient_at(cfg,cohorts,reference,hour)
    row['wear_by_fraction_g_t'] = {
        names_map.get(key,key):float(value)
        for key,value in coefficients.items()
        if key not in ('Наработка, ч','Вся загрузка, г/т')}
    row['chamber_diameters_mm'] = {
        f"К{info['chamber']}":info['mean_d_mm']
        for info in chamber_info(cfg,cohorts)}
    return row


def _perform(cfg: dict, times: list[float], observed: set[float],
             reference: float, *, action: dict | None = None,
             actions: list[dict] | None = None,
             capture_states: bool = False,
             runtime_states: dict | None = None,
             resume: tuple[dict, list[dict], float] | None = None,
             stop_at_first_failure: bool = False) -> tuple[list[dict], dict, dict]:
    # Вторая траектория начинается непосредственно в точке коррекции.
    # Ранее выполненные события и износ уже содержатся в снапшоте.
    operating = deepcopy(cfg if resume is None else resume[0])
    cohorts = initial_cohorts(operating) if resume is None else deepcopy(resume[1])
    records = []
    states = {}
    logs = {'cement_changes': [], 'media_changes': [], 'parameter_changes': []}
    wear_cumulative_t = 0. if resume is None else float(resume[2])
    days_hours = float(operating.get('simulation_hours_per_day', 8))
    for idx, now in enumerate(times):
        if resume is None or idx > 0:
            manual = [entry for entry in operating.get('manual_reloads', [])
                      if abs(float(entry['hour'])-now)<1e-6]
            manual_targets = {}
            for rr in manual:
                target = {k:rr[k] for k in ('chamber','type','material','diameter_mm')}
                target['aspect']=rr.get('aspect',1.)
                key = _description(target)
                if key not in manual_targets:
                    manual_targets[key] = (target,_group_mass(cohorts,target),
                                           _group_count(cohorts,target))
            _install_manual(operating, cohorts, now)
            for target, before_t, before_n in manual_targets.values():
                after_t = _group_mass(cohorts, target)
                after_n = _group_count(cohorts, target)
                logs['media_changes'].append({
                    'Час наработки':now,'День / час':operation_day(now,days_hours),
                    'Фракция':_description(target),'Операция':'Догрузка из общего журнала',
                    'Было, т':before_t,'Стало, т':after_t,
                    'Изменение, т':after_t-before_t,'Изменение, шт':after_n-before_n})
            for event in operating.get('parameter_events', []):
                if abs(_at_hour(event) - now) > 1e-6: continue
                key = event['parameter']
                after = float(event['value'])
                before = _set_parameter(operating, key, after)
                logs['parameter_changes'].append({
                    'Час наработки': now, 'День / час': operation_day(now, days_hours),
                    'Переменная': PARAMETERS[key][0], 'Было': before,
                    'Стало': after, 'Единица': PARAMETERS[key][1]})
            for event in operating.get('cement_events', []):
                if abs(_at_hour(event) - now) > 1e-6: continue
                before = profile_name(operating)
                after = event['profile']
                # Смена марки сама по себе меняет ТРЕБОВАНИЯ, а не мгновенно
                # фракционный состав цемента. Поэтому измеренное/модельное значение
                # может совпадать до и после этой записи, и это не ошибка.
                before_quality = quality_at(_runtime_quality_config(operating, now), cohorts, samples=2)
                operating['cement_profile'] = after
                after_quality = quality_at(_runtime_quality_config(operating, now), cohorts, samples=2)
                for key, label in METRICS:
                    logs['cement_changes'].append({
                        'Час наработки': now, 'День / час': operation_day(now, days_hours),
                        'Показатель / сито': label,
                        'Марка до': before, 'Значение до': float(before_quality[key]),
                        'Цели до': _range_label(PROFILES[before].get(key)),
                        'Марка после': after, 'Значение после': float(after_quality[key]),
                        'Цели после': _range_label(PROFILES[after].get(key))})
            for event in operating.get('media_events', []):
                if abs(_at_hour(event) - now) > 1e-6: continue
                target = event['target']
                before_t = _group_mass(cohorts, target)
                before_n = _group_count(cohorts, target)
                _change_media(operating, cohorts, event)
                after_t = _group_mass(cohorts, target)
                after_n = _group_count(cohorts, target)
                logs['media_changes'].append({
                    'Час наработки': now, 'День / час': operation_day(now, days_hours),
                    'Фракция': _description(target),
                    'Операция': 'Догрузка' if event['direction']=='add' else 'Выгрузка',
                    'Было, т': before_t, 'Стало, т': after_t,
                    'Изменение, т': after_t-before_t,
                    'Изменение, шт': after_n-before_n})
        planned_actions = actions if actions is not None else ([action] if action else [])
        for planned in planned_actions:
            if abs(now - float(planned['hour'])) > 1e-6:
                continue
            target = planned['target']
            before_t = _group_mass(cohorts, target)
            before_n = _group_count(cohorts, target)
            _change_media(operating, cohorts, planned)
            logs['media_changes'].append({
                'Час наработки': now, 'День / час': operation_day(now, days_hours),
                'Фракция': _description(target),
                'Операция': 'Предлагаемая догрузка' if planned['direction'] == 'add'
                            else 'Предлагаемая выгрузка',
                'Было, т': before_t, 'Стало, т': _group_mass(cohorts, target),
                'Изменение, т': _group_mass(cohorts, target) - before_t,
                'Изменение, шт': _group_count(cohorts, target) - before_n})
        if now in observed or idx == 0 or idx == len(times)-1:
            entry = _config_row(operating, cohorts, now, reference, wear_cumulative_t)
            records.append(entry)
            if capture_states:
                states[now] = deepcopy(cohorts)
                if runtime_states is not None:
                    runtime_states[now] = deepcopy(operating)
            if stop_at_first_failure and not entry['ok']:
                return records, states, logs
        if idx < len(times)-1:
            mass_before = sum(cohort_mass(c) for c in cohorts)
            removed_before = sum(c.get('removed_kg', 0.) for c in cohorts)
            _wear_step(operating, cohorts, reference, now, times[idx+1])
            mass_after = sum(cohort_mass(c) for c in cohorts)
            removed_after = sum(c.get('removed_kg', 0.) for c in cohorts)
            wear_cumulative_t += max(0.,
                mass_before-mass_after-(removed_after-removed_before))/1000.0
    return records, states, logs


# Большая часть вычислений — CPU-bound Python. Используются отдельные
# ПРОЦЕССЫ, а не Python threads (GIL). Все объекты контекста сериализуемы:
# Qt виджеты, matplotlib canvas и сигналы сюда никогда не передаются.
_PROCESS_CONTEXT = None


def _init_trial_worker(operating, cohorts, wear_t, times, observed,
                       reference, start, end):
    global _PROCESS_CONTEXT
    _PROCESS_CONTEXT = (operating, cohorts, wear_t, times, observed,
                        reference, start, end)


def _violation_distance(row: dict, cfg: dict) -> float:
    """Нормированная величина выхода за активные диапазоны.

    Значение используется ТОЛЬКО при отборе кандидатов, не как мера
    вероятности или физическая оценка качества.
    """
    rules = PROFILES.get(row.get('profile'), {})
    err = 0.0
    for key in ('r008', 'r0045', 'blaine_proxy'):
        bounds = rules.get(key)
        if not bounds:
            continue
        actual = float(row[key])
        for name, direction in (('min', -1), ('max', 1)):
            bound = bounds.get(name)
            if bound is None:
                continue
            err += max(0., direction*(actual-bound)) / max(1., abs(bound))
    q_min = float(cfg.get('target_product_tph', 0.))
    err += max(0., q_min-float(row['throughput'])) / max(1., abs(q_min))
    return err


def _eval_trial(indexed_actions):
    index, actions = indexed_actions
    operating, cohorts, wear_t, times, observed, reference, start, end = _PROCESS_CONTEXT
    try:
        records, _, _ = _perform(operating, times, observed, reference,
                                 actions=actions, resume=(operating, cohorts, wear_t),
                                 stop_at_first_failure=True)
    except (ValueError, ZeroDivisionError, ArithmeticError, OverflowError):
        return index, {'duration': 0., 'distance': float('inf'), 'error': True}
    if not records:
        return index, {'duration': 0., 'distance': float('inf'), 'error': True}
    failing = next((row for row in records if not row['ok']), None)
    duration = (float(failing['hour']) if failing else end) - start
    distance = _violation_distance(failing, operating) if failing else 0.
    return index, {'duration': max(0., duration), 'distance': distance,
                   'error': False}


class _TrialExecutor:
    """Один многопроцессный пул для всех уровней поиска 1/2/3 операций.

    Ошибку запуска spawn не скрываем как якобы многопоточность: возвращаем
    фактическое число процессов и причину переключения на последовательный режим.
    """

    def __init__(self, cfg, cohorts, wear_t, times, observed, reference,
                 start, end, workers):
        self.context = (cfg, cohorts, wear_t, times, observed,
                        reference, start, end)
        self.workers = max(1, workers)
        self.actual_workers = 1
        self.warning = None
        self.pool = None
        _init_trial_worker(*self.context)

    def __enter__(self):
        if self.workers > 1:
            try:
                self.pool = ProcessPoolExecutor(
                    max_workers=self.workers, mp_context=get_context('spawn'),
                    initializer=_init_trial_worker, initargs=self.context)
            except (OSError, RuntimeError, BrokenProcessPool, ImportError) as exc:
                self.warning = f'Не удалось создать пул процессов: {exc}'
        return self

    def __exit__(self, *exc):
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.pool = None
        return False

    def evaluate(self, combos):
        jobs = list(enumerate(combos))
        if self.pool is not None and len(jobs) >= 4:
            try:
                results = list(self.pool.map(_eval_trial, jobs,
                                          chunksize=max(1, len(jobs)//(self.workers*5))))
                self.actual_workers = self.workers
                return results
            except (OSError, RuntimeError, BrokenProcessPool, EOFError) as exc:
                self.warning = f'Параллельный запуск завершился ошибкой; применён последовательный режим: {exc}'
                self.pool.shutdown(wait=True, cancel_futures=True)
                self.pool = None
                self.actual_workers = 1
                _init_trial_worker(*self.context)
        return [_eval_trial(job) for job in jobs]


def _group_signature(action: dict) -> tuple:
    row = action['target']
    return (int(row['chamber']), str(row['type']), str(row['material']),
            float(row['diameter_mm']), float(row.get('aspect', 1)))


def _different_groups(actions: list[dict]) -> bool:
    keys = [_group_signature(action) for action in actions]
    return len(keys) == len(set(keys))


def _combo_fill_ok(cfg: dict, cohorts: list[dict], actions: list[dict]) -> bool:
    """Реальное заполнение после ВСЕХ операций, включая смешанные формы тел."""
    if not _different_groups(actions):
        return False
    trial = deepcopy(cohorts)
    try:
        for action in actions:
            _change_media(cfg, trial, action)
        fills = chamber_info(cfg, trial)
    except (ValueError, ArithmeticError, ZeroDivisionError, OverflowError):
        return False
    return all(MIN_FILL <= row['fill_j'] <= MAX_FILL for row in fills)


def _grouped_candidate_subset(candidates: list[dict], limit: int) -> list[dict]:
    """Равномерно берём фракции, а не только первые 60 операций первой камеры."""
    if len(candidates) <= limit:
        return candidates
    groups = {}
    for cand in candidates:
        key = (_group_signature(cand), cand['direction'])
        groups.setdefault(key, []).append(cand)
    result = []
    lists = list(groups.values())
    for layer in range(max(map(len, lists))):
        for rows in lists:
            if layer < len(rows):
                result.append(rows[layer])
                if len(result) == limit:
                    return result
    return result


def _ranked_seeds(candidates: list[dict], responses: list[tuple], limit: int) -> list[dict]:
    """Лучшие одиночные улучшения + разные группы для комбинирования."""
    ranks = sorted(responses, key=lambda x: (
        -x[1]['duration'], x[1]['distance'],
        candidates[x[0]]['tons'], x[0]))
    best = []
    used = set()
    # Сначала разнообразные фракции: без этого пары из второго отсека не попадут.
    for idx, score in ranks:
        if score['error']:
            continue
        signature = (_group_signature(candidates[idx]), candidates[idx]['direction'])
        if signature not in used:
            used.add(signature)
            best.append(candidates[idx])
            if len(best) >= limit // 2:
                break
    for idx, score in ranks:
        if score['error']:
            continue
        action = candidates[idx]
        if action not in best:
            best.append(action)
            if len(best) >= limit:
                break
    return best


def _score(actions: list[dict], metric: dict) -> tuple:
    # Максимум часов в норме, затем МЕНЬШЕ операций и суммарной массы.
    return (metric['duration'], -len(actions),
            -sum(abs(float(a['tons'])) for a in actions), -metric['distance'])


def _emit(callback, stage, payload):
    if callback is not None:
        callback(stage, payload)


def simulate_operation_timeline(cfg: dict, *, optimize: bool = True,
                                observations: int = 100, candidate_limit: int = 84,
                                parallel: bool = True, max_workers: int | None = None,
                                max_actions: int = 3, pair_limit: int = 120,
                                triple_limit: int = 60,
                                progress_callback=None) -> dict:
    """Вычислить работу и выбрать лучшую среди проверенных комбинаций 1–3 операций.

    Качество считается в дискретных контрольных точках, а не непрерывно.
    Комбинации — догрузка/выгрузка ЦЕЛЫХ штук разных фракций одновременно.
    Используется beam-search с проверкой заполнения камер: не глобальный оптимум.
    При равном периоде соответствия предпочитается меньше операций и меньшая масса.
    """
    if not 1 <= max_actions <= 3:
        raise ValueError('max_actions должен быть от 1 до 3')
    cfg = deepcopy(cfg)
    total = hours_of_operation(cfg)
    cfg['horizon_h'] = total
    _validate_events(cfg, total)
    ticks, observed = _clock_grid(cfg, observations)
    for category in ('cement_events', 'media_events', 'parameter_events'):
        for event in cfg.get(category, []):
            t = round(_at_hour(event), 9)
            ticks.append(t)
            observed.add(t)
    ticks = sorted(set(ticks))
    reference = _reference_weight(cfg)
    runtime_states = {}
    baseline, states, logs = _perform(cfg, ticks, observed, reference,
                                     capture_states=True, runtime_states=runtime_states)
    bad = next((item for item in baseline if not item['ok']), None)
    result = {'hours': total, 'days': int(cfg.get('simulation_days', 5)),
              'hours_per_day': float(cfg.get('simulation_hours_per_day', 8.)),
              'profile': profile_name(cfg), 'baseline': baseline,
              'optimized': None, 'action': None, 'actions': [],
              'first_bad': bad, 'evaluated': 0, 'parallel_workers': 1,
              'search_levels': {}, **logs}
    _emit(progress_callback, 'baseline', {'points':len(baseline),
          'first_bad_hour':bad['hour'] if bad else None})
    if bad is None:
        result['status'] = ('За весь период заданных изменений на контрольных '
                            'точках выходов за цели не обнаружено. Коррекция не нужна.')
        return result
    if not optimize:
        result['status'] = 'Обнаружено отклонение от действующих на тот час технологических целей.'
        return result
    # Q(t) в данном ядре задано извне и не зависит от состава шаров.
    # Нет смысла нагружать все ядра поиском при нарушенной уставке Q.
    if any('Производительность' in str(v) for row in baseline
           for v in row.get('violations', [])):
        result['status'] = ('В прогнозе нарушен минимум производительности Q. '
                            'Загрузкой мелющих тел его исправить нельзя: Q(t) '
                            'задаётся оператором независимо от состава загрузки. '
                            'Измените режим/подачу или минимальную уставку Q.')
        result['blocked_by_throughput'] = True
        return result

    ix = baseline.index(bad)
    when = baseline[max(0, ix-1)]['hour']
    snap = (runtime_states[when], states[when],
            baseline[max(0, ix-1)]['wear_cumulative_t'])
    remaining = [t for t in ticks if t >= when-1e-7]
    observed_remaining = {t for t in observed if t >= when-1e-7} | {when}
    raw = [{**cand, 'hour': when}
           for cand in _candidates(snap[0], snap[1], when)]
    candidates = _grouped_candidate_subset(raw, max(1, candidate_limit))
    available = os.cpu_count() or 1
    wanted = max(1, min(max_workers or max(1, available-1), 8, available,
                        max(1, len(candidates)))) if parallel else 1
    best = None
    evaluated = 0
    with _TrialExecutor(snap[0], snap[1], snap[2], remaining,
                        observed_remaining, reference, when, total, wanted) as executor:
        singles = [[c] for c in candidates]
        single_scores = executor.evaluate(singles)
        evaluated += len(single_scores)
        result['search_levels']['singles'] = len(single_scores)
        best = _select_best(best, singles, single_scores)
        _emit(progress_callback, 'singles', {'evaluated': evaluated,
             'best_hours': best['metric']['duration'] if best else 0.,
             'workers': executor.actual_workers})

        if max_actions >= 2 and len(candidates) > 1 and (
                best is None or best['metric']['duration'] < total-when-1e-9):
            seeds = _ranked_seeds(candidates, single_scores, 20)
            pairs = []
            seen = set()
            for i, a in enumerate(seeds):
                for b in candidates:
                    if a == b:
                        continue
                    combo = [a, b]
                    sigs = tuple(sorted(((_group_signature(x),x['direction'],x['pieces'])
                                         for x in combo), key=str))
                    if sigs in seen or not _combo_fill_ok(snap[0], snap[1], combo):
                        continue
                    seen.add(sigs)
                    pairs.append(combo)
                    if len(pairs) >= pair_limit:
                        break
                if len(pairs) >= pair_limit:
                    break
            pair_scores = executor.evaluate(pairs)
            evaluated += len(pair_scores)
            result['search_levels']['pairs'] = len(pair_scores)
            best = _select_best(best, pairs, pair_scores)
            _emit(progress_callback, 'pairs', {'evaluated': evaluated,
                 'best_hours': best['metric']['duration'] if best else 0.,
                 'workers': executor.actual_workers})
        else:
            pairs, pair_scores = [], []

        if max_actions >= 3 and pairs and (
                best is None or best['metric']['duration'] < total-when-1e-9):
            ranked_pairs = sorted(pair_scores, key=lambda x:(
                -x[1]['duration'], x[1]['distance'],
                sum(a['tons'] for a in pairs[x[0]]),x[0]))
            top_pairs = [pairs[idx] for idx, metric in ranked_pairs[:8] if not metric['error']]
            seeds = _ranked_seeds(candidates, single_scores, 20)
            triples = []
            seen = set()
            for pair in top_pairs:
                for action in seeds:
                    combo = pair + [action]
                    signature = tuple(sorted(((_group_signature(a),a['direction'],a['pieces'])
                                              for a in combo), key=str))
                    if signature in seen or not _combo_fill_ok(snap[0], snap[1], combo):
                        continue
                    seen.add(signature)
                    triples.append(combo)
                    if len(triples) >= triple_limit:
                        break
                if len(triples) >= triple_limit:
                    break
            triple_scores = executor.evaluate(triples)
            evaluated += len(triple_scores)
            result['search_levels']['triples'] = len(triple_scores)
            best = _select_best(best, triples, triple_scores)
            _emit(progress_callback, 'triples', {'evaluated': evaluated,
                 'best_hours': best['metric']['duration'] if best else 0.,
                 'workers': executor.actual_workers})
        result['parallel_workers'] = executor.actual_workers
        if executor.warning:
            result['parallel_warning'] = executor.warning

    result['evaluated'] = evaluated
    if best is None or best['metric']['duration'] <= 0:
        result['status'] = ('Не найдена допустимая комбинация из 1–3 операций '
                            'с проверенными фракциями и пределами заполнения. '
                            'Может потребоваться смена режима, состава загрузки '
                            'или иной момент вмешательства.')
        return result
    actions = best['actions']
    suffix, _, _ = _perform(snap[0], remaining, observed_remaining, reference,
                            actions=actions, resume=snap)
    prefix = [row for row in baseline if row['hour'] < when-1e-7]
    result['optimized'] = prefix + suffix
    result['actions'] = [{**a, 'valid_hours':best['metric']['duration'],
                          'valid_to':when+best['metric']['duration']} for a in actions]
    # В старых формах .action означает ОДНО действие; смешанный план передаём
    # через .actions, чтобы случайно не записать лишь первую догрузку.
    result['action'] = result['actions'][0] if len(actions)==1 else None
    result['status'] = ('Предложена ' + ('одиночная коррекция' if len(actions)==1
                       else f'комбинация из {len(actions)} операций') + ': '
                       f'{best["metric"]["duration"]:g} ч в заданных пределах '
                       'после вмешательства на контрольной сетке. '
                       'Подбор ограничен фракциями и моментом первого нарушения.')
    return result


def _select_best(previous, combos, metrics):
    selected = previous
    for index, metric in metrics:
        if metric['error']:
            continue
        combo = combos[index]
        rank = _score(combo, metric)
        if selected is None or rank > selected['rank']:
            selected = {'actions': combo, 'metric':metric, 'rank':rank}
    return selected
