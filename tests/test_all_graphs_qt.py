"""Manual headless Qt smoke tests; no automatic GitHub workflow."""
from __future__ import annotations

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')

from PySide6.QtWidgets import QApplication
from qt_app import MillWindow
from multicore_ui import HourPlotImage
from adaptive_graphs_ui import changed_size, display_size


def test_all_visible_graphs_and_forms_resize_without_fixed_widths():
    app = QApplication.instance() or QApplication([])
    window = MillWindow()
    try:
        assert window._all_graphs_responsive_installed
        assert window._adaptive_responsive_installed
        assert window._staged_results_installed
        assert window.left.minimumWidth() == 0
        window.resize(1440, 900)
        window.show()
        app.processEvents()
        window._master_splitter.setSizes([270, 1150])
        app.processEvents()
        narrow = window.left.width()
        window._master_splitter.setSizes([620, 800])
        app.processEvents()
        assert window.left.width() > narrow + 100
        assert window.overview_plot.canvas.sizePolicy().hasHeightForWidth() is False
        for panel in (window.sim_plot, window.history_plot, window.fraction_plot):
            w, h = display_size(panel)
            assert w > 0 and h > 0
            image = HourPlotImage(panel, panel)
            assert not image.hasScaledContents()
            image.deleteLater()
        assert changed_size((500, 300), (750, 300))
        assert not changed_size((500, 300), (508, 304))
    finally:
        window._timer.stop()
        window._sim_timer.stop()
        window._all_graphs_resize_timer.stop()
        window._native_graphs_resize_timer.stop()
        window.close()
        app.processEvents()
