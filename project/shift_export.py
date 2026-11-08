"""Листы Excel для симуляции смен и сравнения двух траекторий."""
from __future__ import annotations

from model import mass_kg
from shift_simulation import simulate_shifts, operation_day
from production_planning import PROFILES


def extend_shift_report(wb, report, cfg):
    result=simulate_shifts(cfg, optimize=True, observations=85)
    baseline=result['baseline']
    improved={round(row['hour'],8):row for row in (result.get('optimized') or [])}
    rows=[]
    for b in baseline:
        a=improved.get(round(b['hour'],8))
        rows.append({
            'Наработка, ч':b['hour'],
            'Рабочий день / час':operation_day(b['hour'],result['hours_per_day']),
            'R0,08 без':b['r008'], 'R0,08 после':a['r008'] if a else None,
            'R0,045 без':b['r0045'], 'R0,045 после':a['r0045'] if a else None,
            'Блейн без (модель)':b['blaine_proxy'],
            'Блейн после (модель)':a['blaine_proxy'] if a else None,
            'Q, т/ч':b['throughput'],
            'Без операции в норме':b['ok'],
            'После операции в норме':a['ok'] if a else None,
        })
    ws,cols,last=report.sheet('Симуляция_смен',rows)
    if len(rows)>1:
        for name,src,dst,place,units in (
            ('R0,08','R0,08 без','R0,08 после','O2','%'),
            ('R0,045','R0,045 без','R0,045 после','O22','%'),
            ('Блейн (прокси)','Блейн без (модель)','Блейн после (модель)','O42','см²/г')):
            traces=[(cols.index(src),'Без операции')]
            if improved:
                traces.append((cols.index(dst),'После операции'))
            report.line(ws,name+': сравнение',0,traces,last,cell=place,y_label=units)
    act=result.get('action')
    if act:
        r=act['target']
        pcs=act['tons']*1000/mass_kg(r,r['diameter_mm'])
        table=[{'Состояние':result['status'],
                'Операция':'Догрузка' if act['direction']=='add' else 'Выгрузка',
                'Час работы':act['hour'],
                'День / час':operation_day(act['hour'],result['hours_per_day']),
                'Камера':r['chamber'],'Тип':r['type'],
                'Материал':r['material'],'Диаметр, мм':r['diameter_mm'],
                'Масса, т':act['tons'],'Расчётное количество, шт':pcs,
                'В пределах целей после, ч':act['valid_hours']}]
    else:
        table=[{'Состояние':result['status'],'Операция':'Нет'}]
    ws,_,last=report.sheet('Коррекция_загрузки',table)
    ws.write(last+2,0,'Источник диапазонов: сохранённый HTML; технологические цели, не обязательные требования ГОСТ.')
    ws.write(last+3,0,'Надёжность: модель не прошла полную заводскую калибровку; Блейн расчётный.')
    ws.write(last+4,0,'Производительность Q задаётся извне и при изменении мелющих тел не пересчитывается физически.')
    ws.write(last+5,0,'Нормативы проверяются по дискретным контрольным точкам, а не в непрерывном времени.')
    ws.write(last+6,0,f'Проверено альтернативных одиночных операций: {result["evaluated"]}')
    ws, _, last = report.sheet('Границы_цемента', [
        {'Профиль':result['profile'],'Показатель':key,
         'Минимум':bound.get('min'),'Максимум':bound.get('max'),
         'Тип':'Технологическая карта из HTML (не ГОСТ)'}
        for key,bound in PROFILES[result['profile']].items()
    ] or [{'Профиль':result['profile'],'Показатель':'Нет ограничений'}])
