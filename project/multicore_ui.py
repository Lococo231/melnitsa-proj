"""Безопасный GUI-мост для мультипроцессного подбора и готовых PNG-графиков.

Qt-поток только показывает готовые PNG и обновляет виджеты. Matplotlib Agg
рисует каждую временную диаграмму отдельно в дочернем процессе без Qt.
Устанавливается ПОСЛЕ timeline_ui.install(MillWindow).
"""
from __future__ import annotations

from copy import deepcopy
from PySide6.QtCore import QObject, Qt, QRunnable, Signal, QTimer, QThreadPool
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QLabel, QMessageBox, QSizePolicy,
                               QVBoxLayout, QWidget)

import workflow_ui
import timeline_ui
from operation_timeline import simulate_operation_timeline, operation_day
from multicore_render import render_timeline_images


class MultiSignals(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, str, object)
    charts_ready = Signal(int, str, object)
    charts_failed = Signal(int, str, str)


class MultiJob(QRunnable):
    """Один QRunnable управляет процессами с ядрами поиска и рендеринга."""

    def __init__(self, number, cfg, signals):
        super().__init__()
        self.number = number
        self.cfg = cfg
        self.signals = signals

    def run(self):
        try:
            result = simulate_operation_timeline(
                self.cfg, optimize=True, observations=90,
                parallel=True, max_actions=3,
                progress_callback=lambda stage,info:
                    self.signals.progress.emit(self.number,stage,info))
            self.signals.progress.emit(self.number, 'render',
                                       {'message':'Подготовка временных графиков на нескольких ядрах…'})
            try:
                pictures, count, warning = render_timeline_images(result,groups=('sim',))
                result['_plot_images'] = pictures
                result['plot_workers'] = count
                if warning:
                    result['plot_warning'] = warning
            except Exception as exc:
                # Не пропускать расчёт целиком из-за единичной проблемы Agg:
                # Qt умеет отрисовать старый Matplotlib-график как fallback.
                result['plot_warning'] = str(exc)
            self.signals.completed.emit(self.number, result)
        except Exception as exc:
            self.signals.failed.emit(self.number, str(exc))




class DeferredChartJob(QRunnable):
    """Рендерит только открытую вкладку, не замедляя первый результат симуляции."""
    def __init__(self, generation, group, result, signals):
        super().__init__()
        self.generation = generation
        self.group = group
        # Для потоковой безопасности не изменяем исходный словарь результата.
        self.result = result
        self.signals = signals

    def run(self):
        try:
            images,workers,warning = render_timeline_images(
                self.result,groups=(self.group,))
            self.signals.charts_ready.emit(self.generation,self.group,
                                            (images,workers,warning))
        except Exception as exc:
            self.signals.charts_failed.emit(self.generation,self.group,str(exc))


class HourPlotImage(QLabel):
    """Отображение PNG; линия выбранного часа рисуется в Qt GUI потоке."""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.hour = 0.
        self.end = 1.
        self.setScaledContents(True)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.setStyleSheet('background:#162a3d')

    def set_image(self, data, end):
        qimage = QImage.fromData(data,'PNG')
        if qimage.isNull():
            raise ValueError('Невозможно отобразить PNG графика')
        self.setPixmap(QPixmap.fromImage(qimage))
        self.end = max(.001,float(end))
        self.update()

    def set_hour(self,hour):
        self.hour = max(0.,float(hour))
        self.update()

    def paintEvent(self,event):
        super().paintEvent(event)
        if self.pixmap() is None:
            return
        # Доля оси X в Figure: [0.105,0.95] либо [0.105,0.785] для легенды сбоку.
        # Помним, имеет ли PNG боковую легенду, чтобы не проводить курсор по легенде.
        frac = min(1.,self.hour/self.end)
        left=getattr(self,'left_fraction',.105)*self.width()
        right=.785*self.width()
        x=left+(right-left)*frac
        painter=QPainter(self)
        painter.setPen(QPen(QColor(240,246,255,190),1,Qt.PenStyle.DashLine))
        painter.drawLine(round(x),round(.17*self.height()),
                         round(x),round(.80*self.height()))
        painter.end()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            left=getattr(self,'left_fraction',.105)*self.width()
            right=.785*self.width()
            v=max(0.,min(1.,(event.position().x()-left)/max(1,right-left)))
            self.panel.hour_spin.setValue(v*self.end)
        super().mousePressEvent(event)


