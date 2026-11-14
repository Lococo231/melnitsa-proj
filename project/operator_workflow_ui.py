"""Operator-facing workflow polish for cement mill simulation.

Installed last, after staged_results_ui / responsive_ui / adaptive_graphs_ui.
Adds help/export menus, removes verbose heading panels, and introduces
segment-based simulation logging inside the Simulation tab.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import io
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QMenu, QPlainTextEdit, QPushButton,
    QScrollArea, QSplitter, QTableWidget, QTabWidget, QTableWidgetItem,
    QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

import workflow_ui
import workspace_ui
from operator_export import save_selected_export

SIM_KEYS = {
    'sim0': ('r008', 'R0,08', '%'),
    'sim1': ('r0045', 'R0,045', '%'),
    'sim2': ('blaine_proxy', 'Блейн (прокси)', 'см²/г'),
    'sim3': ('media_mass_t', 'Масса мелющих тел', 'т'),
    'sim4': ('wear_cumulative_t', 'Накопленный износ мелющих тел', 'т'),
    'sim5': ('chamber_diameters_mm', 'Средний диаметр по камерам', 'мм'),
}

HTML_HELP = """
<h2>Как работает программа</h2>
<ol>
<li><b>Задайте исходные данные мельницы.</b> Слева заполняются грансостав клинкера,
геометрия барабана, режимы работы, состав мелющих тел и лабораторные/производственные параметры.</li>
<li><b>Откройте «Симуляцию работы».</b> Выберите вид цемента и длительность очередного отрезка работы.</li>
<li><b>Нажмите «Пуск».</b> Программа фиксирует текущие входные данные и рассчитывает модельный отрезок
работы с изменением мелющих тел во времени.</li>
<li><b>При необходимости измените исходные данные.</b> После нового «Пуск» следующий отрезок
добавляется к предыдущему. Графики R0,08, R0,045, Блейна и массы загрузки продолжаются по общему времени.</li>
<li><b>Используйте журнал симуляций.</b> На вкладке симуляции сохраняются номер расчёта,
марка цемента, длительность и полный снимок входных параметров на момент запуска.</li>
<li><b>Экспорт.</b> Через меню «Экспорт» можно выбрать, какие таблицы и журналы выгружать в файл.</li>
</ol>
<p><b>Примечание.</b> R0,08 и R0,045 рассчитываются модельно по технологической карте; Блейн — расчётный прокси.
При выходе показателей за нормативы используются рекомендации по корректировке загрузки.</p>
"""


def _find_main_window(widget: QWidget | None) -> QMainWindow | None:
    while widget is not None:
        if isinstance(widget, QMainWindow):
            return widget
        widget = widget.parentWidget()
    return None


def _table_to_rows(table: QTableWidget) -> list[dict]:
    headers = []
    for c in range(table.columnCount()):
        item = table.horizontalHeaderItem(c)
        headers.append(item.text() if item else f'Колонка {c+1}')
    rows = []
    for r in range(table.rowCount()):
        row = {}
        empty = True
        for c, h in enumerate(headers):
            item = table.item(r, c)
            text = item.text().strip() if item else ''
            if text:
                empty = False
            row[h] = text
        if not empty:
            rows.append(row)
    return rows


def _config_summary(cfg: dict) -> list[tuple[str, str]]:
    items = []
    for key in sorted(cfg):
        value = cfg[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            items.append((str(key), '' if value is None else str(value)))
    return items


def _infer_cement_name(window, snapshot: dict) -> str:
    for key in ('profile', 'cement_profile', 'cement_name', 'cement'):
        value = snapshot.get(key)
        if isinstance(value, str) and value:
            return value
    for cb in window.findChildren(QComboBox):
        text = cb.currentText().strip()
        if 'ЦЕМ' in text.upper():
            return text
    return 'Текущий режим'


def _infer_duration_text(result: dict) -> str:
    days = result.get('days')
    hpd = result.get('hours_per_day')
    hours = result.get('hours')
    if days is not None and hpd is not None:
        try:
            return f'{float(days):g} дней × {float(hpd):g} ч = {float(hours):g} ч'
        except Exception:
            pass
    if hours is not None:
        try:
            return f'{float(hours):g} ч'
        except Exception:
            return str(hours)
    return '—'


def _offset_rows(rows: list[dict], offset: float, key='hour') -> list[dict]:
    out = []
    for row in rows or []:
        nr = deepcopy(row)
        if key in nr:
            try:
                nr[key] = float(nr[key]) + offset
            except Exception:
                pass
        out.append(nr)
    return out


def _offset_table_rows(rows: list[dict], offset: float, key='Час наработки') -> list[dict]:
    out = []
    for row in rows or []:
        nr = deepcopy(row)
        if key in nr:
            try:
                nr[key] = float(nr[key]) + offset
            except Exception:
                pass
        out.append(nr)
    return out


def _combine_segments(segments: list[dict]) -> dict | None:
    if not segments:
        return None
    total = {
        'baseline': [],
        'optimized': [],
        'cement_changes': [],
        'actions': [],
        'hours': 0.0,
        'days': 0.0,
        'hours_per_day': 0.0,
    }
    offset = 0.0
    days = 0.0
    for index, segment in enumerate(segments, 1):
        result = deepcopy(segment['result'])
        baseline = result.get('baseline') or []
        for row in baseline:
            nr = deepcopy(row)
            nr['hour'] = float(nr.get('hour', 0.0)) + offset
            nr['_segment_index'] = index
            total['baseline'].append(nr)
        for row in result.get('optimized') or []:
            nr = deepcopy(row)
            nr['hour'] = float(nr.get('hour', 0.0)) + offset
            total['optimized'].append(nr)
        total['cement_changes'].extend(_offset_table_rows(result.get('cement_changes') or [], offset))
        actions = result.get('actions') or ([] if result.get('action') is None else [result['action']])
        for action in actions:
            na = deepcopy(action)
            try:
                na['hour'] = float(na.get('hour', 0.0)) + offset
            except Exception:
                pass
            total['actions'].append(na)
        hours = float(result.get('hours', 0.0) or 0.0)
        offset += hours
        days += float(result.get('days', 0.0) or 0.0)
    last = deepcopy(segments[-1]['result'])
    for key in ('samples', 'sample_rows', 'summary', 'recommendation', 'action', 'warnings'):
        if key in last:
            total[key] = deepcopy(last[key])
    total['hours'] = offset
    total['days'] = days
    total['hours_per_day'] = segments[-1]['result'].get('hours_per_day', 0)
    total['media_mass_t'] = total['baseline'][-1].get('media_mass_t') if total['baseline'] else None
    return total


class HelpAnimationWidget(QWidget):
    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(40)
        self.setMinimumHeight(240)

    def _tick(self):
        self.phase = (self.phase + 0.07) % 6.28318
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#122738'))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(18, 18, -18, -18)
        p.setPen(QPen(QColor('#53738d'), 3))
        p.setBrush(QColor('#1b3a4d'))
        p.drawRoundedRect(r, 16, 16)
        p.setPen(QColor('#dfeef8'))
        if self.mode == 'cross':
            p.drawText(r.adjusted(0, 6, 0, 0), Qt.AlignmentFlag.AlignHCenter, 'Поперечный разрез барабана')
            cx, cy = r.center().x(), r.center().y() + 16
            radius = min(r.width(), r.height()) * 0.30
            p.setBrush(QColor(30, 70, 90, 90))
            p.drawEllipse(int(cx-radius), int(cy-radius), int(radius*2), int(radius*2))
            for i in range(22):
                angle = self.phase + i * 0.32
                bx = cx + 0.72 * radius * __import__('math').cos(angle)
                by = cy + 0.72 * radius * __import__('math').sin(angle)
                size = 10 + (i % 3)
                p.setBrush(QColor('#d2b16d' if i % 2 else '#80c7de'))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(int(bx-size/2), int(by-size/2), size, size)
        else:
            p.drawText(r.adjusted(0, 6, 0, 0), Qt.AlignmentFlag.AlignHCenter, 'Продольный разрез мельницы')
            left = r.left() + 18
            right = r.right() - 18
            top = r.top() + 58
            bottom = r.bottom() - 28
            mid = left + (right-left) * 0.58
            p.setPen(QPen(QColor('#7f9db0'), 2))
            p.drawLine(int(mid), top, int(mid), bottom)
            p.drawText(int((left+mid)/2)-40, top-12, 'Камера 1')
            p.drawText(int((mid+right)/2)-40, top-12, 'Камера 2')
            # material stream
            p.setPen(QPen(QColor('#4ec4ff'), 3))
            y = top + 18 + int(8 * __import__('math').sin(self.phase * 1.8))
            p.drawLine(left + 8, y, right - 8, y)
            # grinding bodies
            for i in range(14):
                x = left + 18 + i * (right-left-36) / 13.0
                wobble = 10 * __import__('math').sin(self.phase*1.4 + i*0.55)
                p.setBrush(QColor('#e1c275' if x < mid else '#7bd0be'))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(int(x-7), int((top+bottom)/2 + wobble), 14, 14)
        p.end()


class SimulationDetailDialog(QDialog):
    def __init__(self, segment: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Симуляция №{segment["index"]}')
        self.resize(760, 680)
        layout = QVBoxLayout(self)
        info = QLabel(f'<b>Вид цемента:</b> {segment["cement"]}<br>'
                      f'<b>Длительность:</b> {segment["duration"]}<br>'
                      f'<b>Время запуска:</b> {segment["timestamp"]}')
        info.setWordWrap(True)
        layout.addWidget(info)
        tabs = QTabWidget()
        # snapshot
        snap = QTableWidget()
        snap.setColumnCount(2)
        snap.setHorizontalHeaderLabels(['Параметр', 'Значение'])
        rows = _config_summary(segment['snapshot'])
        snap.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            snap.setItem(r, 0, QTableWidgetItem(k))
            snap.setItem(r, 1, QTableWidgetItem(v))
        snap.resizeColumnsToContents()
        tabs.addTab(snap, 'Снимок входных данных')
        raw = QPlainTextEdit(json.dumps(segment['snapshot'], ensure_ascii=False, indent=2))
        raw.setReadOnly(True)
        tabs.addTab(raw, 'JSON')
        layout.addWidget(tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class ExportDialog(QDialog):
    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.setWindowTitle('Экспорт данных')
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Выберите данные, которые нужно включить в экспортный файл:'))
        self.checks = {}
        for key, text, checked in [
            ('segments', 'Журнал симуляций', True),
            ('segment_details', 'Снимки входных данных по симуляциям', True),
            ('sim_status', 'Результат проверки режима', True),
            ('recommendations', 'Рекомендации', True),
            ('sample_table', 'Таблица проб', False),
            ('start_table', 'Начальная загрузка', False),
            ('journal_tables', 'Автоматический журнал и история', True),
            ('current_config', 'Текущая конфигурация', True),
        ]:
            cb = QCheckBox(text)
            cb.setChecked(checked)
            self.checks[key] = cb
            layout.addWidget(cb)
        form = QFormLayout()
        self.format_combo = QComboBox()
        self.format_combo.addItems(['Excel (*.xlsx)', 'JSON (*.json)'])
        form.addRow('Формат файла:', self.format_combo)
        layout.addLayout(form)
        self.info = QLabel('')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        selected = [k for k, cb in self.checks.items() if cb.isChecked()]
        if not selected:
            self.info.setText('Выберите хотя бы один набор данных для выгрузки.')
            return
        suffix = '.xlsx' if self.format_combo.currentIndex() == 0 else '.json'
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить экспорт', str(Path.home() / f'melnitsa_export{suffix}'))
        if not path:
            return
        try:
            export_selected(self.window, selected, Path(path))
        except Exception as exc:
            QMessageBox.warning(self, 'Ошибка экспорта', str(exc))
            return
        self.info.setText(f'Файл сформирован: {path}')
        QMessageBox.information(self, 'Экспорт завершён', f'Файл сохранён:\n{path}')
        self.accept()


def export_selected(window, selected: list[str], path: Path):
    payload = {
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'selected': selected,
    }
    if 'segments' in selected:
        payload['segments'] = [
            {'index': s['index'], 'cement': s['cement'], 'duration': s['duration'], 'timestamp': s['timestamp']}
            for s in getattr(window, '_sim_segments', [])
        ]
    if 'segment_details' in selected:
        payload['segment_details'] = [
            {'index': s['index'], 'cement': s['cement'], 'duration': s['duration'], 'snapshot': s['snapshot']}
            for s in getattr(window, '_sim_segments', [])
        ]
    if 'sim_status' in selected:
        # This is a QLabel, not a QTableWidget.
        payload['sim_status'] = [{'Результат проверки': window.sim_status.text()}]
    if 'recommendations' in selected:
        payload['recommendations'] = _table_to_rows(window.reco_table)
    if 'sample_table' in selected:
        payload['sample_table'] = _table_to_rows(window.sample_table)
    if 'start_table' in selected:
        payload['start_table'] = _table_to_rows(window.start_table)
    if 'journal_tables' in selected:
        payload['journal_initial'] = _table_to_rows(window._workspace_initial)
        payload['journal_tables'] = {k: _table_to_rows(v) for k, v in getattr(window, '_workspace_log_tables', {}).items()}
    if 'current_config' in selected:
        payload['current_config'] = deepcopy(window.collect_config())

    save_selected_export(payload, path)


def install(MillWindow):
    if getattr(MillWindow, '_operator_workflow_installed', False):
        return
    MillWindow._operator_workflow_installed = True
    old_build = MillWindow._build
    old_done = MillWindow._sim_done
    old_fail = MillWindow._sim_fail

    def _hide_helper_headings(window):
        texts = {
            'Исходные параметры мельницы',
            'Контроль помола',
            'Мелющие тела',
            'Автоматический журнал работы',
        }
        for label in window.findChildren(QLabel):
            t = (label.text() or '').replace('<b>', '').replace('</b>', '')
            if any(text in t for text in texts):
                parent = label.parentWidget()
                # hide only banner-like labels, not tab names or content captions.
                if parent is not None and label.minimumHeight() >= 0 and label.sizeHint().height() > 36:
                    label.hide()
        # also remove the explanatory section label on grouped tabs
        for group in (getattr(window, '_grind_stages', None), getattr(window, '_media_stages', None)):
            if group is None:
                continue
            page = group.parentWidget()
            if page and page.layout() and page.layout().count() > 0:
                first = page.layout().itemAt(0).widget()
                if isinstance(first, QLabel):
                    first.hide()
        if hasattr(window, '_grind_stages'):
            window._grind_stages.setTabText(0, 'Диаграмма помола')
            window._grind_stages.setTabText(1, 'Таблица проб')
        if hasattr(window, '_media_stages'):
            window._media_stages.setTabText(0, 'Начальная загрузка')
            window._media_stages.setTabText(1, 'Износ фракций')

    def _add_table_caption(layout, text, before_widget):
        label = QLabel(text)
        label.setStyleSheet('background:#2a4a61; color:#eef4f8; padding:6px 10px; '
                            'border-top-left-radius:4px; border-top-right-radius:4px; '
                            'border:1px solid #4a6577; border-bottom:none;')
        idx = layout.indexOf(before_widget)
        if idx < 0:
            layout.addWidget(label)
        else:
            layout.insertWidget(idx, label)
        return label

    def _add_help_menu(window):
        bar = window.menuBar()
        if getattr(window, '_how_menu', None) is not None:
            return
        how = bar.addMenu('Как работает?')
        window._how_menu = how
        act = QAction('Открыть справку и анимацию', window)
        how.addAction(act)

        def show_help():
            dlg = QDialog(window)
            dlg.setWindowTitle('Как работает программа')
            dlg.resize(880, 700)
            lay = QVBoxLayout(dlg)
            tabs = QTabWidget()
            page1 = QTextBrowser()
            page1.setHtml(HTML_HELP)
            tabs.addTab(page1, 'Справка')
            cross = QWidget()
            cl = QVBoxLayout(cross)
            cl.addWidget(QLabel('Анимация движения мелющих тел в поперечном разрезе барабана.'))
            cl.addWidget(HelpAnimationWidget('cross'), 1)
            tabs.addTab(cross, 'Разрез по ширине')
            length = QWidget()
            ll = QVBoxLayout(length)
            ll.addWidget(QLabel('Схема работы мельницы в продольном разрезе: две камеры, поток материала и движение тел.'))
            ll.addWidget(HelpAnimationWidget('length'), 1)
            tabs.addTab(length, 'Разрез по длине')
            lay.addWidget(tabs, 1)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            bb.rejected.connect(dlg.reject)
            bb.accepted.connect(dlg.accept)
            lay.addWidget(bb)
            dlg.exec()
        act.triggered.connect(show_help)

    def _add_export_menu(window):
        bar = window.menuBar()
        if getattr(window, '_export_menu', None) is not None:
            return
        menu = bar.addMenu('Экспорт')
        window._export_menu = menu
        act = QAction('Выбрать данные для экспорта…', window)
        menu.addAction(act)
        act.triggered.connect(lambda: ExportDialog(window).exec())

    def _simulation_page(window):
        page = window.right.tabs.widget(window.sim_tab_index)
        return page.widget() if isinstance(page, QScrollArea) else page

    def _find_run_button(window):
        page = _simulation_page(window)
        for button in page.findChildren(QPushButton):
            t = button.text().lower()
            if 'пуск' in t or 'рассчитать' in t or 'просимулировать' in t:
                return button
        return None

    def _build_segment_ui(window):
        page = _simulation_page(window)
        layout = page.layout()
        # hide planner block: user now works via sequential simulation runs.
        if hasattr(window, '_workspace_plan_toggle'):
            window._workspace_plan_toggle.hide()
        if hasattr(window, '_workspace_planner_scroll'):
            window._workspace_planner_scroll.hide()
        # clearer status area heading.
        window._operator_sim_status_caption = _add_table_caption(
            layout, 'Итог проверки качества и производительности', window.sim_table)
        # simulation journal.
        box = QFrame()
        box.setObjectName('simulation-journal-frame')
        box.setStyleSheet('QFrame#simulation-journal-frame {border:1px solid #375a72; border-radius:6px; background:#12283a;}')
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 8)
        bl.setSpacing(6)
        hdr = QLabel('Журнал симуляций')
        hdr.setStyleSheet('background:#2a4a61; color:#eef4f8; padding:7px 10px; '
                          'border-top-left-radius:5px; border-top-right-radius:5px;')
        bl.addWidget(hdr)
        note = QLabel('Каждый запуск «Пуск» сохраняет номер симуляции, вид цемента, длительность и снимок входных данных.')
        note.setWordWrap(True)
        note.setStyleSheet('padding:0 10px; color:#bcd2de;')
        bl.addWidget(note)
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(['№', 'Вид цемента', 'Длительность', 'Время запуска'])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setMinimumHeight(160)
        table.doubleClicked.connect(lambda *_: _open_current_segment(window))
        bl.addWidget(table)
        open_btn = QPushButton('Открыть выбранную запись')
        open_btn.clicked.connect(lambda *_: _open_current_segment(window))
        bl.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(box)
        window._segment_log_frame = box
        window._segment_table = table
        window._sim_segments = []
        window._segment_capture_requested = False
        # run button hooks
        run_btn = _find_run_button(window)
        if run_btn is not None:
            def mark_capture():
                window._segment_capture_requested = True
                try:
                    window._segment_pending_snapshot = deepcopy(window.collect_config())
                except Exception:
                    window._segment_pending_snapshot = {}
                window._segment_pending_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                window._segment_pending_generation = window._sim_generation
            run_btn.clicked.connect(mark_capture)
            window._segment_run_button = run_btn

    def _refresh_segment_log(window):
        table = getattr(window, '_segment_table', None)
        if table is None:
            return
        data = getattr(window, '_sim_segments', [])
        table.setRowCount(len(data))
        for r, seg in enumerate(data):
            vals = [seg['index'], seg['cement'], seg['duration'], seg['timestamp']]
            for c, val in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem(str(val)))
        table.resizeColumnsToContents()

    def _current_result_for_sim(window):
        combined = _combine_segments(getattr(window, '_sim_segments', []))
        return combined or getattr(window, '_timeline_outcome', None)

    def _open_current_segment(window):
        table = getattr(window, '_segment_table', None)
        if table is None or table.currentRow() < 0:
            return
        idx = table.currentRow()
        segment = window._sim_segments[idx]
        SimulationDetailDialog(segment, window).exec()

    def _plot_simulation(window, result):
        # Use the combined sequential simulations instead of one isolated run.
        combined = _current_result_for_sim(window)
        if not combined or not combined.get('baseline'):
            return
        panel = window.sim_plot
        key = getattr(window, '_workspace_chart_picker', None)
        chart_key = key.currentData() if key is not None else 'sim0'
        if chart_key not in SIM_KEYS:
            chart_key = 'sim0'
        value_key, title, unit = SIM_KEYS[chart_key]
        baseline = combined['baseline']
        x = [float(row.get('hour', 0.0)) for row in baseline]
        panel.figure.clear()
        ax = panel.figure.subplots(1, 1)
        panel.axis(ax, title, ylabel=unit)
        # boundaries between simulation segments
        for seg in getattr(window, '_sim_segments', [])[:-1]:
            boundary = seg.get('_offset_end', 0.0)
            ax.axvline(boundary, color='#dbe6ef', ls='--', lw=1.0, alpha=0.8)
        if value_key == 'chamber_diameters_mm':
            chamber_names = sorted({k for row in baseline for k in row.get('chamber_diameters_mm', {})})
            colors = ('#66cbe1', '#e9ad73', '#95d6ad', '#d4a4ef')
            for i, name in enumerate(chamber_names):
                y = [row.get('chamber_diameters_mm', {}).get(name) for row in baseline]
                ax.plot(x, y, lw=1.7, label=name, color=colors[i % len(colors)])
            ax.legend(loc='upper right', fontsize=8)
        else:
            y = [row.get(value_key) for row in baseline]
            ax.plot(x, y, lw=1.9, color='#e9ad73', label='Суммарная симуляция')
            if chart_key in ('sim0', 'sim1', 'sim2'):
                ymin = [row.get(value_key + '_minimum') for row in baseline]
                ymax = [row.get(value_key + '_maximum') for row in baseline]
                if any(v is not None for v in ymin):
                    ax.plot(x, ymin, lw=1.2, ls='--', color='#ff6b80', label='Мин.')
                if any(v is not None for v in ymax):
                    ax.plot(x, ymax, lw=1.2, ls='--', color='#ff6b80', label='Макс.')
            ax.legend(loc='upper right', fontsize=8)
        ax.set_xlim(0, max(0.01, combined['hours']))
        panel.figure.subplots_adjust(left=.085, right=.97, top=.90, bottom=.18)
        panel.set_time_range(combined['hours'])
        panel._plot_layers.setCurrentWidget(panel.canvas)
        panel.canvas.show()
        panel.canvas.draw_idle()
        if hasattr(window, '_workspace_chart_hint'):
            window._workspace_chart_hint.hide()

    def build(self):
        old_build(self)
        _hide_helper_headings(self)
        _add_help_menu(self)
        _add_export_menu(self)
        _build_segment_ui(self)
        # clearer tab texts, keep essence and remove numeric prefixes.
        for idx, text in ((0, 'Обзор'), (1, 'Контроль помола'), (2, 'Мелющие тела'),
                          (3, 'Рекомендации'), (self.sim_tab_index, 'Симуляция работы'),
                          (self.timeline_editor_index, 'Журнал и история')):
            self.right.tabs.setTabText(idx, text)
            self.right.picker.setItemText(idx, text)
        # make all top-level splitters stretch remaining visible pane.
        for splitter in self.findChildren(QSplitter):
            if splitter.count() >= 2:
                splitter.setStretchFactor(0, 1)
                splitter.setStretchFactor(1, 2)
        # stop using auto text that suggests editable planning.
        if hasattr(self, 'sim_apply'):
            self.sim_apply.setText('Перенести предложенные операции в журнал')
        # drive the simulation view from combined segments.
        self._workspace_change_chart = lambda: _plot_simulation(self, _current_result_for_sim(self))
        workspace_ui._one_sim_chart = lambda window, result: _plot_simulation(window, result)
        workflow_ui._sim_plot = lambda window, result: _plot_simulation(window, result)
        _refresh_segment_log(self)

    def sim_done(self, n, result):
        old_done(self, n, result)
        if n != getattr(self, '_sim_generation', -1):
            return
        if (getattr(self, '_segment_capture_requested', False)
                and n == getattr(self, '_segment_pending_generation', None)):
            snapshot = deepcopy(getattr(self, '_segment_pending_snapshot', {}) or {})
            cement = _infer_cement_name(self, snapshot)
            duration = _infer_duration_text(result)
            segment = {
                'index': len(getattr(self, '_sim_segments', [])) + 1,
                'cement': cement,
                'duration': duration,
                'timestamp': getattr(self, '_segment_pending_timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                'snapshot': snapshot,
                'result': deepcopy(result),
            }
            self._sim_segments.append(segment)
            offset = 0.0
            for seg in self._sim_segments:
                offset += float(seg['result'].get('hours', 0.0) or 0.0)
                seg['_offset_end'] = offset
            self._segment_capture_requested = False
            _refresh_segment_log(self)
        if self.right.tabs.currentIndex() == self.sim_tab_index:
            _plot_simulation(self, _current_result_for_sim(self))

    def sim_fail(self, n, error):
        old_fail(self, n, error)
        if n == getattr(self, '_segment_pending_generation', None):
            self._segment_capture_requested = False

    MillWindow._build = build
    MillWindow._sim_done = sim_done
    MillWindow._sim_fail = sim_fail
