"""UI-independent helpers: one chronology for all time plots and recommendations.

No Qt, no hidden simulation. The returned evidence is about a bounded search,
not an engineering guarantee or a factory-standard certification.
"""
from __future__ import annotations

from math import isfinite


def analysis_hours(result: dict) -> float:
    rows = result.get('baseline') or []
    if not rows:
        return 0.0
    hours = float(result['hours'])
    last = float(rows[-1]['hour'])
    if not isfinite(hours) or not isfinite(last) or abs(hours-last) > 1e-4:
        raise ValueError('Результаты хронологии не охватывают весь период работы')
    return hours


def _sum_production(rows):
    # The timeline grid contains Q change events; left rectangle integration.
    running = 0.0
    cumulative = [0.0]
    for first, second in zip(rows, rows[1:]):
        dt = float(second['hour']) - float(first['hour'])
        if dt < 0:
            raise ValueError('Неупорядоченные часы в результатах симуляции')
        running += float(first['throughput']) * dt
        cumulative.append(running)
    return cumulative


def overview_series(result: dict) -> list[dict]:
    """Every series is sampled on the exact same horizon as the simulation."""
    analysis_hours(result)
    rows = result['baseline']
    hours = [float(r['hour']) for r in rows]
    # Timeline fields are already computed with all material, cement and mode events.
    return [
        dict(name='Производительность Q(t)',unit='т/ч',hours=hours,
             values=[float(r['throughput']) for r in rows]),
        dict(name='Накопленный выпуск',unit='т',hours=hours,
             values=_sum_production(rows)),
        dict(name='Масса загрузки',unit='т',hours=hours,
             values=[float(r['media_mass_t']) for r in rows]),
        dict(name='Накопленный износ',unit='т',hours=hours,
             values=[float(r['wear_cumulative_t']) for r in rows]),
        dict(name='Число мелющих тел',unit='шт',hours=hours,
             values=[int(r['piece_count']) for r in rows]),
        dict(name='R0,08',unit='%',hours=hours,
             values=[float(r['r008']) for r in rows]),
    ]


def recommendation(result: dict, cfg: dict) -> dict:
    """Explain the bounded optimizer result and the true blocker, if any."""
    analysis_hours(result)
    actions = result.get('actions') or ([] if not result.get('action') else [result['action']])
    bad = result.get('first_bad')
    if bad is None:
        headline = 'Во все контрольные часы показатели соответствуют заданным целям.'
        reason = ('Коррекция загрузки не требуется. Износ и выпуск прогнозируются только '
                  'в рамках используемой эмпирической модели.')
        return dict(headline=headline, reason=reason, actions=[], feasible=True)
    violations = ', '.join(str(x) for x in bad.get('violations', []))
    when = float(bad['hour'])
    if actions:
        duration = float(actions[0].get('valid_hours', 0.0))
        headline = f'Подобрано операций: {len(actions)}. Действуют с часа {actions[0]["hour"]:g}.'
        reason = (f'Среди проверенных вариантов этот план удерживает показатели в целях '
                  f'{duration:g} ч после вмешательства; первое исходное отклонение — '
                  f'{when:g} ч ({violations}). Целые штуки и заполнение камер проверены. '
                  'Поиск ограничен максимум тремя одновременными операциями и '
                  'дискретными контрольными точками; глобальный оптимум не доказан.')
        return dict(headline=headline,reason=reason,actions=actions,feasible=True)
    if result.get('blocked_by_throughput') or any(
            'производительност' in str(x).lower()
            for row in result.get('baseline', []) for x in row.get('violations', [])):
        reason = ('Минимальный выпуск Q нарушен. В текущей модели Q задаётся '
                  'подачей и не зависит от изменения количества шаров. Поэтому '
                  'догрузка не может математически устранить это отклонение. '
                  'Проверьте фактическую подачу, Q(t) и требуемый минимум.')
    else:
        reason = ('Не найдена допустимая комбинация из проверенных одиночных, парных '
                  'или тройных операций. Возможные причины: недостаточное/избыточное '
                  'заполнение камеры, неподходящий стартовый состав шаров, '
                  'грансостав клинкера, обороты, запас материала или режим подачи. '
                  'Рекомендуется проверить геометрию, диапазоны технологической карты '
                  'и режим помола; алгоритм не перебирает все возможные составы '
                  'и моменты вмешательства.')
    return dict(headline=f'Коррекция не найдена; первое отклонение — {when:g} ч: {violations}.',
                reason=reason, actions=[], feasible=False)


def recommendation_rows(result: dict) -> list[dict]:
    actions = result.get('actions') or ([] if not result.get('action') else [result['action']])
    hours_day=float(result.get('hours_per_day',8))
    rows=[]
    for action in actions:
        hour=float(action['hour'])
        day = int((hour-1e-8)//hours_day)+1 if hour>0 else 1
        target=action['target']
        rows.append({'Наработка, ч':hour,'Рабочий день':day,
                     'Операция':'Догрузка' if action['direction']=='add' else 'Выгрузка',
                     'Камера':int(target['chamber']),'Тип':target['type'],
                     'Материал':target['material'], 'Ø, мм':float(target['diameter_mm']),
                     'Штук':int(action['pieces']), 'Масса, т':float(action['tons'])})
    return rows


def journal_tables(result: dict) -> dict:
    """Output is derived exclusively from model events, never typed into a log."""
    analysis_hours(result)
    return {
        'cement':list(result.get('cement_changes') or []),
        'media':list(result.get('media_changes') or []),
        'parameter':list(result.get('parameter_changes') or []),
    }


def initial_conditions(result: dict) -> list[dict]:
    rows=result.get('baseline') or []
    if not rows:
        return []
    r=rows[0]
    return [{'Состояние':'Начало работы','Час':float(r['hour']),
             'Марка цемента':r['profile'],'Производительность, т/ч':r['throughput'],
             'Масса мелющих тел, т':r['media_mass_t'],'Количество, шт':int(r['piece_count']),
             'Обороты, об/мин':r['rpm'],'Диаметр барабана, м':r['diameter_m']}]