def _show_png_set(panel,result,group,parts):
    images=result.get('_plot_images',{})
    keys=[f'{group}{i}' for i in range(parts)]
    if not all(key in images for key in keys):
        return False
    if not hasattr(panel,'_multicore_images'):
        content=QWidget(panel)
        stack=QVBoxLayout(content)
        stack.setContentsMargins(0,0,0,0)
        stack.setSpacing(4)
        slots=[]
        for _ in keys:
            image=HourPlotImage(panel,content)
            stack.addWidget(image,1)
            slots.append(image)
        panel._plot_layers.addWidget(content)
        panel._multicore_images = slots
        panel._multicore_container = content
        panel.hour_spin.valueChanged.connect(
            lambda h,p=panel:[label.set_hour(h) for label in p._multicore_images])
    # Если ранее отображался стандартный Matplotlib, скрываем только canvas.
    panel.canvas.hide()
    panel._plot_layers.setCurrentWidget(panel._multicore_container)
    if hasattr(panel,'_pending_chart_label'):
        panel._pending_chart_label.hide()
    for i,key in enumerate(keys):
        slot=panel._multicore_images[i]
        slot.legend_side=True
        slot.left_fraction=.22 if key=='history1' else .105
        slot.set_image(images[key],result['hours'])
    panel.set_time_range(result['hours'])
    for img in panel._multicore_images:
        img.set_hour(panel.hour_spin.value())
    return True


def _fallback_panel(panel,draw):
    if hasattr(panel,'_multicore_container'):
        panel._multicore_container.hide()
    panel._plot_layers.setCurrentWidget(panel.canvas)
    panel.canvas.show()
    draw()


def _status(window,result):
    bad=result.get('first_bad')
    msg=(f"Работа {result['days']} дней × {result['hours_per_day']:g} ч = "
         f"{result['hours']:g} ч наработки.\n")
    if bad:
        msg+=('Первое отклонение: '+operation_day(bad['hour'],result['hours_per_day'])+
              '; '+', '.join(bad['violations'])+'.\n')
    msg+=result['status']
    actions=result.get('actions',[]) or ([] if result.get('action') is None else [result['action']])
    if actions:
        msg+='\nПредложенный план:'
        for a in actions:
            what='догрузить' if a['direction']=='add' else 'выгрузить'
            r=a['target']
            msg+=(f"\n• {what} {a['pieces']} шт ({a['tons']:.4f} т), "
                  f"камера {r['chamber']}, {r['type']} Ø{r['diameter_mm']:g} мм, "
                  f"на часу {a['hour']:g}.")
        msg+=(f"\nВ норме после вмешательства: {actions[0]['valid_hours']:g} ч "
              '(по контрольным точкам).')
    msg+=(f"\nПроверено {result.get('evaluated',0)} сценариев; "
          f"процессов поиска: {result.get('parallel_workers',1)}, "
          f"процессов отрисовки: {result.get('plot_workers',1)}.")
    if result.get('parallel_warning') or result.get('plot_warning'):
        msg+='\nПредупреждение ускорения: '+str(result.get('parallel_warning') or result.get('plot_warning'))
    msg+='\nБлейн расчётный; Q при изменении шаров не моделируется физически. Проверить решение с технологом.'
    window.sim_status.setText(msg)
    window.sim_status.setStyleSheet('color:#ff8585' if bad and not actions else 'color:#8ddfc5')
    window.sim_apply.setText('Перенести предложенные операции в журнал')
    window.sim_apply.setEnabled(bool(actions))
    if actions:
        table=[]
        for a in actions:
            r=a['target']
            table.append({'Час':a['hour'],
                          'День / час':operation_day(a['hour'],result['hours_per_day']),
                          'Операция':'Догрузка' if a['direction']=='add' else 'Выгрузка',
                          'Камера':r['chamber'],'Фракция':f"{r['type']} Ø{r['diameter_mm']:g}",
                          'Материал':r['material'],'Количество, шт':a['pieces'],
                          'Масса, т':a['tons']})
    else:
        table=[{'Состояние':'Коррекция не требуется' if not bad
                else 'Подходящая комбинация не найдена или нарушение Q'}]
    window._populate_result(window.sim_table,table,list(table[0]))


