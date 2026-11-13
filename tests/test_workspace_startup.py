"""Local GUI regression. Does not enable GitHub Actions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QScrollArea
from qt_app import MillWindow


def test_workspace_build_does_not_use_uninitialized_tabs_or_scroll_area_layout():
    app = QApplication.instance() or QApplication([])
    win = MillWindow()
    try:
        assert win._workspace_ui_built is True
        assert hasattr(win, 'timeline_editor_index')
        assert hasattr(win, '_workspace_chart_picker')
        sim_page = win.right.tabs.widget(win.sim_tab_index)
        contents = sim_page.widget() if isinstance(sim_page, QScrollArea) else sim_page
        assert contents is not None
        assert contents.layout() is not None
        assert contents.layout().indexOf(win.sim_plot) >= 0
        for index in (0, win.sim_tab_index, win.timeline_editor_index):
            win.right.tabs.setCurrentIndex(index)
            win._render_active()  # no missing attribute on normal navigation
    finally:
        win._sim_timer.stop()
        win._timer.stop()
        win.close()
        app.processEvents()
