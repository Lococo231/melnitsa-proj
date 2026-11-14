"""Run only on a machine with PySide6 and the actual repository."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication,QComboBox
from PySide6.QtCore import QEvent
from qt_app import MillWindow
from mill_visual_ui import HelpAnimationWidget


def test_live_controller_and_overview_field():
    app=QApplication.instance() or QApplication([])
    w=MillWindow()
    try:
        assert hasattr(w,'_live_controller')
        assert w.overview_hours.value()==40.
        assert hasattr(w,'_wheel_guard')
        assert hasattr(w,'_workspace_removal_table')
        assert w._workspace_removal_table.isHidden()
        w.overview_hours.setValue(120.)
        assert w.sim_days.value()==5
    finally:
        w._sim_timer.stop()
        w._timer.stop()
        w._live_controller.timer.stop()
        w._live_controller.overview_timer.stop()
        w.close()
        app.processEvents()


def test_animation_both_modes_draw():
    app=QApplication.instance() or QApplication([])
    for mode in ('cross','length'):
        w=HelpAnimationWidget(mode)
        try:
            w.view.drum.step(.033)
            w.view.axial.step(.033)
            w.resize(830,450)
            w.show()
            app.processEvents()
            img=w.grab().toImage()
            assert not img.isNull()
        finally:
            w.view.timer.stop()
            w.close()
