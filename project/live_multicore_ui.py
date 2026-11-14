"""Responsive live recalculation across several CPU cores.

Heavy wear/fineness/reload computations run in persistent spawn processes,
coalesced by a Qt debounce. Only visible QtAgg widgets are painted by the
main GUI thread. Simulation opt-in stays explicit: moving a slider must not
trigger an expensive optimization of 1–3 body-reload combinations.
"""
from __future__ import annotations

from copy import deepcopy
import math
from PySide6.QtCore import (QObject, QEvent, QTimer, QThreadPool, QRunnable,
                            Signal, Slot, Qt, QSignalBlocker)
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QLabel, QAbstractScrollArea,
                               QSizePolicy)

import live_preview_core
import mill_visual_ui
import operator_workflow_ui
import workspace_ui


class _Signals(QObject):
    ready=Signal(int,str,object)
    failed=Signal(int,str,str)


class _Task(QRunnable):
    def __init__(self,signals,version,kind,cfg,hours=0.):
        super().__init__()
        self.signals=signals
        self.version=version
        self.kind=kind
        self.cfg=cfg
        self.hours=hours

    def run(self):
        try:
            if self.kind=='overview':
                value=live_preview_core.calculate_overview(
                    self.cfg,self.hours,parallel=True)
            else:
                value=live_preview_core.calculate_preview(self.cfg,parallel=True)
            self.signals.ready.emit(self.version,self.kind,value)
        except Exception as exc:
            self.signals.failed.emit(self.version,self.kind,str(exc))


class WheelGuard(QObject):
    """Wheel scrolls the page, never changes collapsed graph selections."""
    def eventFilter(self,obj,event):
        if not isinstance(obj,QComboBox) or event.type()!=QEvent.Type.Wheel:
            return False
        # Mouse wheel can still be used to scroll an explicitly opened popup.
        if obj.view().isVisible():
            return False
        parent=obj.parentWidget()
        while parent is not None:
            if isinstance(parent,QAbstractScrollArea):
                bar=parent.verticalScrollBar()
                if bar.maximum()>0:
                    bar.setValue(bar.value()-int(event.angleDelta().y()*0.7))
                    break
            parent=parent.parentWidget()
        event.accept()
        return True


