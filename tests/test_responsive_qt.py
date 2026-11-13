"""Manual offscreen Qt smoke tests for horizontal responsiveness and media wear."""
from __future__ import annotations
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QFormLayout,QScrollArea
from qt_app import MillWindow


def test_left_and_right_panels_follow_splitter_and_form_wraps():
    app=QApplication.instance() or QApplication([])
    w=MillWindow()
    try:
        assert w._adaptive_responsive_installed
        w.resize(1450,900)
        w.show()
        app.processEvents()
        splitter=w._master_splitter
        splitter.setSizes([270,1180])
        app.processEvents()
        w._adaptive_layout_timer.stop()
        from responsive_ui import _reflow_forms
        _reflow_forms(w)
        root=w.left.tabs.widget(0)
        assert isinstance(root,QScrollArea)
        width1=w.left.width()
        assert width1<500
        forms=[c.layout() for c in root.widget().findChildren(type(root.widget()))
               if isinstance(c.layout(),QFormLayout)]
        assert forms
        assert all(f.rowWrapPolicy()==QFormLayout.RowWrapPolicy.WrapAllRows for f in forms)
        splitter.setSizes([650,800])
        app.processEvents()
        _reflow_forms(w)
        assert w.left.width()>width1+50
        assert all(f.rowWrapPolicy()==QFormLayout.RowWrapPolicy.WrapLongRows for f in forms)
    finally:
        w._sim_timer.stop(); w._timer.stop(); w.close(); app.processEvents()


def test_media_wear_has_single_chart_picker_and_image_does_not_stretch():
    app=QApplication.instance() or QApplication([])
    w=MillWindow()
    try:
        assert w._fraction_metric.count()==3
        from multicore_ui import HourPlotImage
        img=HourPlotImage(w.fraction_plot,w.fraction_plot)
        assert img.hasScaledContents() is False
        assert img.minimumWidth()==0
        for i in range(3):
            w._fraction_metric.setCurrentIndex(i)
        assert w.right.tabs.tabText(2)=='Мелющие тела'
    finally:
        w._sim_timer.stop(); w._timer.stop(); w.close(); app.processEvents()
