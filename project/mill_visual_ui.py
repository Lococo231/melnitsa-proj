"""Animated help widgets for the milling application.

Changes in this version:
- fixes the PySide6 TextWordWrap crash by using QTextOption-based drawing
- redesigns the longitudinal section to better match common two-chamber cement
  ball mill schematics: feed, coarse chamber, diaphragm, fine chamber, air flow,
  discharge and rolling media bed
- runs both animation models in background CPU threads; Qt only paints snapshots
"""
from __future__ import annotations

import math
import threading
import time
import weakref
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPen,
                           QPolygonF, QRadialGradient, QTextOption)
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from mill_dynamics import DrumCharge, AxialTransport

_SOURCE = None


def set_source(window):
    global _SOURCE
    _SOURCE = weakref.ref(window)


@dataclass
class Snapshot:
    kind: str
    payload: dict[str, Any]


def current_parameters() -> dict[str, Any]:
    if _SOURCE is not None:
        window = _SOURCE()
        if window is not None:
            try:
                return window.collect_config()
            except Exception:
                pass
    return {
        'mills': [{'diameter_m': 4.0, 'rpm': 16.0, 'length_m': 13.4,
                   'chambers': [{'length_m': 6.3}, {'length_m': 6.6}]}],
        'media': [],
        'fresh_feed_tph': 72.0,
    }


def _color(grade: int) -> QColor:
    colors = ['#be8a58', '#cda068', '#d8b879', '#c6ba8e', '#a6c3ad',
              '#8ec8c7', '#68bcd3', '#6aaadd', '#7b98d3', '#9d9ad3']
    return QColor(colors[min(9, max(0, int(grade)))])


class AnimationThread(threading.Thread):
    def __init__(self, mode: str, chamber: int = 1, fps: int = 30):
        super().__init__(daemon=True)
        self.mode = mode
        self.chamber = chamber
        self.fps = max(12, min(60, int(fps)))
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._params = current_parameters()
        self._snapshot = Snapshot(mode, {})
        self._build_models()

    def _build_models(self) -> None:
        params = self._params
        mill = params['mills'][0]
        lengths = [float(c.get('length_m', 6.0)) for c in mill.get('chambers', [])]
        if not lengths:
            lengths = [6.3, 6.6]
        while len(lengths) < 2:
            lengths.append(lengths[-1])
        self.rpm = float(mill.get('rpm', 16.0))
        self.diameter = float(mill.get('diameter_m', 4.0))
        media = []
        for item in params.get('media', []):
            if int(item.get('chamber', 1)) == self.chamber:
                media.append(float(item.get('diameter_mm', 50.0)))
        self.drum = DrumCharge(rpm=self.rpm, diameter_m=self.diameter,
                               chamber=self.chamber, sizes_mm=media)
        self.axial = AxialTransport(lengths)

    def set_chamber(self, chamber: int) -> None:
        with self._lock:
            self.chamber = int(chamber)
            self._params = current_parameters()
            self._build_models()

    def refresh_parameters(self) -> None:
        with self._lock:
            self._params = current_parameters()
            # Update only speed/feed-sensitive values to avoid jarring resets.
            try:
                self.rpm = float(self._params['mills'][0].get('rpm', self.rpm))
                self.drum.rpm = self.rpm
                self.drum.omega = 2 * math.pi * self.rpm / 60.0
            except Exception:
                pass

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def pause(self, value: bool) -> None:
        if value:
            self._paused.set()
        else:
            self._paused.clear()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        interval = 1.0 / self.fps
        previous = time.perf_counter()
        while not self._stop_event.is_set():
            if self._paused.is_set():
                time.sleep(0.03)
                previous = time.perf_counter()
                continue
            now = time.perf_counter()
            dt = min(0.08, max(0.012, now - previous))
            previous = now
            with self._lock:
                # A worker must never read Qt widgets via collect_config().
                # The GUI thread refreshes immutable scalar settings on show/change.
                feed = float(self._params.get('fresh_feed_tph', 72.0))
                self.drum.step(dt)
                self.axial.step(dt, feed)
                if self.mode == 'cross':
                    self._snapshot = Snapshot('cross', {
                        'rpm': self.rpm,
                        'critical': self.drum.critical_rpm,
                        'rotation': self.drum.rotation,
                        'impact_count': self.drum.impact_count,
                        'breakage_count': self.drum.breakage_count,
                        'chamber': self.chamber,
                        'balls': [(b.x, b.y, b.r) for b in self.drum.balls],
                        'grains': [(g.x, g.y, g.r, g.grade) for g in self.drum.grains],
                    })
                else:
                    layout = self.axial.media_layout()
                    self._snapshot = Snapshot('length', {
                        'discharge': self.axial.discharge,
                        'split': self.axial.split,
                        'time': self.axial.time,
                        'particles': [(p.x, p.y, p.grade, p.chamber) for p in self.axial.particles],
                        'media_ch1': layout['ch1'],
                        'media_ch2': layout['ch2'],
                    })
            elapsed = time.perf_counter() - now
            if elapsed < interval:
                time.sleep(interval - elapsed)


