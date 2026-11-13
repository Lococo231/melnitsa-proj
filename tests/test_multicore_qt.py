"""Qt проверяется только вручную в окружении с установленным PySide6."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from qt_app import MillWindow


def test_multicore_signals_and_journal_are_available():
    app=QApplication.instance() or QApplication([])
    window=MillWindow()
    try:
        assert window._multicore_installed
        assert hasattr(window._sim_signals,'progress')
        assert hasattr(window._sim_signals,'charts_ready')
        assert hasattr(window,'_chart_pool')
        assert hasattr(window,'_media_events')
        assert window.right.tabs.tabText(window.sim_tab_index)=='Симуляция работы'
    finally:
        window.close()
        app.processEvents()
