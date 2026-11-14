"""Resize-aware, high-DPI, lazy rendering for *all* mill plot types.

Install after responsive_ui. All Matplotlib Agg rendering happens in QRunnable
workers using spawn child processes; Qt widgets are touched only in GUI thread.
Native QtAgg figures resize on their FigureCanvas; a debounced draw_idle
refreshes tick labels and legends. Existing model data is never recomputed
merely because the window is resized.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRunnable, QTimer

import multicore_ui
import workspace_ui
import workflow_ui
import timeline_ui
from multicore_render import render_timeline_images

# Meaningful change threshold, so resizing a splitter does not start dozens
# of parallel Python processes and send obsolete PNG images back to the GUI.
MIN_CHANGE_PX = 44
MIN_CHANGE_RATIO = 0.09
RESIZE_DELAY_MS = 360


def display_size(panel, images: int = 1) -> tuple[int, int]:
    """Return logical viewport size of one plot, excluding hours toolbar."""
    controls = panel.time_controls.height() if panel.time_controls.isVisible() else 38
    readout = panel.hour_readout.height() if panel.hour_readout.isVisible() else 0
    content = panel.contentsRect()
    width = max(290, content.width() - 14)
    height = max(155, (content.height() - controls - readout - 12) // max(1, images))
    # Renderer creates 2 pixels per logical pixel for crisp HiDPI display.
    return width, height


def changed_size(previous, wanted):
    if previous is None:
        return True
    return any(abs(old - new) >= max(MIN_CHANGE_PX, old * MIN_CHANGE_RATIO)
               for old, new in zip(previous, wanted))


class RenderJob(QRunnable):
    """Compute bytes outside Qt; emit tagged result using existing signals."""
    def __init__(self, generation, tag, group, result, size, signals):
        super().__init__()
        self.generation = generation
        self.tag = tag
        self.group = group
        # Drop already-rendered PNGs before pickling a possibly large result.
        self.result = {k: v for k, v in result.items() if k != '_plot_images'}
        self.size = size
        self.signals = signals

    def run(self):
        try:
            images, workers, warning = render_timeline_images(
                self.result, groups=(self.group,), target_size=self.size)
            self.signals.charts_ready.emit(
                self.generation, self.tag, (images, workers, warning))
        except Exception as exc:
            self.signals.charts_failed.emit(
                self.generation, self.tag, str(exc))


class ResizeObserver(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window

    def eventFilter(self, widget, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            owner = self.owner
            if getattr(owner, '_all_graphs_ready', False):
                # Keep one debounced layout observation; QtAgg already
                # handles its own canvas resizeEvent in the GUI thread.
                owner._all_graphs_resize_timer.start()
        return False


def _result(window):
    result = getattr(window, '_timeline_outcome', None)
    if (result is None or getattr(window, '_sim_dirty', True)
            or not getattr(window, '_workspace_ui_built', False)):
        return None
    return result


def install(MillWindow):
    if getattr(MillWindow, '_all_graphs_responsive_installed', False):
        return
    MillWindow._all_graphs_responsive_installed = True
    previous_build = MillWindow._build
    previous_schedule = MillWindow.schedule
    previous_png_set = multicore_ui._show_png_set
    previous_sim = workspace_ui._one_sim_chart

    def request(window, group: str, panel, count: int, result):
        """Render one visible group only, at the current display dimensions."""
        if not getattr(window, '_all_graphs_ready', False) or not panel.isVisible():
            return
        size = display_size(panel, count)
        token = 'adaptive:' + group
        generation = window._sim_generation
        if window._all_graphs_cache_generation != generation:
            # A new explicit simulation run can start without schedule().
            # Never reuse PNG-size metadata from the previous result.
            window._all_graphs_sizes.clear()
            window._all_graphs_pending.clear()
            window._all_graphs_cache_generation = generation
        request_key = (generation, size)
        pending = window._all_graphs_pending.get(group)
        if pending is not None:
            # A newer size will be dispatched when the existing job completes.
            return
        if not changed_size(window._all_graphs_sizes.get(group), size):
            return
        window._all_graphs_pending[group] = request_key
        window._chart_pool.start(RenderJob(
            generation, token, group, result, size, window._sim_signals))

    def sim_chart(window, result):
        previous_sim(window, result)
        if getattr(window, '_all_graphs_ready', False):
            key = window._workspace_chart_picker.currentData()
            if key:
                request(window, str(key), window.sim_plot, 1, result)

    def show_png(panel, result, group, parts):
        shown = previous_png_set(panel, result, group, parts)
        if shown and group in ('history', 'forecast'):
            owner = panel.window()
            if getattr(owner, '_all_graphs_ready', False):
                request(owner, group, panel, parts, result)
        return shown

    # The workspace module dynamically references _one_sim_chart on initial
    # completion and selection changes. This updates every call site, while
    # preserving old plot behavior when a worker has not finished.
    workspace_ui._one_sim_chart = sim_chart
    workflow_ui._sim_plot = sim_chart
    timeline_ui._timeline_sim_plot = sim_chart
    multicore_ui._show_png_set = show_png

    def resized(window):
        result = _result(window)
        if result is None:
            return
        outer = window.right.tabs.currentIndex()
        if outer == window.sim_tab_index and window.sim_plot.isVisible():
            sim_chart(window, result)
        elif outer == window.history_index and window.history_plot.isVisible():
            show_png(window.history_plot, result, 'history', 3)
        elif outer == 2 and window.fraction_plot.isVisible():
            stages = getattr(window, '_media_stages', None)
            if stages is None or stages.currentIndex() == 1:
                # The preceding responsive_ui extension already renders one
                # chosen fraction metric at the current real panel dimensions.
                window._draw_fractions()
        elif outer == 6 and window.forecast_plot.isVisible():
            show_png(window.forecast_plot, result, 'forecast', 2)

    def native_draw(window):
        """QtAgg already scales by devicePixelRatioF; refresh the vector canvas."""
        panels = (window.overview_plot, window.quality_plot,
                  window.start_plot, window.fraction_plot,
                  window.history_plot, window.sim_plot)
        for panel in panels:
            canvas = panel.canvas
            if canvas.isVisible() and canvas.width() > 10 and canvas.height() > 10:
                canvas.draw_idle()

    def on_ready(window, generation, tag, data):
        if not tag.startswith('adaptive:'):
            return
        group = tag[len('adaptive:'):]
        queued = window._all_graphs_pending.pop(group, None)
        if queued is None or generation != window._sim_generation:
            return
        images, _workers, warning = data
        result = _result(window)
        if result is None:
            return
        if not images:
            return
        # multicore_ui handler already merged the PNGs into the result.
        # Keep the tag's requested size so the next draw will not loop.
        window._all_graphs_sizes[group] = queued[1]
        if warning:
            window.statusBar().showMessage(
                'Графики подготовлены последовательно: ' + str(warning), 10000)
        # Existing result cache is already updated by multicore_ui.
        # Show it once, without another full-window resize cycle.
        def show_ready():
            if generation != window._sim_generation:
                return
            if group.startswith('sim'):
                if (window.right.tabs.currentIndex() == window.sim_tab_index and
                        window._workspace_chart_picker.currentData() == group):
                    window._render_active()
            elif group == 'history' and window.right.tabs.currentIndex() == window.history_index:
                window._render_active()
            elif group == 'forecast' and window.right.tabs.currentIndex() == 6:
                window._render_active()
            # If the latest panel dimensions changed while the background task
            # ran, schedule only one follow-up render after layout settles.
            panel = (window.sim_plot if group.startswith('sim') else
                     window.history_plot if group == 'history' else
                     window.forecast_plot if group == 'forecast' else None)
            if panel is not None and panel.isVisible() and changed_size(
                    queued[1], display_size(panel, 3 if group == 'history' else
                                              2 if group == 'forecast' else 1)):
                window._all_graphs_resize_timer.start()
        QTimer.singleShot(0, show_ready)

    def on_failed(window, generation, tag, error):
        if not tag.startswith('adaptive:'):
            return
        group = tag[len('adaptive:'):]
        window._all_graphs_pending.pop(group, None)
        if generation == window._sim_generation:
            window.statusBar().showMessage(
                'Невозможно обновить разрешение графика: ' + error, 12000)

    def build(window):
        window._all_graphs_ready = False
        previous_build(window)
        window._all_graphs_pending = {}
        window._all_graphs_sizes = {}
        window._all_graphs_cache_generation = -1
        window._all_graphs_resize_timer = QTimer(window)
        window._all_graphs_resize_timer.setSingleShot(True)
        window._all_graphs_resize_timer.setInterval(RESIZE_DELAY_MS)
        window._all_graphs_resize_timer.timeout.connect(lambda: resized(window))
        window._native_graphs_resize_timer = QTimer(window)
        window._native_graphs_resize_timer.setSingleShot(True)
        window._native_graphs_resize_timer.setInterval(100)
        window._native_graphs_resize_timer.timeout.connect(lambda: native_draw(window))
        window._all_graphs_observer = ResizeObserver(window)
        panels = (window.sim_plot, window.overview_plot, window.quality_plot,
                  window.start_plot, window.fraction_plot, window.history_plot,
                  window._master_splitter, window.left, window.right)
        for panel in panels:
            panel.installEventFilter(window._all_graphs_observer)
        window._sim_signals.charts_ready.connect(
            lambda n, group, data: on_ready(window, n, group, data))
        window._sim_signals.charts_failed.connect(
            lambda n, group, error: on_failed(window, n, group, error))
        window._all_graphs_ready = True
        window._native_graphs_resize_timer.start()
        window._all_graphs_resize_timer.start()

    def schedule(window, *args):
        if getattr(window, '_all_graphs_ready', False):
            window._all_graphs_sizes.clear()
            window._all_graphs_pending.clear()
            window._all_graphs_cache_generation = -1
        return previous_schedule(window, *args)

    MillWindow._build = build
    MillWindow.schedule = schedule
    MillWindow._all_graphs_request = request
