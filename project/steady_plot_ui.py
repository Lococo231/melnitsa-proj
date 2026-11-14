"""A fixed plot viewport for QtAgg and offscreen PNG layers.

The figure, waiting view and PNG images share one QWidget slot. Its size hint
never depends on the PNG resolution, so changing an image cannot resize the
window or reflow the surrounding QSplitter/QScrollArea.

Install *after* all older MillWindow plug-ins, but before constructing a window.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout,
)


class StablePlotStack(QStackedWidget):
    """Independent of the active image's original pixel dimensions."""

    def sizeHint(self):
        return QSize(420, 270)

    def minimumSizeHint(self):
        return QSize(160, 115)


def install(MillWindow, PlotPanel):
    """Reserve the plot area before any images arrive or tabs become visible."""
    if getattr(PlotPanel, '_stable_plot_stack_installed', False):
        return
    PlotPanel._stable_plot_stack_installed = True
    old_init = PlotPanel.__init__

    def init(self, *args, **kwargs):
        old_init(self, *args, **kwargs)
        layout = self.layout()
        original_pos = layout.indexOf(self.canvas)
        if original_pos < 0:
            raise RuntimeError('Matplotlib canvas missing from PlotPanel layout')
        layout.removeWidget(self.canvas)
        stack = StablePlotStack(self)
        stack.setObjectName('stable-plot-viewport')
        stack.setSizePolicy(QSizePolicy.Policy.Ignored,
                            QSizePolicy.Policy.Expanding)
        stack.setMinimumWidth(0)
        stack.setFrameShape(QFrame.Shape.NoFrame)
        layout.insertWidget(original_pos, stack, 1)
        stack.addWidget(self.canvas)

        waiting = QLabel('Ожидание данных графика…', stack)
        waiting.setObjectName('plot-waiting-layer')
        waiting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        waiting.setWordWrap(True)
        waiting.setSizePolicy(QSizePolicy.Policy.Ignored,
                              QSizePolicy.Policy.Expanding)
        waiting.setStyleSheet('background:#162a3d; color:#a9c3d2;')
        stack.addWidget(waiting)
        stack.setCurrentWidget(self.canvas)
        self._plot_layers = stack
        self._plot_placeholder = waiting

    PlotPanel.__init__ = init

    # The controls below temporal plots were initially hidden. Calling show()
    # twice on the first result used to change the plot viewport twice. Reserve
    # their final geometry before the top-level window is ever displayed.
    previous_build = MillWindow._build

    def build(window):
        previous_build(window)
        for name in ('overview_plot', 'fraction_plot', 'history_plot',
                     'sim_plot', 'forecast_plot'):
            panel = getattr(window, name, None)
            if panel is None:
                continue
            controls = (panel.time_controls, panel.hour_readout)
            for control, height in zip(controls, (35, 32)):
                policy = control.sizePolicy()
                policy.setRetainSizeWhenHidden(True)
                control.setSizePolicy(policy)
                control.setFixedHeight(height)

    MillWindow._build = build
