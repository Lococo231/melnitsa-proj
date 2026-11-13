"""Local smoke checks, run with QT_QPA_PLATFORM=offscreen and PySide6 installed."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from qt_app import MillWindow


def test_workspace_navigation_and_readonly_log():
    app=QApplication.instance() or QApplication([])
    w=MillWindow()
    try:
        assert getattr(w,'_workspace_installed',False)
        assert w.left.tabs.tabText(0)=='Исходные данные'
        assert w.right.tabs.tabText(w.timeline_editor_index)=='Журнал и история'
        assert w.right.tabs.tabText(w.sim_tab_index)=='Симуляция работы'
        assert len(w._workspace_log_tables)==3
        assert w._workspace_chart_picker.count()==6
        assert not w.right.tabs.isTabVisible(5)  # Заводская история
        assert not w.right.tabs.isTabVisible(6)  # Прогноз перенесён
        assert not w.right.tabs.isTabVisible(w.timeline_editor_index+1)
        assert all(w._workspace_log_tables[k].editTriggers().value==0
                   for k in ('cement','media','parameter'))
    finally:
        w._sim_timer.stop()
        w._timer.stop()
        w.close()
        app.processEvents()
