"""Отрисовка графиков в нескольких ПРОЦЕССАХ через Matplotlib Agg.

Никаких Qt/QWidget/QPixmap в процессе. Возвращаем PNG bytes: Qt лишь
показывает готовые изображения и рисует линию выбранного часа в GUI-потоке.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
import math
import os

COLORS = ('#66cbe1', '#e9ad73', '#95d6ad', '#d4a4ef', '#e5d46f',
          '#9bbbef', '#e2a2b8', '#8de0d6', '#a5cad9')


def _part_png(job):
    # pyplot НЕ импортируем: backend Agg не связан с потоком QApplication.
    import io
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    # Use two physical pixels per display pixel for sharp curves/text.
    # With target_size the image aspect follows the *current Qt pane*.
    pixel_w, pixel_h = job.get('render_px', (1920, 540))
    pixel_w = max(620, min(6400, int(pixel_w)))
    pixel_h = max(270, min(3600, int(pixel_h)))
    dpi = 170
    fig = Figure(figsize=(pixel_w/dpi, pixel_h/dpi), dpi=dpi, facecolor='#162a3d')
    FigureCanvasAgg(fig)
    ax = fig.add_axes([.22 if job.get('category_labels') else .105,
                       .22, .565 if job.get('category_labels') else
                       (.68 if job.get('legend_side') else .845), .62])
    ax.set_facecolor('#162a3d')
    ax.set_title(job['title'], color='#ebf5fc', fontsize=11, pad=7)
    ax.set_ylabel(job.get('unit', ''), color='#aec0ce', fontsize=8)
    ax.set_xlabel('Наработка, ч', color='#aec0ce', fontsize=8)
    ax.tick_params(colors='#aec0ce', labelsize=8)
    ax.grid(True, color='#375267', alpha=.55)
    for spine in ax.spines.values():
        spine.set_color('#44657c')
    tmax = max(0.01, float(job['end']))
    ax.set_xlim(0, tmax)
    vals = []
    for trace in job.get('traces', []):
        x, y = trace['x'], trace['y']
        ys = [float(v) if v is not None else float('nan') for v in y]
        vals.extend(v for v in ys if math.isfinite(v))
        opts = dict(color=trace.get('color', COLORS[0]), lw=1.7,
                    alpha=trace.get('alpha', 1.), label=trace.get('label', ''))
        if trace.get('step'):
            ax.step(x, ys, where='post', **opts)
        else:
            ax.plot(x, ys, ls=trace.get('ls', '-'), **opts)
    for line in job.get('bounds', []):
        xs, ys = line['x'], [float('nan') if v is None else float(v) for v in line['y']]
        vals.extend(v for v in ys if math.isfinite(v))
        ax.step(xs,ys,where='post',color='#ef737a',lw=1.1,ls='--',
                label=line.get('label',''))
    for hour in job.get('vertical', []):
        ax.axvline(hour, color='#a59af0', alpha=.55, lw=1., ls=':')
    if job.get('bad_x'):
        ax.scatter(job['bad_x'],job['bad_y'],s=12,color='#ff5969',zorder=5)
    if job.get('category_labels'):
        names = job['category_labels']
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=7)
        ax.set_ylim(-.5,max(.5,len(names)-.5))
    elif vals:
        low,high=min(vals),max(vals)
        padding=max((high-low)*.12, 0.05 if job.get('unit')=='%' else max(.025,abs(high)*.015))
        ax.set_ylim(low-padding,high+padding)
    if job.get('legend_side') and job.get('traces'):
        ax.legend(fontsize=7,loc='upper left',bbox_to_anchor=(1.01,1.0),
                  frameon=False,labelcolor='#ebf5fc',ncol=1)
    elif job.get('traces') and len(job['traces']) <= 3:
        ax.legend(fontsize=7,loc='upper center',bbox_to_anchor=(.5,1.27),ncol=3,
                  frameon=False,labelcolor='#ebf5fc')
    buf=io.BytesIO()
    fig.savefig(buf,format='png',dpi=dpi,facecolor=fig.get_facecolor())
    return job['id'],buf.getvalue()


def _jobs_for_result(result):
    baseline = result.get('baseline') or []
    if not baseline:
        return []
    optimized = result.get('optimized') or []
    end = result['hours']
    t = [float(row['hour']) for row in baseline]
    o_t = [float(row['hour']) for row in optimized]
    labels = (('r008','R0,08','%'),('r0045','R0,045','%'),
              ('blaine_proxy','Блейн (прокси)','см²/г'),
              ('media_mass_t','Масса мелющих тел','т'))
    changes = sorted({r['Час наработки'] for r in result.get('cement_changes',[])
                      if r.get('Показатель / сито')=='R0,08'})
    actions = result.get('actions') or ([] if result.get('action') is None else [result['action']])
    changes += sorted({float(a['hour']) for a in actions})
    jobs=[]
    for i,(key,title,unit) in enumerate(labels):
        j={'id':f'sim{i}','title':title,'unit':unit,'end':end,'vertical':changes,
           'traces':[{'x':t,'y':[r[key] for r in baseline],
                      'label':'События из журнала','color':COLORS[1]}]}
        if optimized:
            j['traces'].append({'x':o_t,'y':[r[key] for r in optimized],
                                'label':'После коррекции','color':COLORS[0]})
        if i<3:
            j['bounds']=[{'x':t,'y':[r.get(key+suffix) for r in baseline],
                          'label':text} for suffix,text in
                         (('_minimum','Мин.'),('_maximum','Макс.'))]
            bad=[r for r in baseline if (r.get(key+'_minimum') is not None and r[key]<r[key+'_minimum']
                                    or r.get(key+'_maximum') is not None and r[key]>r[key+'_maximum'])]
            j['bad_x']=[r['hour'] for r in bad]
            j['bad_y']=[r[key] for r in bad]
        jobs.append(j)
    # Общий раздел симуляции: прогноз износа не живёт в отдельной вкладке.
    # All these series use exactly the same hours and event-aware baseline.
    jobs.extend([
        {'id':'sim4','title':'Накопленный износ мелющих тел','unit':'т',
         'end':end,'vertical':changes,
         'traces':[{'x':t,'y':[r['wear_cumulative_t'] for r in baseline],
                    'label':'Истирание, т','color':COLORS[0]}]},
        {'id':'sim5','title':'Средние диаметры тел по камерам','unit':'мм',
         'end':end,'vertical':changes,
         'traces':[{'x':t,'y':[r['chamber_diameters_mm'].get(name) for r in baseline],
                    'label':name,'color':COLORS[(i+2)%len(COLORS)]}
                   for i,name in enumerate(sorted({k for r in baseline
                                                  for k in r['chamber_diameters_mm']}))]},
    ])
    # История: 3 разных временных графика.
    groups = sorted({k for r in baseline for k in r.get('media_by_fraction_t',{})})
    jobs.append({'id':'history0','title':'Масса фракций мелющих тел','unit':'т','end':end,
                 'legend_side':True,'vertical':changes,
                 'traces':[{'x':t,'y':[r['media_by_fraction_t'].get(name,0) for r in baseline],
                            'label':name,'color':COLORS[i%len(COLORS)]}
                           for i,name in enumerate(groups)]})
    profiles=list(dict.fromkeys(r['profile'] for r in baseline))
    jobs.append({'id':'history1','title':'Действующая технологическая карта','unit':'',
                 'end':end,'vertical':changes,'category_labels':profiles,
                 'traces':[{'x':t,'y':[profiles.index(r['profile']) for r in baseline],
                            'label':'Вид цемента','color':COLORS[4],'step':True}]})
    mode=[('rpm','Обороты'),('diameter_m','Диаметр'),('power_kw','Мощность'),('fresh_feed_tph','Выпуск')]
    jobs.append({'id':'history2','title':'Изменения параметров от исходных значений','unit':'%',
                 'end':end,'vertical':changes,
                 'traces':[{'x':t,'y':[(float(r[k])/float(baseline[0][k])-1)*100 for r in baseline],
                            'label':name,'color':COLORS[(i+2)%len(COLORS)],'step':True}
                           for i,(k,name) in enumerate(mode) if abs(float(baseline[0][k]))>1e-9]})
    # Износ фракций: заготовки для всех камер и каждой отдельно.
    for kind,filter_ch in [('all',None),('ch1',1),('ch2',2)]:
        for i,(key,title,unit) in enumerate((
            ('diameter_by_fraction_mm','Диаметры фракций','мм'),
            ('media_by_fraction_t','Масса фракций','т'),
            ('wear_by_fraction_g_t','Удельный износ','г/т'))):
            names=sorted({name for row in baseline for name in row.get(key,{})
                          if filter_ch is None or name.startswith(f'К{filter_ch} ')})
            jobs.append({'id':f'fraction_{kind}_{i}','title':title,'unit':unit,
                         'end':end,'legend_side':True,'vertical':changes,
                         'traces':[{'x':t,'y':[r.get(key,{}).get(name) for r in baseline],
                                    'label':name,'color':COLORS[j%len(COLORS)]}
                                   for j,name in enumerate(names)]})
    jobs.extend([
        {'id':'forecast0','title':'Масса загрузки и накопленный износ','unit':'т','end':end,
         'vertical':changes,'traces':[
             {'x':t,'y':[r['media_mass_t'] for r in baseline],'label':'Масса загрузки','color':COLORS[0]},
             {'x':t,'y':[r['wear_cumulative_t'] for r in baseline],
              'label':'Накопленный износ (т)','color':COLORS[1]}]},
        {'id':'forecast1','title':'Средний диаметр по камерам','unit':'мм','end':end,
         'vertical':changes,'traces':[
             {'x':t,'y':[r['chamber_diameters_mm'].get(name) for r in baseline],
              'label':name,'color':COLORS[(i+3)%len(COLORS)]}
             for i,name in enumerate(sorted({k for r in baseline for k in r['chamber_diameters_mm']}))]}
    ])
    # Легенды вынесены СПРАВА от области данных: линии не перекрываются.
    for job in jobs:
        job['legend_side']=True
    return jobs


def render_timeline_images(result:dict, max_workers:int|None=None,
                           enabled:bool=True, groups:tuple[str,...]|None=None,
                           target_size:tuple[int,int]|None=None):
    """Рендерить каждую независимую панель на ядре, передать в UI только bytes.

    Python Qt-функции здесь отсутствуют. Если spawn недоступен — последовательный
    Agg в том же ФОНОВОМ рабочем потоке (не в GUI).
    """
    jobs = _jobs_for_result(result)
    if groups is not None:
        jobs = [j for j in jobs if any(j['id'].startswith(g) for g in groups)]
    if target_size is not None:
        # ALL Matplotlib Agg figures must match the actual visible Qt viewport:
        # simulation, fraction wear, event history and forecast. The PNG has
        # twice the logical pixels, avoiding blurry upscaling on HiDPI screens.
        pane_width, pane_height = target_size
        if pane_width <= 0 or pane_height <= 0:
            raise ValueError('Размер графика должен быть положительным')
        render_size = (2 * int(pane_width), 2 * int(pane_height))
        for job in jobs:
            job['render_px'] = render_size
    if not jobs:
        return {},1,None
    cpu = os.cpu_count() or 1
    workers = min(max(1,max_workers or cpu-1),8,cpu,len(jobs)) if enabled else 1
    if workers <= 1:
        return dict(_part_png(j) for j in jobs),1,None
    try:
        with ProcessPoolExecutor(max_workers=workers,mp_context=get_context('spawn')) as pool:
            data = list(pool.map(_part_png, jobs, chunksize=1))
        return dict(data),workers,None
    except (OSError, RuntimeError, BrokenProcessPool, EOFError) as exc:
        return dict(_part_png(j) for j in jobs),1,str(exc)