class MillCutWidget(QWidget):
    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        self.mode = mode
        self._chamber = 1
        self._font_small = QFont('Segoe UI', 9)
        self._font_title = QFont('Segoe UI', 10)
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(33)
        self._render_timer.timeout.connect(self.update)
        self._render_timer.start()
        self._worker = AnimationThread(mode='cross' if mode == 'cross' else 'length', chamber=1, fps=30)
        self._user_paused = False
        worker = self._worker
        self.destroyed.connect(lambda *_: worker.stop())
        self._worker.start()
        self.setMinimumHeight(310)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_chamber(self, number: int) -> None:
        self._chamber = int(number)
        self._worker.set_chamber(self._chamber)
        self.update()

    def set_paused(self, value: bool) -> None:
        self._user_paused = bool(value)
        self._worker.pause(value)
        if value:
            self._render_timer.stop()
        else:
            self._render_timer.start()

    def closeEvent(self, event):
        try:
            self._worker.stop()
        finally:
            super().closeEvent(event)

    def hideEvent(self, event):
        # Paused hidden animations must not consume background CPU.
        self._worker.pause(True)
        super().hideEvent(event)

    def showEvent(self, event):
        self._worker.refresh_parameters()
        self._worker.pause(self._user_paused)
        super().showEvent(event)

    def _background(self, painter: QPainter, rect: QRectF):
        painter.fillRect(self.rect(), QColor('#0c1e2c'))
        painter.setPen(QPen(QColor('#355e75'), 1))
        painter.setBrush(QBrush(QColor('#142f42')))
        painter.drawRoundedRect(rect, 12, 12)

    def _circle(self, painter: QPainter, x: float, y: float, r: float,
                color: QColor, shaded: bool = True):
        if shaded:
            grad = QRadialGradient(x - r * 0.34, y - r * 0.42, r * 1.30)
            grad.setColorAt(0.0, QColor('#eef5f7'))
            grad.setColorAt(0.26, QColor(color))
            grad.setColorAt(1.0, QColor('#344b5c'))
            painter.setBrush(QBrush(grad))
        else:
            painter.setBrush(QColor(color))
        painter.setPen(QPen(QColor('#122c39'), 0.65))
        painter.drawEllipse(QRectF(x - r, y - r, 2 * r, 2 * r))

    def _draw_wrapped(self, painter: QPainter, rect: QRectF, text: str,
                      color: str = '#cfe2ec', align=Qt.AlignmentFlag.AlignLeft):
        painter.save()
        painter.setPen(QColor(color))
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        option.setAlignment(align | Qt.AlignmentFlag.AlignTop)
        painter.drawText(rect, text, option)
        painter.restore()

    def _cross(self, painter: QPainter, rect: QRectF, snap: Snapshot):
        data = snap.payload
        size = min(rect.width() * 0.70, rect.height() * 0.90)
        rad = size * 0.47
        cx = rect.center().x() - 0.10 * rect.width()
        cy = rect.center().y() + 10
        painter.setBrush(QBrush(QColor('#17364a')))
        painter.setPen(QPen(QColor('#e6ae54'), max(3.0, rad * 0.026)))
        painter.drawEllipse(QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad))
        rotation = float(data.get('rotation', 0.0))
        for idx in range(18):
            theta = rotation + idx * 2 * math.pi / 18
            x1 = cx + rad * 0.95 * math.cos(theta)
            y1 = cy + rad * 0.95 * math.sin(theta)
            x2 = cx + rad * 0.86 * math.cos(theta + 0.045)
            y2 = cy + rad * 0.86 * math.sin(theta + 0.045)
            painter.setPen(QPen(QColor('#d7a04d'), max(1.5, rad * 0.016)))
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
        for x, y, r0, grade in data.get('grains', []):
            self._circle(painter, cx + x * rad, cy + y * rad,
                         max(1.5, r0 * rad), _color(int(grade)), shaded=False)
        for x, y, r0 in data.get('balls', []):
            self._circle(painter, cx + x * rad, cy + y * rad,
                         max(4.0, r0 * rad), QColor('#8fa5b0'))
        info_x = cx + rad + 18
        width = max(150, rect.right() - info_x - 12)
        painter.setFont(self._font_title)
        ratio = 100.0 * float(data.get('rpm', 0.0)) / max(0.01, float(data.get('critical', 1.0)))
        self._draw_wrapped(
            painter,
            QRectF(info_x, cy - rad + 4, width, 76),
            f'Камера {data.get("chamber", self._chamber)}\n'
            f'{float(data.get("rpm", 0.0)):.1f} об/мин\n'
            f'{ratio:.0f}% критической скорости',
            color='#d8e9f2')
        painter.setFont(self._font_small)
        self._draw_wrapped(
            painter,
            QRectF(info_x, cy - 8, width, 110),
            f'Ударов (схема): {int(data.get("impact_count", 0))}\n'
            f'Дроблений (схема): {int(data.get("breakage_count", 0))}\n'
            'Подъём зарядки лайнерами → падение → удар и истирание',
            color='#b5c9d6')
        self._draw_wrapped(
            painter,
            QRectF(rect.left() + 12, rect.bottom() - 38, rect.width() - 24, 28),
            'Поперечный разрез: каскадно-катарктирующее движение мелющих тел. Демонстрационная 2D модель.',
            color='#6d94aa', align=Qt.AlignmentFlag.AlignHCenter)

    def _length(self, painter: QPainter, rect: QRectF, snap: Snapshot):
        d = snap.payload
        x = rect.left() + 58
        y = rect.top() + 64
        width = rect.width() - 126
        height = max(160.0, rect.height() - 120)
        split = x + width * float(d.get('split', 0.48))
        shell = QRectF(x, y, width, height)
        ymid = y + height * 0.50

        # Feed hopper and discharge cone.
        painter.setPen(QPen(QColor('#d5a35c'), 3))
        painter.setBrush(QColor('#203b4d'))
        painter.drawRoundedRect(shell, 12, 12)
        painter.setBrush(QColor('#1a3346'))
        feed = QPolygonF([QPointF(x - 54, y + 22), QPointF(x - 7, y + 30),
                          QPointF(x - 7, ymid - 16), QPointF(x - 38, ymid - 18),
                          QPointF(x - 54, ymid - 44)])
        painter.drawPolygon(feed)
        discharge = QPolygonF([QPointF(x + width + 6, ymid - 16), QPointF(x + width + 44, ymid - 28),
                               QPointF(x + width + 54, ymid - 18), QPointF(x + width + 54, ymid + 22),
                               QPointF(x + width + 12, ymid + 16)])
        painter.drawPolygon(discharge)

        # Chamber separator / diaphragm.
        painter.setPen(QPen(QColor('#dfb26f'), 4))
        painter.drawLine(int(split), int(y + 2), int(split), int(y + height - 2))
        painter.setPen(QPen(QColor('#7bb4bd'), 2))
        for i in range(8):
            yy = y + 12 + i * (height - 24) / 7
            painter.drawLine(int(split - 5), int(yy), int(split + 5), int(yy))

        # Charge bed polygons: chamber 1 higher shoulder, chamber 2 more stable fine bed.
        painter.setPen(QPen(QColor('#38586d'), 1.0))
        painter.setBrush(QColor('#30475a'))
        ch1 = QPolygonF([
            QPointF(x + 4, ymid + height * 0.27),
            QPointF(x + (split - x) * 0.08, ymid + height * 0.14),
            QPointF(x + (split - x) * 0.24, ymid + height * 0.04),
            QPointF(x + (split - x) * 0.47, ymid + height * 0.06),
            QPointF(x + (split - x) * 0.76, ymid + height * 0.20),
            QPointF(split - 4, ymid + height * 0.28),
            QPointF(split - 4, y + height - 4), QPointF(x + 4, y + height - 4),
        ])
        painter.drawPolygon(ch1)
        painter.setBrush(QColor('#2d4456'))
        ch2 = QPolygonF([
            QPointF(split + 4, ymid + height * 0.24),
            QPointF(split + (x + width - split) * 0.20, ymid + height * 0.14),
            QPointF(split + (x + width - split) * 0.46, ymid + height * 0.10),
            QPointF(split + (x + width - split) * 0.78, ymid + height * 0.16),
            QPointF(x + width - 4, ymid + height * 0.25),
            QPointF(x + width - 4, y + height - 4), QPointF(split + 4, y + height - 4),
        ])
        painter.drawPolygon(ch2)

        # Ball charge layouts.
        for xn, yn, rn in d.get('media_ch1', []):
            xx = x + xn * (split - x)
            yy = ymid + (yn - 0.5) * height * 0.62
            self._circle(painter, xx, yy, rn * height, QColor('#8ba5b4'))
        for xn, yn, rn in d.get('media_ch2', []):
            xx = split + xn * (x + width - split)
            yy = ymid + (yn - 0.5) * height * 0.62
            self._circle(painter, xx, yy, rn * height, QColor('#81a7a2'))

        # Axial stream of clinker/cement particles.
        for pxn, pyn, grade, chamber in d.get('particles', []):
            xx = x + pxn * width
            yy = y + pyn * height
            rr = max(2.3, min(8.0, (11 - grade) * 0.54))
            self._circle(painter, xx, yy, rr, _color(int(grade)), shaded=False)
            if chamber == 1 and pxn < 0.18:
                painter.setPen(QPen(QColor('#68d8cf'), 1.2))
                painter.drawLine(int(xx - 6), int(yy), int(xx - 1), int(yy))

        # Air/product flow arrows.
        painter.setPen(QPen(QColor('#68d8cf'), 2.2))
        painter.drawLine(int(x - 34), int(ymid - 10), int(x - 2), int(ymid - 10))
        painter.drawLine(int(x + width + 4), int(ymid + 8), int(x + width + 38), int(ymid + 8))
        painter.drawLine(int(split - 24), int(y + 18), int(split - 4), int(y + 18))
        painter.drawLine(int(split + 4), int(y + 18), int(split + 24), int(y + 18))
        for ax in (x + 34, x + width * 0.42, split + 30, x + width - 70):
            painter.drawLine(int(ax), int(y + 10), int(ax + 14), int(y + 10))

        painter.setFont(self._font_title)
        self._draw_wrapped(painter, QRectF(x - 56, y - 36, 120, 30), 'Подача\nклинкера', '#d8e9f2')
        self._draw_wrapped(painter, QRectF(x + 10, y + 7, (split - x) - 18, 30), 'Камера 1 - грубый помол', '#d8e9f2')
        self._draw_wrapped(painter, QRectF(split + 10, y + 7, (x + width - split) - 18, 30), 'Камера 2 - тонкий помол', '#d8e9f2')
        self._draw_wrapped(painter, QRectF(split - 52, y - 34, 108, 28), 'Перфорированная\nперегородка', '#c5d7e4', align=Qt.AlignmentFlag.AlignHCenter)
        self._draw_wrapped(painter, QRectF(x + width - 42, y - 36, 118, 30), 'Выход\nцемента', '#d8e9f2', align=Qt.AlignmentFlag.AlignRight)

        painter.setFont(self._font_small)
        self._draw_wrapped(
            painter,
            QRectF(x, rect.bottom() - 38, width, 32),
            f'Продольный разрез: крупные тела и ударное дробление в 1-й камере, '
            f'мелкая загрузка и истирание во 2-й. Разгрузка частиц (схема): {int(d.get("discharge", 0))}.',
            color='#6d94aa', align=Qt.AlignmentFlag.AlignHCenter)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(7, 7, -7, -7)
        self._background(painter, rect)
        snap = self._worker.snapshot()
        if self.mode == 'cross':
            self._cross(painter, rect, snap)
        else:
            self._length(painter, rect, snap)
        painter.end()