class PreviewController(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window
        self.signal=_Signals()
        self.signal.ready.connect(self._ready,Qt.ConnectionType.QueuedConnection)
        self.signal.failed.connect(self._failed,Qt.ConnectionType.QueuedConnection)
        self.pool=QThreadPool(window)
        self.pool.setMaxThreadCount(2)
        self.version=0
        self.running={'preview':False,'overview':False}
        self.latest={'preview':None,'overview':None}
        self.timer=QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(340)
        self.timer.timeout.connect(lambda:self.submit('preview'))
        self.overview_timer=QTimer(self)
        self.overview_timer.setSingleShot(True)
        self.overview_timer.setInterval(420)
        self.overview_timer.timeout.connect(lambda:self.submit('overview'))
        self.last_cfg=None

    def mark(self):
        self.version+=1
        self.window._overview_cached=None
        self.window._overview_cached_version=-1
        # Throttle at most one request per interval while dragging; unlike a
        # trailing-edge debounce, a continuous drag still gets live previews.
        if not self.timer.isActive():
            self.timer.start()
        if not self.overview_timer.isActive():
            self.overview_timer.start()

    def submit(self,kind):
        w=self.window
        if w._loading:
            return
        try:
            cfg=deepcopy(w.collect_config())
        except Exception as e:
            w.statusBar().showMessage('Проверьте ввод: '+str(e))
            return
        hrs=(w.overview_hours.value() if kind=='overview'
             else 0.)
        self.latest[kind]=(self.version,cfg,hrs)
        if self.running[kind]:
            return  # newest configuration is dispatched after active job
        self._dispatch(kind)

    def _dispatch(self,kind):
        item=self.latest[kind]
        if item is None:
            return
        self.latest[kind]=None
        self.running[kind]=True
        version,cfg,hrs=item
        if kind=='overview':
            self.window.overview_hours_note.setText(
                f'Рассчитываю обзор за {hrs:g} ч на нескольких ядрах…')
        self.pool.start(_Task(self.signal,version,kind,cfg,hrs))

    @Slot(int,str,object)
    def _ready(self,version,kind,value):
        self.running[kind]=False
        w=self.window
        if version==self.version and not (kind=='overview' and
                abs(float(value.get('hours',-1)) - self.window.overview_hours.value())>.01):
            if kind=='overview':
                w._overview_cached=value
                w._overview_cached_version=version
                w.overview_hours_note.setText(
                    f'Обзор: {w.overview_hours.value():g} ч, '
                    f'{len(value.get("baseline",[]))} точек. '
                    'Ползунок под графиком выбирает час просмотра.')
                if w.right.tabs.currentIndex()==0:
                    workspace_ui._overview_plot(w,value)
            else:
                cfg,run,quality,reco=(value[k] for k in ('cfg','run','quality','reco'))
                w.config_data=deepcopy(cfg)
                w.run_data=run
                w.quality_data=quality
                w._set_lab(cfg)
                w._draw_results(cfg,run,quality,reco)
                if w.right.tabs.currentIndex()==0 and w._overview_cached is not None:
                    workspace_ui._overview_plot(w,w._overview_cached)
                extra=(' (один процесс)' if not value['parallel'] else
                       f' ({value["workers"]} вычислительных ядра)')
                w.statusBar().showMessage(
                    f'Графики обновлены: {len(run["rows"])} точек'+extra)
        if self.latest[kind] is not None:
            self._dispatch(kind)

    @Slot(int,str,str)
    def _failed(self,version,kind,error):
        self.running[kind]=False
        if version==self.version:
            self.window.statusBar().showMessage(
                f'Ошибка пересчёта {kind}: {error}',12000)
        if self.latest[kind] is not None:
            self._dispatch(kind)


def install(MillWindow):
    if getattr(MillWindow,'_live_multicore_installed',False):
        return
    MillWindow._live_multicore_installed=True
    original_build=MillWindow._build
    original_schedule=MillWindow.schedule
    previous_calculate=MillWindow.calculate
    previous_plot=workspace_ui._overview_plot

    def plot_overview(window,result):
        cached=getattr(window,'_overview_cached',None)
        if cached is not None and getattr(window,'_overview_cached_version',None)==window._live_controller.version:
            result=cached
        return previous_plot(window,result)

    # Avoid restoring the simulation horizon from the Overview cursor.
    workspace_ui._overview_plot=plot_overview
    operator_workflow_ui.HelpAnimationWidget=mill_visual_ui.HelpAnimationWidget
    operator_workflow_ui.HTML_HELP += '''<h3>Движение загрузки по данным веб-прототипа</h3>
    <p>Первая камера работает преимущественно за счёт ударного дробления падающими шарами
    (катарктирование), вторая — за счёт каскадного перекатывания и истирания.
    Межкамерная перегородка удерживает мелющие тела, но пропускает материал;
    на выходе находится более тонкая фракция. Визуализация контактов 2D не заменяет
    инженерную калибровку кинетики помола и промышленный расчёт DEM.</p>'''

    def build(window):
        original_build(window)
        window._overview_cached=None
        window._overview_cached_version=-1
        mill_visual_ui.set_source(window)
        # Blank planned-unloading sidebar duplicates the actual journal.
        remove=getattr(window,'_workspace_removal_table',None)
        if remove is not None:
            remove.hide()
            parent=remove.parentWidget()
            if parent is not None:
                for label in parent.findChildren(QLabel):
                    if 'Плановые выгрузки (из симуляции)' in label.text():
                        label.hide()
        # Overview controls its OWN calculation horizon, independent from
        # Simulation days*hours and the plot's selected-hour cursor.
        top=window.right.tabs.widget(0)
        options=QGroupBox('Период расчёта обзора')
        form=QFormLayout(options)
        window.overview_hours=QDoubleSpinBox()
        window.overview_hours.setRange(.5,10000.)
        window.overview_hours.setSingleStep(1.)
        window.overview_hours.setDecimals(1)
        window.overview_hours.setValue(40.)
        window.overview_hours.setSuffix(' ч')
        window.overview_hours.setSizePolicy(QSizePolicy.Policy.Expanding,
                                             QSizePolicy.Policy.Fixed)
        form.addRow('Наработка для графиков:',window.overview_hours)
        window.overview_hours_note=QLabel(
            'Часы здесь задают период расчёта. Ползунок под графиком — только час просмотра.')
        window.overview_hours_note.setWordWrap(True)
        form.addRow(window.overview_hours_note)
        layout=top.layout()
        plot_index=layout.indexOf(window.overview_plot)
        layout.insertWidget(plot_index+1 if plot_index>=0 else layout.count(), options)
        window._wheel_guard=WheelGuard(window)
        window.installEventFilter(window._wheel_guard)
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance()
        if app:
            app.installEventFilter(window._wheel_guard)
        window._live_controller=PreviewController(window)
        window.overview_hours.valueChanged.connect(
            lambda *_:window._live_controller.overview_timer.start())
        # Old auto timer may have been set to 130ms. New calculate()
        # uses background processes, and the debounce prevents flooding.
        window._timer.setInterval(340)
        if hasattr(window,'_sim_timer'):
            window._sim_timer.stop()
        window._live_controller.mark()

    def schedule(window,*args):
        if not getattr(window,'_live_controller',None):
            return original_schedule(window,*args)
        if getattr(window,'_loading',False):
            return
        # We intentionally do NOT call original_schedule: it queues an
        # expensive full correction search for every slider tick.
        if hasattr(window,'_sim_timer'):
            window._sim_timer.stop()
        if hasattr(window,'_chart_pool'):
            window._chart_pool.clear()
        if hasattr(window,'_sim_generation'):
            window._sim_generation+=1
            window._sim_dirty=True
            if hasattr(window,'sim_apply'):
                window.sim_apply.setEnabled(False)
        if hasattr(window,'_workspace_ready'):
            window._workspace_ready=False
        if hasattr(window,'_all_graphs_sizes'):
            window._all_graphs_sizes.clear()
        if hasattr(window,'_all_graphs_pending'):
            window._all_graphs_pending.clear()
        if hasattr(window,'_workspace_recommendation_apply'):
            window._workspace_recommendation_apply.setEnabled(False)
        window._live_controller.mark()
        window.statusBar().showMessage(
            'Изменены параметры — рассчитываю графики по нескольким ядрам…')

    def calculate(window,quiet=False):
        if not getattr(window,'_live_controller',None):
            return previous_calculate(window,quiet)
        if window._loading:
            return
        window._timer.stop()
        window._live_controller.timer.stop()
        window._live_controller.submit('preview')
        window._live_controller.overview_timer.start()

    MillWindow._build=build
    MillWindow.schedule=schedule
    MillWindow.calculate=calculate
