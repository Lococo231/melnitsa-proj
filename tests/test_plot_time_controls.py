"""Ручная проверка часового курсора Matplotlib/Qt (не GitHub Actions)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from qt_app import PlotPanel


def test_hour_cursor_numeric_input_and_slider():
    app = QApplication.instance() or QApplication([])
    panel = PlotPanel()
    try:
        ax = panel.figure.add_subplot(111)
        ax.plot([0, 20, 40], [1, 2, 3], label='Тренд')
        panel.set_time_range(40)
        assert panel.toolbar is None
        assert not panel.time_controls.isHidden()
        panel.hour_spin.setValue(12.)
        assert abs(panel.hour_slider.value()-300) <= 1
        assert panel._cursor_artists
        panel.hour_slider.setValue(750)
        assert abs(panel.hour_spin.value()-30.) < .06
    finally:
        panel.close()
        app.processEvents()