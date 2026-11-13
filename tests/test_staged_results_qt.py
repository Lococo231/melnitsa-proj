"""Локальные Qt-тесты этапных вкладок. GitHub Actions не используется."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QHeaderView
from qt_app import MillWindow


def make_window():
    app = QApplication.instance() or QApplication([])
    window = MillWindow()
    window._sim_timer.stop()
    window._timer.stop()
    return app, window


def test_right_tabs_are_grouped_by_process_stage():
    app, window = make_window()
    try:
        assert window.right.tabs.tabText(1) == "Контроль помола"
        assert window.right.tabs.tabText(2) == "Мелющие тела"
        assert not window.right.tabs.isTabVisible(4)
        assert not window.right.tabs.isTabVisible(7)
        assert window.right.tabs.widget(1).findChild(type(window._grind_stages),
                                                      "stage-switcher") is window._grind_stages
        assert window._grind_stages.widget(0) is window.quality_plot
        assert window._grind_stages.widget(1).findChild(
            type(window.sample_table)) is window.sample_table
        assert window._media_stages.widget(0).findChild(
            type(window.start_plot)) is window.start_plot
        assert window._media_stages.widget(1).findChild(
            type(window.fraction_plot)) is window.fraction_plot
        assert window._grind_stages.tabText(0).startswith("1.")
        assert window._media_stages.tabText(0).startswith("1.")
    finally:
        window._sim_timer.stop()
        window._timer.stop()
        window.close()
        app.processEvents()


def test_sample_columns_have_values_and_no_giant_last_column():
    app, window = make_window()
    try:
        window.right.tabs.setCurrentIndex(1)
        window._grind_stages.setCurrentIndex(1)
        window._refresh_grinding_stages()
        table = window.sample_table
        assert table.rowCount() > 0
        assert table.columnCount() >= 5
        assert not table.horizontalHeader().stretchLastSection()
        assert table.horizontalHeader().sectionResizeMode(table.columnCount() - 1) == (
            QHeaderView.ResizeMode.Stretch
        )
        headers = [table.horizontalHeaderItem(i).text()
                   for i in range(table.columnCount())]
        assert "R0,045, %" in headers  # display only, model retains dot keys
        last = table.item(0, table.columnCount()-1)
        assert last is not None
        assert last.text().strip() != ""
        float(last.text().replace(",", "."))
    finally:
        window._sim_timer.stop()
        window._timer.stop()
        window.close()
        app.processEvents()


def test_switching_group_stages_keeps_simulation_and_journal_usable():
    app, window = make_window()
    try:
        for index, stage in ((1, 0), (1, 1), (2, 0), (2, 1)):
            window.right.tabs.setCurrentIndex(index)
            widget = window._grind_stages if index == 1 else window._media_stages
            widget.setCurrentIndex(stage)
            window._render_active()
        window.right.tabs.setCurrentIndex(window.sim_tab_index)
        window._render_active()
        window.right.tabs.setCurrentIndex(window.timeline_editor_index)
        window._render_active()
        assert window._workspace_ui_built
    finally:
        window._sim_timer.stop()
        window._timer.stop()
        window.close()
        app.processEvents()
