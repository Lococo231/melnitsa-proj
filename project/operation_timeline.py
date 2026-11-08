"""Рабочая хронология одного барабана, с изменениями на часах наработки.

Раздельные журналы: марки цемента (технологические целевые карты), операции
над мелющими телами (строго целые штуки), параметры оборудования. Состояние
пересчитывается в каждой точке, а не строится из неподвижных иллюстраций.

Это модель, не управление установкой. Геометрические изменения разрешены как
сценарии замены конфигурации: диаметр работающего барабана физически не меняется.
"""
from __future__ import annotations

from copy import deepcopy
import math

from model import (MATERIALS, mass_kg, piece_count, initial_cohorts, cohort_mass,
                   chamber_info, throughput_at, quality_at, config_at_time,
                   coefficient_at)
from production_planning import PROFILES, profile_name, assessments
from shift_simulation import (_clock_grid, _wear_step, _install_manual,
                              _reference_weight, _candidates, _change_media,
                              hours_of_operation, operation_day)

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


def _config_row(cfg: dict, cohorts: list[dict], hour: float, reference: float,
                wear_cumulative_t: float) -> dict:
    q = quality_at(config_at_time(cfg, hour), cohorts, samples=2)
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
             capture_states: bool = False) -> tuple[list[dict], dict, dict]:
    operating = deepcopy(cfg)
    cohorts = initial_cohorts(operating)
    records = []
    states = {}
    logs = {'cement_changes': [], 'media_changes': [], 'parameter_changes': []}
    wear_cumulative_t = 0.
    days_hours = float(operating.get('simulation_hours_per_day', 8))
    for idx, now in enumerate(times):
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
            before_quality = quality_at(config_at_time(operating, now), cohorts, samples=2)
            operating['cement_profile'] = after
            after_quality = quality_at(config_at_time(operating, now), cohorts, samples=2)
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
        if action is not None and abs(now-action['hour']) <= 1e-6:
            target = action['target']
            before_t = _group_mass(cohorts, target)
            before_n = _group_count(cohorts, target)
            _change_media(operating, cohorts, action)
            logs['media_changes'].append({
                'Час наработки': now, 'День / час': operation_day(now, days_hours),
                'Фракция': _description(target), 'Операция': 'Рекомендованная коррекция',
                'Было, т': before_t, 'Стало, т': _group_mass(cohorts, target),
                'Изменение, т': _group_mass(cohorts,target)-before_t,
                'Изменение, шт': _group_count(cohorts,target)-before_n})
        if now in observed or idx == 0 or idx == len(times)-1:
            records.append(_config_row(operating, cohorts, now, reference, wear_cumulative_t))
            if capture_states:
                states[now] = deepcopy(cohorts)
        if idx < len(times)-1:
            mass_before = sum(cohort_mass(c) for c in cohorts)
            removed_before = sum(c.get('removed_kg', 0.) for c in cohorts)
            _wear_step(operating, cohorts, reference, now, times[idx+1])
            mass_after = sum(cohort_mass(c) for c in cohorts)
            removed_after = sum(c.get('removed_kg', 0.) for c in cohorts)
            wear_cumulative_t += max(0.,
                mass_before-mass_after-(removed_after-removed_before))/1000.0
    return records, states, logs


def simulate_operation_timeline(cfg: dict, *, optimize: bool = True,
                                observations: int = 100, candidate_limit: int = 60) -> dict:
    """Пересчёт по всем событиям и сравнение с одной дополнительной коррекцией.

    Модельные параметры переключаются в заданном часу, износ и дробление
    продолжаются от текущей партии мелющих тел, без перезапуска истории.
    """
    cfg = deepcopy(cfg)
    total = hours_of_operation(cfg)
    cfg['horizon_h'] = total
    _validate_events(cfg, total)
    ticks, observed = _clock_grid(cfg, observations)
    # Не пропускаем смену карты/геометрии между численными узлами.
    for category in ('cement_events', 'media_events', 'parameter_events'):
        for event in cfg.get(category, []):
            t = round(_at_hour(event), 9)
            ticks.append(t)
            observed.add(t)
    ticks = sorted(set(ticks))
    reference = _reference_weight(cfg)
    baseline, states, logs = _perform(cfg, ticks, observed, reference, capture_states=True)
    bad = next((item for item in baseline if not item['ok']), None)
    result = {'hours': total, 'days': int(cfg.get('simulation_days', 5)),
              'hours_per_day': float(cfg.get('simulation_hours_per_day', 8.)),
              'profile': profile_name(cfg), 'baseline': baseline, 'optimized': None,
              'action': None, 'first_bad': bad, 'evaluated': 0,
              **logs}
    if bad is None:
        result['status'] = ('За весь период заданных изменений на контрольных '
                            'точках выходов за цели не обнаружено. Догрузка не требуется.')
        return result
    if not optimize:
        result['status'] = 'Обнаружено отклонение от действующих на тот час технологических целей.'
        return result
    ix = baseline.index(bad)
    when = baseline[max(0, ix-1)]['hour']
    cohorts_at = states[when]
    best = None
    # Предварительно учтём все запланированные вмешательства в хронологии;
    # предлагаемая догрузка не заменяет и не стирает их.
    for number, cand in enumerate(_candidates(cfg, cohorts_at, when)):
        if number >= candidate_limit: break
        action = {**cand, 'hour': when}
        try:
            trial, _, trial_logs = _perform(cfg, ticks, observed, reference, action=action)
        except (ValueError, ZeroDivisionError, ArithmeticError, OverflowError):
            continue
        result['evaluated'] += 1
        suffix = [row for row in trial if row['hour'] >= when - 1e-6]
        if not suffix or not suffix[0]['ok']:
            continue
        next_bad = next((row for row in suffix if not row['ok']), None)
        duration = (next_bad['hour'] if next_bad else total) - when
        score = (duration, -float(action['tons']))
        if best is None or score > best['score']:
            best = {'score': score, 'action': action, 'trial': trial,
                    'logs': trial_logs, 'duration': duration}
    if best is None:
        result['status'] = ('Не найдено допустимой одиночной коррекции: нужно изменить '
                            'подачу, режим или несколько фракций; требуется проверка технологом.')
        return result
    chosen = best['action']
    result['action'] = {**chosen, 'valid_hours': best['duration'],
                        'valid_to': when + best['duration']}
    result['optimized'] = best['trial']
    result['status'] = ('После запланированных изменений рассчитан дополнительный '
                        'сценарий одной коррекции; время соответствия после неё '
                        f'{best["duration"]:g} ч по проверенным точкам.')
    return result