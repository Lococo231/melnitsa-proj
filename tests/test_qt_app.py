"""Локальные smoke-тесты GUI PySide6 в headless-режиме."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from qt_app import MillWindow, AdaptiveTabs


def test_window_renders_and_calculates():
    app = QApplication.instance() or QApplication([])
    window = MillWindow()
    try:
        assert window.windowTitle() == 'Цементная мельница'
        assert isinstance(window.left, AdaptiveTabs)
        assert len(window.collect_config()['mills']) == 1
        assert window.run_data is not None
        assert window.quality_data is not None
        # После запуска открыта «Симуляция смен» — скрытый «Обзор» лениво
        # строится только при переходе на него.
        assert not window.overview_plot.figure.axes
        window.right.setCurrentIndex(0)
        window._render_active()
        assert len(window.overview_plot.figure.axes) == 6
    finally:
        window.close()
        app.processEvents()


def test_reload_in_table_without_dialog():
    app = QApplication.instance() or QApplication([])
    window = MillWindow()
    try:
        before = window.tables['manual_reloads'].rowCount()
        window.add_row('manual_reloads')
        assert window.tables['manual_reloads'].rowCount() == before + 1
        last = window.tables['manual_reloads'].rowCount()-1
        assert window.tables['manual_reloads'].item(last,5).text() == '0.5'
        window.calculate(quiet=True)
        assert window.run_data is not None
        assert len(window.run_data['reload_events']) >= 1
    finally:
        window.close()
        app.processEvents()


def test_sieve_and_feed_schedule_update_model():
    app = QApplication.instance() or QApplication([])
    window = MillWindow()
    try:
        before = len(window.collect_config()['sieves_mm'])
        window.new_sieve.setValue(.11)
        window.add_sieve()
        assert len(window.collect_config()['sieves_mm']) == before + 1
        window.add_row('throughput_schedule')
        assert window.tables['throughput_schedule'].rowCount() == 1
        window.tables['throughput_schedule'].item(0, 1).setText('65')
        window.calculate(quiet=True)
        assert window.run_data is not None
        assert window.collect_config()['throughput_schedule'][0]['tph'] == 65
        window.right.setCurrentIndex(0)
        window._render_active()
        assert len(window.overview_plot.figure.axes) == 6
    finally:
        window.close()
        app.processEvents()


def test_chamber_count_and_adaptive_tabs():
    app = QApplication.instance() or QApplication([])
    window = MillWindow()
    try:
        window.geometry_fields['chcount'].setCurrentText('1')
        assert len(window.collect_config()['mills'][0]['chambers']) == 1
        assert all(r['chamber'] == 1 for r in window.collect_config()['media'])
        window.left.resize(330, 500)
        app.processEvents()
        assert window.left.picker.isVisible() or not window.left.isVisible()
    finally:
        window.close()
        app.processEvents()


def test_menu_lifetime_after_extensions():
    """Меню должны существовать и после построения расширений окна."""
    app = QApplication.instance() or QApplication([])
    window = MillWindow()
    try:
        titles = [action.text() for action in window.file_menu.actions()]
        assert any('Импорт грансостава клинкера' in name for name in titles)
        assert any('Экспорт отчёта Excel' in name for name in titles)
        assert window.file_menu.title() == 'Файл'
        assert window.model_menu.title() == 'Модель'
        assert window.model_menu.actions()
    finally:
        window.close()
        app.processEvents()