def install(MillWindow):
    if getattr(MillWindow,'_multicore_installed',False):
        return
    MillWindow._multicore_installed=True
    # Имена SimJob/SimSignals разрешаются поздно из глобальной области workflow_ui.
    workflow_ui.SimJob=MultiJob
    workflow_ui.SimSignals=MultiSignals
    original_sim=workflow_ui._sim_plot
    original_history=timeline_ui._timeline_history_plot
    original_fraction=timeline_ui._dynamic_fraction_plot
    original_forecast=timeline_ui._dynamic_forecast_plot
    previous_build=MillWindow._build
    previous_schedule=MillWindow.schedule
    previous_draw_fractions=MillWindow._draw_fractions

    def plot_sim(window,result):
        if not _show_png_set(window.sim_plot,result,'sim',4):
            _fallback_panel(window.sim_plot,lambda:original_sim(window,result))

    def plot_history(window,result):
        if not _show_png_set(window.history_plot,result,'history',3):
            request_charts(window,result,'history',window.history_plot)

    def plot_fraction(window,result):
        choice=window.fraction_combo.currentText()
        category=('ch1' if choice=='Б1К1' else 'ch2' if choice=='Б1К2' else 'all')
        if not _show_png_set(window.fraction_plot,result,f'fraction_{category}_',3):
            request_charts(window,result,'fraction',window.fraction_plot)

    def plot_forecast(window,result):
        if not _show_png_set(window.forecast_plot,result,'forecast',2):
            request_charts(window,result,'forecast',window.forecast_plot)
        else:
            rows=result['baseline']
            if rows:
                window.forecast_summary.setText(
                    f"Изменения загрузки учтены: {rows[0]['media_mass_t']:.3f} т в начале, "
                    f"{rows[-1]['media_mass_t']:.3f} т в конце, "
                    f"истирание {rows[-1]['wear_cumulative_t']:.3f} т.")
                first=rows[0]['media_by_fraction_t']
                last=rows[-1]['media_by_fraction_t']
                table=[{'Фракция':name,'В начале, т':first.get(name,0.),
                        'В конце, т':last.get(name,0.),
                        'Изменение, т':last.get(name,0.)-first.get(name,0.)}
                       for name in sorted(set(first)|set(last))]
                if table:
                    window._populate_result(window.forecast_table,table,list(table[0]))

    def request_charts(window,result,group,panel):
        if not hasattr(window,'_chart_pool'):
            return
        if not hasattr(panel,'_pending_chart_label'):
            note=QLabel('Подготавливаются графики в фоновых процессах…',panel)
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            panel._plot_layers.addWidget(note)
            panel._pending_chart_label=note
        panel._plot_layers.setCurrentWidget(panel._pending_chart_label)
        if window._charts_loading.get(group) != window._sim_generation:
            window._charts_loading[group] = window._sim_generation
            window._chart_pool.start(DeferredChartJob(
                window._sim_generation,group,result,window._sim_signals))

    workflow_ui._sim_plot=plot_sim
    workflow_ui._render_summary=_status
    timeline_ui._timeline_sim_plot=plot_sim
    timeline_ui._timeline_history_plot=plot_history
    timeline_ui._dynamic_fraction_plot=plot_fraction
    timeline_ui._dynamic_forecast_plot=plot_forecast

    def build(window):
        previous_build(window)
        window._chart_pool=QThreadPool(window)
        window._chart_pool.setMaxThreadCount(2)
        window._charts_loading={}
        window._sim_signals.progress.connect(lambda n,stage,data: progress(window,n,stage,data))
        window._sim_signals.charts_ready.connect(
            lambda n,group,data:charts_ready(window,n,group,data))
        window._sim_signals.charts_failed.connect(
            lambda n,group,error:charts_failed(window,n,group,error))

    def progress(window,n,stage,data):
        if n != window._sim_generation:
            return
        names={'baseline':'Начальная траектория рассчитана; подбор комбинаций…',
               'singles':'Проверены одиночные операции',
               'pairs':'Проверены пары операций',
               'triples':'Проверены тройные комбинации',
               'render':'Графики строятся параллельно в фоновых процессах…'}
        message=names.get(stage,stage)
        if isinstance(data,dict) and 'evaluated' in data:
            message+=f" — {data['evaluated']} проверено, {data.get('workers',1)} процессов"
        window.sim_status.setText(message)

    def charts_ready(window,n,group,data):
        if n!=window._sim_generation:
            return
        images,workers,warning=data
        window._charts_loading.pop(group,None)
        result=getattr(window,'_timeline_outcome',None)
        if result is None:
            return
        result.setdefault('_plot_images',{}).update(images)
        window._sim_result=result
        index=window.right.tabs.currentIndex()
        if group=='history' and index==window.history_index:
            plot_history(window,result)
        elif group=='fraction' and index==2:
            plot_fraction(window,result)
        elif group=='forecast' and index==6:
            plot_forecast(window,result)
        if warning:
            window.statusBar().showMessage('Некоторые графики подготовлены последовательно: '+str(warning),15000)

    def charts_failed(window,n,group,error):
        if n!=window._sim_generation:
            return
        window._charts_loading.pop(group,None)
        window.statusBar().showMessage('Ошибка фонового рендеринга: '+error,15000)
        result=getattr(window,'_timeline_outcome',None)
        if result is None:
            return
        if group=='history':_fallback_panel(window.history_plot,lambda:original_history(window,result))
        if group=='fraction':_fallback_panel(window.fraction_plot,lambda:original_fraction(window,result))
        if group=='forecast':_fallback_panel(window.forecast_plot,lambda:original_forecast(window,result))

    def apply_plan(window):
        result=getattr(window,'_sim_result',None)
        if not result:return
        actions=result.get('actions') or ([] if result.get('action') is None else [result['action']])
        if not actions:return
        yes=QMessageBox.question(window,'Добавить операции в журнал?',
                                 f'Добавить {len(actions)} операций в план на часе '
                                 f'{actions[0]["hour"]:g}? Это только сценарий, не команда оборудованию.')
        if yes!=QMessageBox.StandardButton.Yes:
            return
        for action in actions:
            window._media_events.append({
                'hour':float(action['hour']), 'direction':action['direction'],
                'pieces':int(action['pieces']), 'tons':float(action['tons']),
                'target':deepcopy(action['target'])})
        window._refresh_timeline()
        window.schedule()

    def update_fractions(window,*args):
        result=getattr(window,'_timeline_outcome',None)
        if result and not getattr(window,'_sim_dirty',False):
            plot_fraction(window,result)
        else:
            previous_draw_fractions(window,*args)

    def schedule(window,*args):
        # Не строим старые графики из очереди после изменения параметров.
        if hasattr(window,'_chart_pool'):
            window._chart_pool.clear()
        return previous_schedule(window,*args)

    MillWindow._build=build
    MillWindow.schedule=schedule
    MillWindow._apply_shift_action=apply_plan
    MillWindow._draw_fractions=update_fractions
