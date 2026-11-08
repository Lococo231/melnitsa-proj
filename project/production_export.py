"""Дополнительные листы Excel в стиле заводских диаграмм помола.

Расчётные фракционные/полные остатки не выдаются за фактический лабораторный
протокол: столбцы веса пробы и остатка в граммах намеренно остаются пустыми.
"""
from __future__ import annotations
from model import mass_kg
from production_planning import (assessments, plan_reload, profile_name,
                                 starting_media)

from model import piece_count


def extend_report(wb, report, cfg, run, final_quality):
    """Вызывается ДО wb.close() в существующем export_excel()."""
    profile = profile_name(cfg)
    q = run['rows'][-1]['Производительность, т/ч']
    checks = assessments(cfg, final_quality, q)
    check_rows = [{
        'Показатель': r['label'], 'Прогноз': r['value'],
        'Минимум': r['minimum'], 'Максимум': r['maximum'],
        'Соответствие': 'ДА' if r['ok'] else 'НЕТ',
        'Тип требования': 'Технологическая карта / уставка' if r['key'] != 'throughput'
                            else 'Заданный минимум выпуска',
    } for r in checks]
    report.sheet('Нормы_и_выпуск', check_rows)

    load = starting_media(cfg)
    sh, cols, end_row = report.sheet('Начальная_загрузка', load)
    if load:
        sh.write(end_row + 1, 0, 'ИТОГО, т', report.emphasis)
        sh.write_number(end_row + 1, cols.index('Начальная масса, т'),
                        sum(r['Начальная масса, т'] for r in load), report.emphasis)
        sh.write(end_row + 3, 0, 'Количество тел целое, масса приведена к нему; округление half-up при вводе тонн.')

    plan = plan_reload(cfg, run)
    plan_rows = []
    for media in plan['rows']:
        count = piece_count(media, media['initial_t'])
        plan_rows.append({'Камера': media['chamber'], 'Тип': media['type'],
                          'Материал': media['material'], 'Ø, мм': media['diameter_mm'],
                          'L/D': media['aspect'], 'Догрузить, т': media['initial_t'],
                          'Количество, шт': count})
    if not plan_rows:
        plan_rows = [{'Состояние': 'Нулевой расчётный объём / отсутствует допустимый сценарий'}]
    sh, _, end = report.sheet('План_догрузки_к_концу', plan_rows)
    sh.write(end + 2, 0, 'Технологическая карта: ' + profile)
    sh.write(end + 3, 0, 'Решение: ' + plan['status'])
    sh.write(end + 4, 0, 'Всего, т:')
    sh.write_number(end + 4, 1, plan['total_t'])
    sh.write(end + 5, 0, 'План на конец горизонта; динамическая производительность в модели задаётся извне.')
    sh.write(end + 6, 0, 'Без подтверждения лаборатории и калибровки модель не удостоверяет качество цемента.')

    # Аналог заводской схемы: проба/точка, место, секции каждого сита.
    sieve_sizes = sorted(cfg['sieves_mm'], reverse=True)
    samples = final_quality['samples']
    ws = wb.add_worksheet('Пробы_по_длине')
    ws.hide_gridlines(2)
    ws.freeze_panes(4, 3)
    ws.set_column(0, 0, 12)
    ws.set_column(1, 1, 20)
    ws.set_column(2, 2, 15)
    ws.set_column(3, 3 + 3*len(sieve_sizes)-1, 21)
    last_col = 2 + 3*len(sieve_sizes)
    ws.merge_range(0, 0, 0, max(last_col, 4),
                   'ДИАГРАММА ПОМОЛА · расчётное распределение по длине', report.title)
    ws.set_row(0, 36)
    ws.merge_range(1, 0, 1, max(last_col, 4),
                   'Форма по образцам производства; веса проб не измерялись, поэтому ячейки «г» пустые.')
    ws.merge_range(2, 0, 3, 0, '№ пробы', report.header)
    ws.merge_range(2, 1, 3, 1, 'Место, м', report.header)
    ws.merge_range(2, 2, 3, 2, 'Камера', report.header)
    for i, size in enumerate(sieve_sizes):
        first = 3 + 3*i
        ws.merge_range(2, first, 2, first+2, f'Сито № {size:g} мм', report.header)
        for k, title in enumerate(('Остаток, г (не измер.)',
                                   'Фракц. остаток, %', 'Полный остаток, %')):
            ws.write(3, first+k, title, report.header)
    ws.set_row(2, 26)
    ws.set_row(3, 42)
    for idx, row in enumerate(samples):
        r = idx + 4
        ws.write_number(r, 0, idx+1, report.numeric)
        ws.write_number(r, 1, row['Расстояние по камерам, м'], report.numeric)
        ws.write_number(r, 2, row.get('Камера', 1), report.numeric)
        prev = 0.0
        for j, size in enumerate(sieve_sizes):
            # R(s) -- полный (кумулятивный) остаток на данном сите.
            total = max(0.0, min(100.0, float(row[f'R{size:g}, %'])))
            fraction = max(0.0, total - prev)
            ws.write_blank(r, 3 + 3*j, None)
            ws.write_number(r, 3 + 3*j + 1, fraction, report.numeric)
            ws.write_number(r, 3 + 3*j + 2, total, report.numeric)
            prev = total
    if samples:
        ws.autofilter(3, 0, len(samples) + 3, last_col)
    ws.write(5 + len(samples), 0, 'Раздел камер:')
    ws.write(5 + len(samples), 1, cfg['mills'][0]['chambers'][0]['length_m'])
    ws.write(6 + len(samples), 0, 'Профиль:')
    ws.write(6 + len(samples), 1, profile)
    ws.write(7 + len(samples), 0, 'Проверка проводится по расчётным значениям, а не по протоколу физиспытаний.')