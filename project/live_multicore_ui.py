"""Responsive live recalculation across several CPU cores.

Heavy wear/fineness/reload computations run in persistent spawn processes,
coalesced by a Qt debounce. Only visible QtAgg widgets are painted by the
main GUI thread. Simulation opt-in stays explicit: moving a slider must not
trigger an expensive optimization of 1–3 body-reload combinations.
"""
from __future__ import annotations

from copy import deepcopy
import math
import threading
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


class _SignalGate:
    """Mute worker emissions before QApplication can destroy Qt signal owners."""
    def __init__(self, signal, closed):
        self.signal = signal
        self.closed = closed

    def connect(self, *args, **kwargs):
        return self.signal.connect(*args, **kwargs)

    def emit(self, *args):
        if self.closed.is_set():
            return
        try:
            self.signal.emit(*args)
        except RuntimeError:
            # aboutToQuit may race a worker which passed the first check.
            if not self.closed.is_set():
                raise


class _WorkerSignals:
    def __init__(self, source, names):
        self.source = source
        self.closed = threading.Event()
        for name in names:
            setattr(self, name, _SignalGate(getattr(source, name), self.closed))

    def close(self):
        self.closed.set()


class _Task(QRunnable):
    def __init__(self,signals,version,kind,cfg,hours=0.):
        super().__init__()
        self.signals=signals
        self.version=version
        self.kind=kind
        self.cfg=cfg
        self.hours=hours

    def run(self):
        if self.signals.closed.is_set():
            return
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
        self.signal=_WorkerSignals(_Signals(self), ('ready', 'failed'))
        self.closed=False
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
        if self.closed:
            return
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
        if self.closed or w._loading:
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
        if self.closed:
            return
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
        if self.closed:
            return
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
        if self.closed:
            return
        self.running[kind]=False
        if version==self.version:
            self.window.statusBar().showMessage(
                f'Ошибка пересчёта {kind}: {error}',12000)
        if self.latest[kind] is not None:
            self._dispatch(kind)


    def shutdown(self):
        self.closed=True
        self.timer.stop()
        self.overview_timer.stop()
        self.latest={'preview':None,'overview':None}
        self.signal.close()
        self.pool.clear()


class _ShutdownController(QObject):
    """Drain active workers asynchronously while their window/signal owners live.

    Running model/optimizer calls have no force-cancellation contract. Closing
    therefore waits for those calls without blocking Qt's event loop.
    """
    def __init__(self, window):
        super().__init__(window)
        self.window=window
        self.started=False
        self.drained=False
        self.timer=QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._about_to_quit)

    def _begin(self):
        if self.started:
            return
        self.started=True
        w=self.window
        w._shutting_down=True
        w._sim_generation+=1  # Ignore already-queued results from this session.
        for timer in w.findChildren(QTimer):
            timer.stop()
        w._live_controller.shutdown()
        w._sim_signals.close()
        for pool in self._pools():
            pool.clear()
        for animation in w.findChildren(mill_visual_ui.MillCutWidget):
            animation.shutdown()
        if w.centralWidget() is not None:
            w.centralWidget().setEnabled(False)
        w.menuBar().setEnabled(False)
        w.statusBar().showMessage('Завершение фоновых задач перед закрытием…')

    def _pools(self):
        w=self.window
        return [pool for pool in (w._live_controller.pool,
                getattr(w,'_sim_pool',None), getattr(w,'_chart_pool',None))
                if pool is not None]

    def _idle(self):
        return (all(pool.activeThreadCount()==0 for pool in self._pools()) and
                all(not widget._worker.is_alive() for widget in
                    self.window.findChildren(mill_visual_ui.MillCutWidget)))

    def request_close(self):
        if self.drained:
            return True
        self._begin()
        if self._idle():
            self._finish()
            return True
        self.timer.start()
        return False

    def _finish(self):
        self.drained=True
        self.timer.stop()
        # No live preview task can submit to the shared process pool now.
        live_preview_core.shutdown()

    def _poll(self):
        if self._idle():
            self._finish()
            self.window.close()

    def _about_to_quit(self):
        # Direct QApplication.quit() bypasses QWidget.closeEvent. Muting all
        # worker signal gates also makes that teardown path safe.
        self._begin()
        self.timer.stop()
        live_preview_core.shutdown()


def install(MillWindow):
    if getattr(MillWindow,'_live_multicore_installed',False):
        return
    MillWindow._live_multicore_installed=True
    original_build=MillWindow._build
    original_schedule=MillWindow.schedule
    previous_calculate=MillWindow.calculate
    previous_close=MillWindow.closeEvent
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
        window._sim_signals=_WorkerSignals(window._sim_signals,
            ('completed','failed','progress','charts_ready','charts_failed'))
        window._shutting_down=False
        window._shutdown_controller=_ShutdownController(window)
        window.overview_hours.valueChanged.connect(
            lambda *_:window._live_controller.overview_timer.start())
        # Old auto timer may have been set to 130ms. New calculate()
        # uses background processes, and the debounce prevents flooding.
        window._timer.setInterval(340)
        if hasattr(window,'_sim_timer'):
            window._sim_timer.stop()
        window._live_controller.mark()

    def schedule(window,*args):
        if getattr(window,'_shutting_down',False):
            return
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
            window._sim_running=False
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
        workspace_ui.invalidate_recommendations(window)
        window._live_controller.mark()
        window.statusBar().showMessage(
            'Изменены параметры — рассчитываю графики по нескольким ядрам…')

    def calculate(window,quiet=False):
        if getattr(window,'_shutting_down',False):
            return
        if not getattr(window,'_live_controller',None):
            return previous_calculate(window,quiet)
        if window._loading:
            return
        window._timer.stop()
        window._live_controller.timer.stop()
        window._live_controller.submit('preview')
        window._live_controller.overview_timer.start()

    def close(window,event):
        controller=getattr(window,'_shutdown_controller',None)
        if controller is not None and not controller.request_close():
            event.ignore()
            return
        previous_close(window,event)

    MillWindow._build=build
    MillWindow.schedule=schedule
    MillWindow.calculate=calculate
    MillWindow.closeEvent=close
