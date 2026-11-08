"""Опциональный локальный smoke-тест PySide6 в режиме offscreen."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PySide6.QtWidgets import QApplication
from qt_app import MillWindow


def test_timeline_layout_and_sidebar_toggle():
    app=QApplication.instance() or QApplication([])
    window=MillWindow()
    window.show()
    app.processEvents()
    try:
        assert all(window.left.tabs.tabText(i)!='Прогноз износа'
                   for i in range(window.left.tabs.count()))
        assert any(window.right.tabs.tabText(i)=='Прогноз износа'
                   for i in range(window.right.tabs.count()))
        assert window.right.tabs.tabText(window.sim_tab_index)=='Симуляция работы'
        window._toggle_side('left')
        assert window.left.isHidden()
        assert not window.right.isHidden()
        window._toggle_side('left')
        assert not window.left.isHidden()
        window._toggle_side('right')
        assert window.right.isHidden()
        window._toggle_side('right')
        assert not window.right.isHidden()
    finally:
        window.close()
        app.processEvents()