class HelpAnimationWidget(QWidget):
    """Drop-in replacement for operator_workflow_ui.HelpAnimationWidget."""

    def __init__(self, mode, parent=None):
        super().__init__(parent)
        self.view = MillCutWidget('cross' if mode == 'cross' else 'length', self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.pause = QPushButton('Пауза')
        self.pause.setCheckable(True)
        self.pause.toggled.connect(self._toggle)
        controls.addWidget(self.pause)
        if mode == 'cross':
            controls.addWidget(QLabel('Камера:'))
            self.chamber_picker = QComboBox()
            chambers = len(current_parameters().get('mills', [{}])[0].get('chambers', [])) or 2
            self.chamber_picker.addItems([f'Камера {i + 1}' for i in range(chambers)])
            self.chamber_picker.currentIndexChanged.connect(lambda i: self.view.set_chamber(i + 1))
            controls.addWidget(self.chamber_picker)
        controls.addStretch(1)
        badge = QLabel('Анимация: расчёт кадра в фоне, отрисовка в Qt')
        badge.setStyleSheet('color:#9eb7c8')
        controls.addWidget(badge)
        layout.addLayout(controls)
        layout.addWidget(self.view, 1)
        self.setMinimumHeight(340)

    def _toggle(self, paused):
        self.view.set_paused(bool(paused))
        self.pause.setText('Продолжить' if paused else 'Пауза')
