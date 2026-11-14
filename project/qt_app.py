"""Цементная мельница — самостоятельное оконное приложение PySide6.

Запуск: python main.py. Ни Tkinter, ни веб-сервер не нужны.
Формулы, валидация, имитационный расчёт и Excel находятся в отдельных модулях.
"""
from __future__ import annotations

import json
import math
import sys
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSignalBlocker, QSize
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QFormLayout, QGridLayout, QGroupBox, QScrollArea, QLabel, QPushButton,
    QComboBox, QTabWidget, QDoubleSpinBox, QSpinBox, QSlider, QLineEdit, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QFileDialog, QMessageBox, QMenu, QFrame, QSizePolicy,
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from model import (
    CLASSES, MATERIALS, SIEVES, default_config, throughput, simulate_wear,
    quality_at, config_at_time, recommends, size_at_pass_percent,
    lab_bond_from_config,
)
from excel_export import export_excel
from calibration import parse_history_csv, summarize_history
from ui_data import (
    FIELDS, MODES, MEDIA_FIELDS, RELOAD_FIELDS, THROUGHPUT_FIELDS,
    is_valid_input, numeric, row_from_cells, default_table_row,
    clinker_from_csv, merge_lab_parameters,
)

ROOT = Path(__file__).resolve().parent.parent
PALETTE = ['#66cbe1', '#e9ad73', '#95d6ad', '#d4a4ef', '#e5d46f',
           '#9bbbef', '#e2a2b8', '#8de0d6', '#a5cad9']
BG = '#0e1b29'
PANEL = '#162a3d'
FG = '#ebf5fc'
MUTED = '#aec0ce'
ACCENT = '#59c5d7'

STYLE = """
QMainWindow, QWidget { background:#0e1b29; color:#eaf4fb; font-size:12px; }
QGroupBox { border:1px solid #335267; border-radius:8px; margin-top:12px;
            padding:16px 10px 10px 10px; font-weight:600; color:#82d9e6; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; }
QLabel { background:transparent; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    color:#eef8fd; background:#1f3a51; border:1px solid #44657c;
    padding:5px; border-radius:5px; min-height:23px; }
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border:1px solid #65d1e3; }
QComboBox QAbstractItemView { background:#1b344a; color:#f4fcff; selection-background-color:#317e9b; }
QPushButton { background:#294a60; color:#f4fbff; border:1px solid #3d6480;
              padding:8px 12px; border-radius:6px; font-weight:600; }
QPushButton:hover { background:#386783; }
QPushButton:pressed { background:#21718d; }
QPushButton#accent { background:#1685a0; border-color:#30bad1; }
QPushButton#accent:hover { background:#1a9dba; }
QTabWidget::pane { border:1px solid #2b4960; border-radius:6px; }
QTabBar::tab { background:#1f384e; color:#c8dae5; padding:10px 10px;
                margin-right:2px; border-radius:4px; }
QTabBar::tab:selected { background:#32627c; color:#fff; }
QTableWidget { background:#14293b; color:#f0f9ff; gridline-color:#355168;
               alternate-background-color:#1c3447; border:1px solid #37556c;
               selection-background-color:#276d8d; }
QHeaderView::section { background:#2a4b61; color:#f4fcff; padding:6px;
                       border:1px solid #35586c; font-weight:600; }
QScrollArea, QScrollArea > QWidget > QWidget { border:0; }
QScrollBar { background:#182c3d; width:12px; height:12px; }
QScrollBar::handle { background:#4b7185; border-radius:4px; min-height:24px; }
QSplitter::handle { background:#2a4b61; width:5px; }
QMenu, QMenuBar { background:#1d3448; color:#f1f8ff; }
QMenu::item:selected { background:#2a6986; }
QStatusBar { background:#203b50; color:#aecad9; }
QCheckBox { spacing:8px; }
"""


def show_number(value, digits=3):
    if value is None:
        return '—'
    if isinstance(value, float):
        if not math.isfinite(value):
            return '—'
        return f'{value:.{digits}f}'.rstrip('0').rstrip('.')
    return str(value)


def scroll_page():
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(12)
    area.setWidget(content)
    return area, content, layout


