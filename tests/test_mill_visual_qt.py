"""Local headless GUI regression for the animation painter (no GitHub Actions)."""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'project'))
from mill_visual_ui import HelpAnimationWidget


def test_text_rendering_and_both_cuts_offscreen():
    app = QApplication.instance() or QApplication([])
    views = [HelpAnimationWidget('cross'), HelpAnimationWidget('length')]
    try:
        for view in views:
            view.resize(850, 450)
            view.show()
            app.processEvents()
            surface = QImage(320, 90, QImage.Format.Format_ARGB32)
            surface.fill(QColor('#102738'))
            painter = QPainter(surface)
            try:
                # Calls the same QTextOption path as the previously crashing code.
                view.view._draw_wrapped(
                    painter, QRectF(10, 10, 290, 65),
                    'Строка 1\nСтрока 2', align=Qt.AlignmentFlag.AlignLeft
                )
            finally:
                painter.end()
            assert not view.view.grab().isNull()
    finally:
        for view in views:
            view.view._worker.stop()
            view.close()
        app.processEvents()