class AdaptiveTabs(QWidget):
    """Полные названия вкладок сохраняются при любом размере окна.

    Если ширины недостаточно, вместо обрезанных заголовков используется
    выпадающий список с полными именами разделов.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.picker = QComboBox()
        self.tabs = QTabWidget()
        layout.addWidget(self.picker)
        layout.addWidget(self.tabs, 1)
        self.picker.hide()
        self.picker.currentIndexChanged.connect(self._from_picker)
        self.tabs.currentChanged.connect(self._from_tabs)

    def addTab(self, page, title):
        self.tabs.addTab(page, title)
        self.picker.addItem(title)

    def _from_picker(self, index):
        if index >= 0 and self.tabs.currentIndex() != index:
            self.tabs.setCurrentIndex(index)

    def _from_tabs(self, index):
        if index >= 0 and self.picker.currentIndex() != index:
            with QSignalBlocker(self.picker):
                self.picker.setCurrentIndex(index)

    def setCurrentIndex(self, index):
        self.tabs.setCurrentIndex(index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        bar = self.tabs.tabBar()
        required = sum(bar.tabSizeHint(i).width() for i in range(bar.count()) if self.tabs.isTabVisible(i)) + 25
        compact = self.width() < required
        bar.setVisible(not compact)
        self.picker.setVisible(compact)


class CellDelegate(QStyledItemDelegate):
    """Выпадающие варианты редактируются внутри ячейки, без диалогов."""
    def __init__(self, owner, kind):
        super().__init__(owner)
        self.owner = owner
        self.kind = kind

    def createEditor(self, parent, option, index):
        key = self.owner.fields[self.kind][index.column()][0]
        if key in ('type', 'material', 'chamber'):
            combo = QComboBox(parent)
            if key == 'type':
                combo.addItems(['Шары', 'Цильпебс'])
            elif key == 'material':
                combo.addItems(list(MATERIALS))
            else:
                combo.addItems([str(i) for i in range(1, self.owner.chamber_count() + 1)])
            return combo
        box = QDoubleSpinBox(parent)
        box.setDecimals(3)
        box.setRange(0., 100000.)
        box.setSingleStep(0.5)
        if key == 'hour':
            box.setMaximum(100000.)
        return box

    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.ItemDataRole.EditRole)
        if isinstance(editor, QComboBox):
            pos = editor.findText(str(value))
            editor.setCurrentIndex(pos if pos >= 0 else 0)
        else:
            try:
                editor.setValue(numeric(value))
            except ValueError:
                editor.setValue(0.)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
        else:
            model.setData(index, show_number(editor.value()), Qt.ItemDataRole.EditRole)


class PlotPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        self.figure = Figure(facecolor=PANEL, dpi=100, figsize=(9, 6))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Вместо панели Matplotlib: курсор наработки и поле времени.
        self.toolbar = None
        layout.addWidget(self.canvas, 1)
        self.time_controls = QWidget(self)
        line = QHBoxLayout(self.time_controls)
        line.setContentsMargins(4, 1, 4, 1)
        self.hour_label = QLabel('Час работы:')
        line.addWidget(self.hour_label)
        self.hour_slider = QSlider(Qt.Orientation.Horizontal)
        self.hour_slider.setRange(0, 1000)
        line.addWidget(self.hour_slider, 1)
        self.hour_spin = QDoubleSpinBox()
        self.hour_spin.setDecimals(2)
        self.hour_spin.setRange(0., 100000.)
        self.hour_spin.setSuffix(' ч')
        self.hour_spin.setMaximumWidth(125)
        line.addWidget(self.hour_spin)
        layout.addWidget(self.time_controls)
        self.hour_readout = QLabel('')
        self.hour_readout.setWordWrap(True)
        self.hour_readout.setStyleSheet('color: #aec0ce')
        layout.addWidget(self.hour_readout)
        self.time_controls.hide()
        self.hour_readout.hide()
        self._hour_max = 0.
        self._hour_started = False
        self._cursor_artists = []
        self.hour_slider.valueChanged.connect(self._hour_from_slider)
        self.hour_spin.valueChanged.connect(self._hour_from_spin)

    def _hour_from_slider(self, value: int):
        hour = self._hour_max * value / 1000.
        with QSignalBlocker(self.hour_spin):
            self.hour_spin.setValue(hour)
        self._update_hour_cursor()

    def _hour_from_spin(self, value: float):
        fraction = value / self._hour_max if self._hour_max else 0.
        with QSignalBlocker(self.hour_slider):
            self.hour_slider.setValue(round(1000 * max(0., min(1., fraction))))
        self._update_hour_cursor()

    def set_time_range(self, max_hours: float):
        """Подключить управление часом к уже построенным временным осям."""
        hours = max(0., float(max_hours))
        if not self._hour_started:
            requested = hours
        else:
            requested = min(hours, self.hour_spin.value())
        self._hour_max = hours
        self._hour_started = True
        with QSignalBlocker(self.hour_spin), QSignalBlocker(self.hour_slider):
            self.hour_spin.setRange(0., max(hours, .01))
            self.hour_spin.setValue(requested)
            self.hour_slider.setValue(round(1000*requested/hours) if hours else 0)
        self.time_controls.show()
        self.hour_readout.show()
        self._cursor_artists = []
        self._update_hour_cursor()

    def _update_hour_cursor(self):
        hour = self.hour_spin.value()
        for artist in self._cursor_artists:
            try:
                artist.remove()
            except (ValueError, AttributeError):
                pass
        self._cursor_artists = []
        descriptions = []
        for ax in self.figure.axes:
            for line in ax.get_lines():
                label = line.get_label()
                if not label or label.startswith('_'):
                    continue
                xs = line.get_xdata()
                ys = line.get_ydata()
                if len(xs) < 2 or len(xs) != len(ys):
                    continue
                try:
                    if abs(float(xs[-1]) - float(xs[0])) < 1e-8:
                        continue
                    index = min(range(len(xs)), key=lambda i: abs(float(xs[i])-hour))
                    reading = float(ys[index])
                except (ValueError, TypeError, IndexError, OverflowError):
                    continue
                if math.isfinite(reading):
                    descriptions.append(f'{ax.get_title() or label}: {reading:.3f}')
                break
            self._cursor_artists.append(ax.axvline(hour, color='#eaf5ff', lw=1.0,
                                                   alpha=.85, linestyle=':',
                                                   label='_nolegend_', zorder=6))
        preview = '  |  '.join(descriptions[:3])
        self.hour_readout.setText(f'Выбранный час: {hour:.2f}  ·  {preview}' if preview
                                  else f'Выбранный час: {hour:.2f}')
        self.canvas.draw_idle()

    def axis(self, ax, heading, xlabel='Наработка, ч', ylabel=''):
        ax.set_facecolor(PANEL)
        ax.set_title(heading, color=FG, fontsize=10, pad=10)
        ax.set_xlabel(xlabel, color=MUTED, fontsize=8)
        ax.set_ylabel(ylabel, color=MUTED, fontsize=8)
        ax.tick_params(colors=MUTED, labelsize=8)
        ax.grid(True, color='#345164', alpha=.65)
        for spine in ax.spines.values():
            spine.set_color('#45697d')


class MillWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Цементная мельница')
        self.resize(1450, 900)
        self.setMinimumSize(QSize(790, 580))
        self.setStyleSheet(STYLE)
        self.config_data = default_config()
        self.config_data.setdefault('throughput_schedule', [])
        self.run_data = None
        self.quality_data = None
        self.history_rows = []
        self.inputs = {}
        self.geometry_fields = {}
        self.lab_labels = {}
        self.sieve_checks = {}
        self.tables = {}
        self.fields = {
            'media': MEDIA_FIELDS, 'manual_reloads': RELOAD_FIELDS,
            'throughput_schedule': THROUGHPUT_FIELDS,
        }
        self._loading = True
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(650)
        self._timer.timeout.connect(lambda: self.calculate(quiet=True))
        self._build()
        self.load_config(self.config_data, calculate=True)
        self._loading = False

    def _build(self):
        # Держим Python-ссылку на QMenu на протяжении жизни окна (важно для PySide6).
        self.file_menu = QMenu('Файл', self)
        self.menuBar().addMenu(self.file_menu)
        menu = self.file_menu
        for title, action in [
            ('Импорт параметров JSON…', self.open_json),
            ('Импорт грансостава клинкера CSV…', self.open_clinker),
            ('Импорт протокола Бонда JSON…', self.open_lab),
            ('Импорт журнала производства CSV…', self.open_history),
            ('Сохранить параметры JSON…', self.save_json),
            ('Экспорт отчёта Excel…', self.save_excel),
        ]:
            menu.addAction(title, action)
        self.model_menu = QMenu('Модель', self)
        self.menuBar().addMenu(self.model_menu)
        model_menu = self.model_menu
        model_menu.addAction('Рассчитать', lambda: self.calculate(quiet=False))
        model_menu.addAction('Восстановить пример мельницы №3', self.reset)
        base = QWidget()
        self.setCentralWidget(base)
        outer = QVBoxLayout(base)
        outer.setContentsMargins(12, 12, 12, 9)
        top = QHBoxLayout()
        title = QLabel('Цементная мельница')
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        title.setFont(font)
        top.addWidget(title)
        top.addStretch(1)
        b = QPushButton('Импорт JSON')
        b.clicked.connect(self.open_json)
        top.addWidget(b)
        b = QPushButton('Рассчитать')
        b.setObjectName('accent')
        b.clicked.connect(lambda: self.calculate(quiet=False))
        top.addWidget(b)
        b = QPushButton('Экспорт Excel')
        b.clicked.connect(self.save_excel)
        top.addWidget(b)
        outer.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)
        self.left = AdaptiveTabs()
        self.right = AdaptiveTabs()
        splitter.addWidget(self.left)
        splitter.addWidget(self.right)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([500, 930])

        geo, _, geo_layout = scroll_page()
        self.left.addTab(geo, 'Барабан и камеры')
        self._build_geometry(geo_layout)

        feed, _, feed_layout = scroll_page()
        self.left.addTab(feed, 'Подача и клинкер')
        self._build_fields(feed_layout, 'Подача и клинкер')
        self._build_feed(feed_layout)

        wear, _, wear_layout = scroll_page()
        self.left.addTab(wear, 'Прогноз износа')
        self._build_fields(wear_layout, 'Прогноз износа')
        self._build_wear_info(wear_layout)

        sieves, _, sieve_layout = scroll_page()
        self.left.addTab(sieves, 'Сита')
        self._build_sieves(sieve_layout)

        media = QWidget()
        self.left.addTab(media, 'Мелющие тела')
        self._build_editor(media, 'media', 'Состав загрузки по камерам')

        reloads = QWidget()
        self.left.addTab(reloads, 'Догрузки')
        self._build_editor(reloads, 'manual_reloads', 'Догрузки по времени')

        overview = QWidget()
        self.right.addTab(overview, 'Обзор')
        self._build_overview(overview)
        quality = PlotPanel()
        self.quality_plot = quality
        self.right.addTab(quality, 'Диаграмма помола')

        fraction = QWidget()
        self.right.addTab(fraction, 'Износ фракций')
        fl = QVBoxLayout(fraction)
        choose = QHBoxLayout()
        choose.addWidget(QLabel('Камеры:'))
        self.fraction_combo = QComboBox()
        self.fraction_combo.currentIndexChanged.connect(self._draw_fractions)
        choose.addWidget(self.fraction_combo)
        choose.addStretch(1)
        fl.addLayout(choose)
        self.fraction_plot = PlotPanel()
        fl.addWidget(self.fraction_plot, 1)

        reco_page = QWidget()
        self.right.addTab(reco_page, 'Рекомендации')
        self.reco_table = self._result_table(reco_page)
        sample_page = QWidget()
        self.right.addTab(sample_page, 'Таблица проб')
        self.sample_table = self._result_table(sample_page)
        history_page = QWidget()
        self.right.addTab(history_page, 'Заводская история')
        history_layout = QVBoxLayout(history_page)
        self.history_note = QLabel('Импортируйте CSV с журналом работы для оценки удельного износа.')
        self.history_note.setWordWrap(True)
        history_layout.addWidget(self.history_note)
        self.history_table = QTableWidget()
        history_layout.addWidget(self.history_table, 1)
        self._read_only_table(self.history_table)
        self.statusBar().showMessage('Демонстрационный расчёт. Требуется калибровка по данным предприятия.')

    def _build_geometry(self, layout):
        hint = QLabel('Один барабан, 1–2 камеры. Длины камер задаются отдельно, общая длина вычисляется автоматически. Внутренний Ø камеры не может превышать Ø барабана.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        group = QGroupBox('Геометрия и режим барабана')
        form = QFormLayout(group)
        labels = [
            ('name', 'Название', None),
            ('diameter_m', 'Диаметр барабана, м', (0.1, 10., 3)),
            ('rpm', 'Обороты, об/мин', (0.1, 40., 2)),
            ('power_kw', 'Измеренная мощность, кВт', (0., 30000., 1)),
            ('diaphragm_m', 'Перегородка, м', (0., 10., 3)),
            ('ch1', 'Длина камеры I, м', (0.01, 50., 3)),
            ('ch1d', 'Внутренний диаметр I, м', (0.01, 10., 3)),
            ('ch2', 'Длина камеры II, м', (0.01, 50., 3)),
            ('ch2d', 'Внутренний диаметр II, м', (0.01, 10., 3)),
        ]
        for key, name, bounds in labels:
            if bounds is None:
                field = QLineEdit()
                field.textChanged.connect(self.schedule)
            else:
                field = self._spin(*bounds)
            form.addRow(name, field)
            self.geometry_fields[key] = field
        self.geometry_fields['chcount'] = QComboBox()
        self.geometry_fields['chcount'].addItems(['1', '2'])
        self.geometry_fields['chcount'].currentIndexChanged.connect(self._on_chamber_count)
        form.addRow('Количество камер', self.geometry_fields['chcount'])
        self.total_length = QLabel('—')
        form.addRow('Полная длина барабана, м', self.total_length)
        for key in ('ch1','ch2','diaphragm_m'):
            self.geometry_fields[key].valueChanged.connect(self._update_total_length)
        layout.addWidget(group)
        layout.addStretch(1)

    def _spin(self, minimum=0., maximum=100000., decimals=3, value=0.):
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSingleStep(0.5 if decimals else 1)
        spin.valueChanged.connect(self.schedule)
        return spin

    def _build_fields(self, layout, group):
        frame = QGroupBox('Параметры режима' if group == 'Подача и клинкер' else 'Период и критерии')
        form = QFormLayout(frame)
        for key, label, kind in FIELDS[group]:
            if kind == 'mode':
                widget = QComboBox()
                widget.addItems(MODES)
                widget.currentIndexChanged.connect(self.schedule)
            else:
                widget = self._spin(0., 200000., 3)
                if key == 'temperature_c':
                    widget.setMinimum(-100.)
                if key == 'step_h':
                    widget.setMinimum(0.01)
                if key == 'material_hold_t':
                    widget.setMinimum(0.001)
            form.addRow(label, widget)
            self.inputs[key] = widget
        layout.addWidget(frame)

    def _build_feed(self, layout):
        info = QGroupBox('Лабораторные свойства клинкера')
        form = QFormLayout(info)
        specs = [
            ('lab_wi', 'Wi по Бонду, кВт·ч/т'),
            ('lab_origin', 'Способ определения Wi'),
            ('f80', 'F80 на входе, мкм'),
            ('grind', 'Размолоспособность'),
            ('abrasion', 'Абразивность'),
            ('density', 'Насыпная плотность, кг/м³'),
        ]
        for key, label in specs:
            w = QLabel('Нет данных')
            w.setWordWrap(True)
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.lab_labels[key] = w
            form.addRow(label, w)
        hint = QLabel('Wi лабораторный вычисляется по протоколу испытаний до работы мельницы. F80 — из грансостава входного клинкера. Не является регулятором.')
        hint.setWordWrap(True)
        form.addRow(hint)
        lab_btn = QPushButton('Импорт протокола Бонда JSON')
        lab_btn.clicked.connect(self.open_lab)
        form.addRow(lab_btn)
        layout.addWidget(info)

        incoming = QGroupBox('Гранулометрический состав клинкера, %')
        incoming_layout = QVBoxLayout(incoming)
        note = QLabel('Только импорт лабораторного грансостава: class,percent (10 классов).')
        note.setWordWrap(True)
        incoming_layout.addWidget(note)
        self.feed_table = QTableWidget(0, 2)
        self.feed_table.setHorizontalHeaderLabels(['Класс, мм', 'Массовая доля, %'])
        self._read_only_table(self.feed_table)
        self.feed_table.setMinimumHeight(260)
        incoming_layout.addWidget(self.feed_table)
        b = QPushButton('Импорт грансостава CSV')
        b.clicked.connect(self.open_clinker)
        incoming_layout.addWidget(b)
        layout.addWidget(incoming)

        schedule = QGroupBox('Подача во времени Q(t)')
        layout.addWidget(schedule)
        self._build_editor(schedule, 'throughput_schedule',
                           'Без интервалов подача постоянна; добавьте измеренные Q, т/ч.')

    def _build_wear_info(self, layout):
        box = QGroupBox('Калибровка коэффициента износа')
        v = QVBoxLayout(box)
        self.calibration_label = QLabel('Калибровочные данные не загружены')
        self.calibration_label.setWordWrap(True)
        v.addWidget(self.calibration_label)
        info = QLabel('Коэффициенты не являются настройками оператора. Для определения фактического расхода импортируйте журнал производства CSV.')
        info.setWordWrap(True)
        v.addWidget(info)
        b = QPushButton('Импорт журнала CSV')
        b.clicked.connect(self.open_history)
        v.addWidget(b)
        layout.addWidget(box)
        layout.addStretch(1)

    def _build_sieves(self, layout):
        info = QLabel('Выберите сита для графика помола и таблицы проб. R0,08 и R0,045 вычисляются всегда. Отверстия — в мм; допускается от 1 до 20 сит.')
        info.setWordWrap(True)
        layout.addWidget(info)
        box = QGroupBox('Набор лабораторных сит')
        self.sieves_grid = QGridLayout(box)
        layout.addWidget(box)
        row = QHBoxLayout()
        self.new_sieve = QDoubleSpinBox()
        self.new_sieve.setRange(0.01, 80.)
        self.new_sieve.setDecimals(3)
        self.new_sieve.setValue(0.1)
        self.new_sieve.setSuffix(' мм')
        row.addWidget(self.new_sieve)
        b = QPushButton('Добавить сито')
        b.clicked.connect(self.add_sieve)
        row.addWidget(b)
        layout.addLayout(row)
        layout.addStretch(1)

    def _set_sieves(self, selected):
        for chk in self.sieve_checks.values():
            self.sieves_grid.removeWidget(chk)
            chk.deleteLater()
        self.sieve_checks.clear()
        choices = sorted(set(SIEVES).union(selected), reverse=True)
        for i, size in enumerate(choices):
            chk = QCheckBox(f'№ {size:g} мм')
            chk.setChecked(size in selected)
            chk.toggled.connect(self.schedule)
            self.sieves_grid.addWidget(chk, i // 3, i % 3)
            self.sieve_checks[size] = chk

    def add_sieve(self):
        size = self.new_sieve.value()
        selected = [d for d, w in self.sieve_checks.items() if w.isChecked()]
        if size not in selected:
            selected.append(size)
        if len(selected) > 20:
            self._error('Выбрано больше 20 сит')
            return
        self._loading = True
        self._set_sieves(selected)
        self._loading = False
        self.schedule()

    def _build_editor(self, parent, kind, hint):
        layout = QVBoxLayout(parent) if parent.layout() is None else parent.layout()
        title = QLabel(hint)
        title.setWordWrap(True)
        layout.addWidget(title)
        buttons = QHBoxLayout()
        b = QPushButton('Добавить строку')
        b.clicked.connect(lambda: self.add_row(kind))
        buttons.addWidget(b)
        b = QPushButton('Удалить выбранную')
        b.clicked.connect(lambda: self.delete_row(kind))
        buttons.addWidget(b)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        fields = self.fields[kind]
        table = QTableWidget(0, len(fields))
        table.setHorizontalHeaderLabels([label for _, label in fields])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                              QAbstractItemView.EditTrigger.EditKeyPressed |
                              QAbstractItemView.EditTrigger.SelectedClicked)
        table.setItemDelegate(CellDelegate(self, kind))
        table.itemChanged.connect(self.schedule)
        table.setMinimumHeight(180 if kind == 'throughput_schedule' else 320)
        layout.addWidget(table, 1)
        self.tables[kind] = table

    @staticmethod
    def _read_only_table(table):
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)

    def _fill_table(self, kind, rows):
        table = self.tables[kind]
        with QSignalBlocker(table):
            table.setRowCount(len(rows))
            for i, data in enumerate(rows):
                for col, (key, _) in enumerate(self.fields[kind]):
                    table.setItem(i, col, QTableWidgetItem(show_number(data.get(key, ''))))

    def _table_rows(self, kind):
        table = self.tables[kind]
        rows = []
        for index in range(table.rowCount()):
            values = {}
            for j, (key, label) in enumerate(self.fields[kind]):
                item = table.item(index, j)
                values[key] = item.text() if item else ''
            rows.append(row_from_cells(kind, values))
        return rows

    def add_row(self, kind):
        try:
            cfg = self.collect_config()
            row = default_table_row(kind, cfg)
            trial = deepcopy(cfg)
            trial[kind].append(row)
            is_valid_input(trial)
            table = self.tables[kind]
            with QSignalBlocker(table):
                index = table.rowCount()
                table.insertRow(index)
                for j, (key, _) in enumerate(self.fields[kind]):
                    table.setItem(index, j, QTableWidgetItem(show_number(row[key])))
            table.selectRow(index)
            table.scrollToItem(table.item(index, 0))
            self.schedule()
        except Exception as exc:
            self._error(str(exc))

    def delete_row(self, kind):
        table = self.tables[kind]
        index = table.currentRow()
        if index < 0:
            return
        with QSignalBlocker(table):
            table.removeRow(index)
        self.schedule()

    def _on_chamber_count(self):
        if not self.geometry_fields:
            return
        count = self.chamber_count()
        for key in ('ch2', 'ch2d'):
            self.geometry_fields[key].setEnabled(count == 2)
        if count == 1 and not self._loading:
            n_removed = 0
            for kind in ('media','manual_reloads'):
                table = self.tables.get(kind)
                if table is None:
                    continue
                with QSignalBlocker(table):
                    for i in reversed(range(table.rowCount())):
                        item = table.item(i, 0 if kind == 'media' else 1)
                        if item and item.text().strip() == '2':
                            table.removeRow(i)
                            n_removed += 1
            if n_removed:
                self.statusBar().showMessage(f'Удалены {n_removed} записей камеры II. При необходимости верните их через импорт JSON.')
        self._update_total_length()
        self.schedule()

    def chamber_count(self):
        return int(self.geometry_fields['chcount'].currentText() or '2')

    def _update_total_length(self):
        if not self.geometry_fields:
            return
        length = self.geometry_fields['ch1'].value()
        if self.chamber_count() == 2:
            length += self.geometry_fields['ch2'].value() + self.geometry_fields['diaphragm_m'].value()
        self.total_length.setText(show_number(length, 3))

    def _build_overview(self, page):
        layout = QVBoxLayout(page)
        cards = QGridLayout()
        labels = ['Подача в начале, т/ч', 'Износ, т', 'Масса загрузки, т',
                  'R0,08 на выходе, %', 'Блейн-прокси, см²/г']
        self.metrics = []
        for i, name in enumerate(labels):
            box = QGroupBox(name)
            row = QVBoxLayout(box)
            label = QLabel('—')
            font = QFont()
            font.setBold(True)
            font.setPointSize(15)
            label.setFont(font)
            label.setStyleSheet('color:#79d5e5')
            row.addWidget(label)
            cards.addWidget(box, i // 3, i % 3)
            self.metrics.append(label)
        layout.addLayout(cards)
        self.overview_plot = PlotPanel()
        layout.addWidget(self.overview_plot, 1)
        self.derived_label = QLabel('F80: —   ·   P80: —   ·   Wi эксплуатации: —')
        self.derived_label.setWordWrap(True)
        layout.addWidget(self.derived_label)
        info = QLabel('Средний Ø — диаметр МЕЛЮЩИХ ТЕЛ, а не камеры. Внутренний диаметр камеры остаётся постоянным. Q(t) изменяется только по заданному графику подачи.')
        info.setWordWrap(True)
        layout.addWidget(info)

    def _result_table(self, page):
        layout = QVBoxLayout(page)
        table = QTableWidget()
        self._read_only_table(table)
        layout.addWidget(table)
        return table

    def schedule(self, *_):
        if not self._loading:
            self._timer.start()
            self.statusBar().showMessage('Параметры изменены — автоматический перерасчёт…')

    def _collect_mill(self):
        def v(key):
            return self.geometry_fields[key].value()
        chambers = [dict(length_m=v('ch1'), diameter_m=v('ch1d'))]
        if self.chamber_count() == 2:
            chambers.append(dict(length_m=v('ch2'), diameter_m=v('ch2d')))
        diaphragm = v('diaphragm_m')
        return dict(name=self.geometry_fields['name'].text(), diameter_m=v('diameter_m'),
                    length_m=sum(ch['length_m'] for ch in chambers) + (len(chambers)-1)*diaphragm,
                    diaphragm_m=diaphragm, chambers=chambers,
                    rpm=v('rpm'), power_kw=v('power_kw'))

    def collect_config(self):
        cfg = deepcopy(self.config_data)
        cfg['mills'] = [self._collect_mill()]
        for key, widget in self.inputs.items():
            cfg[key] = widget.currentText() if isinstance(widget, QComboBox) else widget.value()
        cfg['sieves_mm'] = sorted((d for d, chk in self.sieve_checks.items() if chk.isChecked()), reverse=True)
        for kind in self.tables:
            cfg[kind] = self._table_rows(kind)
        is_valid_input(cfg)
        return cfg

    def load_config(self, cfg, calculate=False):
        cfg = deepcopy(cfg)
        cfg.setdefault('throughput_schedule', [])
        is_valid_input(cfg)
        self._loading = True
        self._timer.stop()
        self.config_data = cfg
        m = cfg['mills'][0]
        vals = dict(name=m.get('name','Мельница'), diameter_m=m['diameter_m'],
                    rpm=m['rpm'],power_kw=m['power_kw'],diaphragm_m=m['diaphragm_m'],
                    ch1=m['chambers'][0]['length_m'],
                    ch1d=m['chambers'][0].get('diameter_m',m['diameter_m']),
                    ch2=m['chambers'][1]['length_m'] if len(m['chambers']) == 2 else 5.,
                    ch2d=m['chambers'][1].get('diameter_m',m['diameter_m'])
                    if len(m['chambers']) == 2 else m['diameter_m'])
        for key, value in vals.items():
            if key == 'name':
                self.geometry_fields[key].setText(value)
            else:
                self.geometry_fields[key].setValue(float(value))
        self.geometry_fields['chcount'].setCurrentText(str(len(m['chambers'])))
        self._on_chamber_count()
        for key, widget in self.inputs.items():
            if isinstance(widget, QComboBox):
                widget.setCurrentText(str(cfg.get(key, MODES[0])))
            else:
                widget.setValue(float(cfg.get(key, 0.)))
        self._set_sieves(cfg.get('sieves_mm', SIEVES))
        self.feed_table.setRowCount(len(CLASSES))
        for i, (name, value) in enumerate(zip(CLASSES, cfg['feed_fraction'])):
            self.feed_table.setItem(i, 0, QTableWidgetItem(name))
            self.feed_table.setItem(i, 1, QTableWidgetItem(show_number(value)))
        for kind in self.tables:
            self._fill_table(kind, cfg.get(kind, []))
        self._set_lab(cfg)
        self._loading = False
        self._update_total_length()
        if calculate:
            self.calculate(quiet=False)

    def _set_lab(self, cfg):
        wi, origin = lab_bond_from_config(cfg)
        values = dict(
            lab_wi='Нет протокола' if wi is None else f'{wi:.2f}',
            lab_origin=origin,
            f80=f'{size_at_pass_percent(cfg["feed_fraction"]):.0f}',
            grind=f'{cfg["grindability"]:g}',
            abrasion=f'{cfg["abrasion_factor"]:g}',
            density=f'{cfg["feed_bulk_density"]:,.0f}'.replace(',',' '),
        )
        for key, value in values.items():
            self.lab_labels[key].setText(value)
        origin = 'по заводской истории (предварительно)' if cfg.get('wear_calibrated') else 'демонстрационное значение'
        self.calibration_label.setText(
            f"Базовый расход: {cfg['wear_g_t']:.2f} г/т ({origin}).\n"
            f"Показатель закона размера Δ: {cfg['delta']:.2f}.\n"
            f"Диаметр выбраковки: {cfg['retention_mm']:.1f} мм."
        )

    def calculate(self, quiet=False):
        self._timer.stop()
        try:
            cfg = self.collect_config()
            run = simulate_wear(cfg)
            quality = quality_at(config_at_time(cfg, cfg['horizon_h']), run['cohorts'])
            reco = recommends(cfg, run)
            self.config_data = deepcopy(cfg)
            self.run_data = run
            self.quality_data = quality
            self._set_lab(cfg)
            self._draw_results(cfg, run, quality, reco)
            self.statusBar().showMessage(
                f"Обновлено: {len(run['rows'])} временных точек; событий догрузки: {len(run['reload_events'])}."
            )
        except Exception as exc:
            self.statusBar().showMessage(f'Исправьте данные: {exc}')
            if not quiet:
                QMessageBox.warning(self, 'Ошибка параметров', str(exc))

    @staticmethod
    def _populate_result(table, rows, columns):
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setRowCount(len(rows))
        for i, data in enumerate(rows):
            for j, key in enumerate(columns):
                item = QTableWidgetItem(show_number(data.get(key, '')))
                table.setItem(i, j, item)
        table.resizeColumnsToContents()

    def _draw_results(self, cfg, run, quality, recommendation):
        end = run['rows'][-1]
        values = [run['throughput']['product_tph'], run['total_wear_t'],
                  end['total_media_t'], quality['r008'], quality['blaine_proxy']]
        for label, value in zip(self.metrics, values):
            label.setText(show_number(value, 2))
        reco_cols = ['Камера','Тип','Материал','Ø, мм','Потеря массы, т','Износ, %','Догрузить, шт','Догрузить, т']
        self._populate_result(self.reco_table, recommendation, reco_cols)
        sample_cols = ['Точка','Расстояние по камерам, м','Камера'] + [f'R{x:g}, %' for x in cfg['sieves_mm']]
        self._populate_result(self.sample_table, quality['samples'], sample_cols)
        x = [r['hours'] for r in run['rows']]
        panel = self.overview_plot
        panel.figure.clear()
        axes = panel.figure.subplots(2, 3)
        plots = [
            ('Накопленный износ', 'т', [r['loss_t'] for r in run['rows']], PALETTE[0]),
            ('Масса загрузки', 'т', [r['total_media_t'] for r in run['rows']], PALETTE[1]),
            ('Удельный износ', 'г/т', [r['Вся загрузка, г/т'] for r in run['coefficient_history']], PALETTE[2]),
            ('Средний Ø мелющих тел', 'мм', None, PALETTE[3]),
            ('Производительность Q(t)', 'т/ч', [r['Производительность, т/ч'] for r in run['rows']], PALETTE[4]),
            ('Накопленный выпуск', 'т', [r['production_t'] for r in run['rows']], PALETTE[5]),
        ]
        for i, (name, unit, y, color) in enumerate(plots):
            ax = axes[i // 3, i % 3]
            panel.axis(ax, name, ylabel=unit)
            if i == 3:
                for chamber, clr in ((1, PALETTE[3]), (2, PALETTE[6])):
                    key = f'Б1К{chamber} Dср, мм'
                    if key in run['rows'][0]:
                        ax.plot(x, [r[key] for r in run['rows']], lw=1.8, label=f'Камера {chamber}', color=clr)
                ax.legend(fontsize=7, frameon=False, labelcolor=FG)
            elif i == 4:
                ax.step(x, y, where='post', color=color, linewidth=1.8)
            else:
                ax.plot(x, y, color=color, linewidth=1.8)
        panel.figure.subplots_adjust(hspace=.7, wspace=.45, left=.09, right=.98, top=.92, bottom=.12)
        panel.canvas.draw_idle()
        panel = self.quality_plot
        panel.figure.clear()
        ax = panel.figure.add_subplot(111)
        panel.axis(ax, 'Грансостав по длине камеры', 'Расстояние от входа, м', 'Полный остаток, %')
        points = quality['samples']
        for i, size in enumerate(cfg['sieves_mm']):
            key = f'R{size:g}, %'
            ax.plot([p['Расстояние по камерам, м'] for p in points],
                    [p[key] for p in points], lw=1.7, marker='o', markersize=3,
                    label=key, color=PALETTE[i % len(PALETTE)])
        ax.legend(fontsize=7, ncol=2, frameon=False, labelcolor=FG)
        panel.figure.tight_layout(pad=2.)
        panel.canvas.draw_idle()
        self.fraction_combo.blockSignals(True)
        old_choice = self.fraction_combo.currentText()
        self.fraction_combo.clear()
        self.fraction_combo.addItem('Все камеры')
        for n in range(1, len(cfg['mills'][0]['chambers'])+1):
            self.fraction_combo.addItem(f'Б1К{n}')
        if old_choice:
            self.fraction_combo.setCurrentText(old_choice)
        self.fraction_combo.blockSignals(False)
        op_wi = quality.get('operating_wi_kwh_t')
        op_label = 'не определён' if op_wi is None else f'{op_wi:.2f} кВт·ч/т'
        self.derived_label.setText(
            f"F80 входа: {quality['f80_um']:.0f} мкм  ·  P80 выхода: {quality['p80_um']:.0f} мкм  ·  "
            f"Wi эксплуатации: {op_label} (НЕ лабораторный Wi Бонда)"
        )
        self._draw_fractions()

    def _draw_fractions(self, *_):
        if self.run_data is None:
            return
        run = self.run_data
        selected = self.fraction_combo.currentText()
        panel = self.fraction_plot
        panel.figure.clear()
        axes = panel.figure.subplots(3, 1)
        specs = [
            ('diameter_history','Диаметры мелющих тел, мм','мм'),
            ('fraction_mass_history','Масса фракций, т','т'),
            ('coefficient_history','Удельный износ фракций, г/т','г/т'),
        ]
        for ax, (key, name, unit) in zip(axes, specs):
            panel.axis(ax, name, ylabel=unit)
            hist = run[key]
            names = [n for n in hist[0] if n not in ('Наработка, ч','Вся загрузка, г/т')
                     and (selected == 'Все камеры' or n.startswith(selected+' '))]
            for i, label in enumerate(names):
                ax.plot([r['Наработка, ч'] for r in hist],
                        [r.get(label, math.nan) for r in hist],
                        lw=1.4, label=label.replace(' · ',' '),
                        color=PALETTE[i % len(PALETTE)])
            if ax is axes[0] and names:
                ax.legend(fontsize=6, frameon=False, labelcolor=FG, ncol=2)
        panel.figure.subplots_adjust(hspace=.7, left=.12, right=.97, top=.94, bottom=.10)
        panel.canvas.draw_idle()

    @staticmethod
    def _choose_open(parent, caption, pattern):
        return QFileDialog.getOpenFileName(parent, caption, str(Path.home()), pattern)[0]

    def open_json(self):
        path = self._choose_open(self, 'Импорт JSON конфигурации', 'JSON (*.json)')
        if not path:
            return
        try:
            cfg = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            self.load_config(cfg, calculate=True)
            self.statusBar().showMessage(f'Импорт параметров: {Path(path).name}')
        except Exception as exc:
            self._error(str(exc))

    def open_lab(self):
        path = self._choose_open(self, 'Импорт лабораторного протокола Бонда', 'JSON (*.json)')
        if not path:
            return
        try:
            params = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            cfg = merge_lab_parameters(self.collect_config(), params)
            self.load_config(cfg, calculate=True)
            self.statusBar().showMessage(f'Импорт протокола Бонда: {Path(path).name}')
        except Exception as exc:
            self._error(str(exc))

    def open_clinker(self):
        path = self._choose_open(self, 'Импорт лабораторного грансостава', 'CSV (*.csv)')
        if not path:
            return
        try:
            cfg = self.collect_config()
            cfg['feed_fraction'] = clinker_from_csv(Path(path).read_bytes())
            self.load_config(cfg, calculate=True)
            self.statusBar().showMessage(f'Импорт грансостава: {Path(path).name}')
        except Exception as exc:
            self._error(str(exc))

    def open_history(self):
        path = self._choose_open(self, 'Импорт истории производства', 'CSV (*.csv)')
        if not path:
            return
        try:
            rows = parse_history_csv(Path(path).read_bytes())
            self.history_rows = rows
            cols = ['period','production_t','start_media_t','reload_t',
                    'end_media_t','removed_media_t','gmcr_g_t']
            self._populate_result(self.history_table, rows, cols)
            data = summarize_history(rows)
            self.history_note.setText(
                f"Периодов: {data['periods']} · Износ: {data['wear_t']:.3f} т · "
                f"Фактический расход: {data['gmcr_g_t']:.2f} г/т"
            )
            self.right.setCurrentIndex(5)
            answer = QMessageBox.question(
                self, 'Калибровка',
                f"Использовать средний расход {data['gmcr_g_t']:.2f} г/т как базовый коэффициент?\n"
                'Это оценка по массовому балансу, не полная калибровка всех факторов.',
            )
            if answer == QMessageBox.StandardButton.Yes:
                cfg = self.collect_config()
                cfg['wear_g_t'] = data['gmcr_g_t']
                cfg['wear_calibrated'] = True
                self.load_config(cfg, calculate=True)
            else:
                self.statusBar().showMessage('История импортирована; коэффициенты не изменены')
        except Exception as exc:
            self._error(str(exc))

    def save_json(self):
        try:
            cfg = self.collect_config()
            path = QFileDialog.getSaveFileName(self, 'Сохранить параметры',
                                               str(ROOT/'mill_config.json'), 'JSON (*.json)')[0]
            if path:
                Path(path).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
                self.statusBar().showMessage(f'Сохранено: {path}')
        except Exception as exc:
            self._error(str(exc))

    def save_excel(self):
        try:
            cfg = self.collect_config()
            run = simulate_wear(cfg)  # исключаем устаревший расчёт после редактирования
            report = export_excel(cfg, run)
            path = QFileDialog.getSaveFileName(self, 'Экспорт Excel',
                                               str(ROOT/'cement_wear_report.xlsx'),
                                               'Excel (*.xlsx)')[0]
            if path:
                Path(path).write_bytes(report)
                self.statusBar().showMessage(f'Отчёт Excel сохранён: {path}')
        except Exception as exc:
            self._error(str(exc))

    def reset(self):
        answer = QMessageBox.question(self, 'Сброс параметров',
                                      'Восстановить демонстрационные параметры мельницы №3?')
        if answer == QMessageBox.StandardButton.Yes:
            self.load_config(default_config(), calculate=True)

    def _error(self, text):
        self.statusBar().showMessage(text)
        QMessageBox.warning(self, 'Цементная мельница', text)


from production_ui import install as install_production_ui
install_production_ui(MillWindow)
from workflow_ui import install as install_workflow_ui
install_workflow_ui(MillWindow)
from timeline_ui import install as install_timeline_ui
install_timeline_ui(MillWindow)
from multicore_ui import install as install_multicore_ui
install_multicore_ui(MillWindow)
from workspace_ui import install as install_workspace_ui
install_workspace_ui(MillWindow)
from staged_results_ui import install as install_staged_results_ui
install_staged_results_ui(MillWindow)
from responsive_ui import install as install_responsive_ui
install_responsive_ui(MillWindow)
from adaptive_graphs_ui import install as install_adaptive_graphs_ui
install_adaptive_graphs_ui(MillWindow)
from operator_workflow_ui import install as install_operator_workflow_ui
install_operator_workflow_ui(MillWindow)
from live_multicore_ui import install as install_live_multicore_ui
install_live_multicore_ui(MillWindow)

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MillWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
