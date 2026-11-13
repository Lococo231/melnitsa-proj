"""Stage-oriented right-hand results for the cement mill (PySide6).

Loaded after workspace_ui. The existing result widgets are *moved*, not
duplicated, into two groups. Outer QTabWidget indices remain stable because
hidden placeholders replace obsolete tabs; existing background callbacks keep
working.

Stage 1 (Контроль помола): diagram -> sieve sample table.
Stage 2 (Мелющие тела): starting load -> wear by fraction.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSignalBlocker, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QLabel, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)

import production_ui
from production_planning import starting_media
from workspace_ui import _visible_page

GRIND_INDEX = 1
MEDIA_INDEX = 2
OLD_SAMPLE_INDEX = 4
OLD_START_INDEX = 7


def _section(title: str, explanation: str):
    panel = QWidget()
    panel.setObjectName("results-stage-page")
    panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(6, 8, 6, 6)
    layout.setSpacing(8)
    title_label = QLabel(f"<b>{title}</b> — {explanation}")
    title_label.setWordWrap(True)
    title_label.setStyleSheet(
        "color:#b8d6e7; background:#1b3447; padding:9px 12px;"
        "border-left:3px solid #e0bd68; border-radius:4px;"
    )
    layout.addWidget(title_label)
    return panel, layout


def _nested_tabs():
    tabs = QTabWidget()
    tabs.setDocumentMode(True)
    tabs.setObjectName("stage-switcher")
    tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    tabs.tabBar().setExpanding(False)
    tabs.setStyleSheet(
        "QTabWidget#stage-switcher::pane {border:1px solid #31526a;}"
        "QTabBar::tab:selected {color:#ffe08c;}"
    )
    return tabs


def _format_sample_table(table):
    """Keep sieve columns balanced. Never stretch only the last column.

    Important: `R0,045` was actually present in the screenshot; its value
    appeared at the left edge of a very wide last column.
    """
    table.setWordWrap(False)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(
        QAbstractItemView.ScrollMode.ScrollPerPixel
    )
    table.setAlternatingRowColors(True)
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(77)
    header.setDefaultAlignment(
        Qt.AlignmentFlag.AlignCenter
    )

    # The short identity columns are sized explicitly. All sieve values share
    # the remaining width, with minimum width and scrolling on narrow windows.
    for index in range(table.columnCount()):
        if index < 3:
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
        else:
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
    for index, width in enumerate((77, 170, 77)):
        if index < table.columnCount():
            header.resizeSection(index, width)
    # The display labels may use a comma, but the model's dictionary keys
    # still use a dot and must not be modified.
    for index in range(3, table.columnCount()):
        item = table.horizontalHeaderItem(index)
        if item is not None:
            item.setText(item.text().replace(".", ","))

    for row in range(table.rowCount()):
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is not None:
                align = (Qt.AlignmentFlag.AlignRight
                         if column not in (0, 2)
                         else Qt.AlignmentFlag.AlignCenter)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter | align
                )


def _format_load_table(table):
    """Disable the oversized last section in the starting-load table."""
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(85)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for index in range(table.columnCount()):
        table.resizeColumnToContents(index)
        header.resizeSection(index, min(240, max(95, header.sectionSize(index))))
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)


def _sync_outer_navigation(window):
    adaptive = window.right
    bar = adaptive.tabs.tabBar()
    required = sum(
        bar.tabSizeHint(i).width()
        for i in range(bar.count())
        if adaptive.tabs.isTabVisible(i)
    ) + 25
    compact = adaptive.width() < required
    bar.setVisible(not compact)
    adaptive.picker.setVisible(compact)


def install(MillWindow):
    """Install after workspace_ui, once, before main() creates a window."""
    if getattr(MillWindow, "_staged_results_installed", False):
        return
    MillWindow._staged_results_installed = True
    old_build = MillWindow._build
    old_render = MillWindow._render_active
    old_done = MillWindow._sim_done

    def _refresh_quality(window):
        if not hasattr(window, "_grind_stages"):
            return
        payload = getattr(window, "_active_payload", None)
        if payload is None:
            return
        cfg, _run, quality, _recommendation = payload
        if window._grind_stages.currentIndex() == 0:
            production_ui._plot_quality(window, cfg, quality)
        else:
            cols = (
                ["Точка", "Расстояние по камерам, м", "Камера"]
                + [f"R{s:g}, %" for s in cfg["sieves_mm"]]
            )
            window._populate_result(window.sample_table, quality["samples"], cols)
            _format_sample_table(window.sample_table)

    def _refresh_media(window):
        if not hasattr(window, "_media_stages"):
            return
        payload = getattr(window, "_active_payload", None)
        if window._media_stages.currentIndex() == 0:
            if payload is None:
                return
            cfg, _run, _quality, _recommendation = payload
            production_ui._plot_start(window, cfg)
            items = starting_media(cfg)
            window._populate_result(
                window.start_table, items,
                list(items[0]) if items else []
            )
            _format_load_table(window.start_table)
        else:
            # Legacy fraction selectors were populated by the old root tab 2
            # rendering handler. That handler is bypassed by the grouped page,
            # so update the chamber choices here before drawing.
            cfg = payload[0] if payload is not None else window.config_data
            chamber_count = len(cfg['mills'][0]['chambers'])
            options = ['Все камеры'] + [f'Б1К{i}' for i in range(1, chamber_count + 1)]
            with QSignalBlocker(window.fraction_combo):
                previous = window.fraction_combo.currentText()
                if (window.fraction_combo.count() != len(options) or
                        any(window.fraction_combo.itemText(i) != name
                            for i, name in enumerate(options))):
                    window.fraction_combo.clear()
                    window.fraction_combo.addItems(options)
                    window.fraction_combo.setCurrentText(
                        previous if previous in options else 'Все камеры'
                    )
            # _draw_fractions delegates to the timeline-aware and multicore
            # implementation when the current timeline is available.
            if getattr(window, "_sim_dirty", False) and not window._loading:
                timer = getattr(window, "_sim_timer", None)
                if timer is not None and not timer.isActive():
                    timer.start()
            window._draw_fractions()

    def build(window):
        # Signals can be emitted while QTabWidget pages are being reparented.
        window._staged_results_ready = False
        old_build(window)
        tabs = window.right.tabs
        picker = window.right.picker
        selected = tabs.currentIndex()
        indices = (GRIND_INDEX, MEDIA_INDEX, OLD_SAMPLE_INDEX, OLD_START_INDEX)
        old_pages = {i: tabs.widget(i) for i in indices}
        if any(w is None for w in old_pages.values()):
            raise RuntimeError("Не найдены исходные страницы результатов")

        grind_page, grind_layout = _section(
            "Контроль помола",
            "сначала диаграмма по длине мельницы, затем числовые данные проб."
        )
        media_page, media_layout = _section(
            "Мелющие тела",
            "этап 1 — исходная загрузка; этап 2 — износ и изменение фракций."
        )
        window._grind_stages = _nested_tabs()
        window._media_stages = _nested_tabs()
        grind_layout.addWidget(window._grind_stages, 1)
        media_layout.addWidget(window._media_stages, 1)

        replacements = {
            GRIND_INDEX: (grind_page, "Контроль помола"),
            MEDIA_INDEX: (media_page, "Мелющие тела"),
            OLD_SAMPLE_INDEX: (QWidget(), "Таблица проб — внутри контроля"),
            OLD_START_INDEX: (QWidget(), "Начальная загрузка — внутри тел"),
        }
        with QSignalBlocker(tabs), QSignalBlocker(picker):
            # Remove and reinsert at EXACTLY the same index: all old callbacks
            # using numeric positions continue to refer to the same section.
            for i in sorted(indices):
                replacement, caption = replacements[i]
                tabs.removeTab(i)
                tabs.insertTab(i, replacement, caption)
                picker.setItemText(i, caption)
            # Qt guarantees removeTab() does not delete the former page.
            window._grind_stages.addTab(old_pages[GRIND_INDEX], "1. Диаграмма помола")
            window._grind_stages.addTab(old_pages[OLD_SAMPLE_INDEX], "2. Таблица проб")
            window._media_stages.addTab(old_pages[OLD_START_INDEX], "1. Начальная загрузка")
            window._media_stages.addTab(old_pages[MEDIA_INDEX], "2. Износ фракций")
            _visible_page(window.right, OLD_SAMPLE_INDEX, False)
            _visible_page(window.right, OLD_START_INDEX, False)
            tabs.setCurrentIndex(selected)
            picker.setCurrentIndex(selected)

        # Remember indexes for code, tests, and saved navigation.
        window._grind_section_index = GRIND_INDEX
        window._media_section_index = MEDIA_INDEX
        window._grind_stages.currentChanged.connect(
            lambda _=None: window._refresh_grinding_stages()
        )
        window._media_stages.currentChanged.connect(
            lambda _=None: window._refresh_media_stages()
        )
        # With 4 obsolete tabs hidden, the outer bar may fit again.
        window.left.setMinimumWidth(380)
        window._staged_results_ready = True
        QTimer.singleShot(0, lambda: _sync_outer_navigation(window))

    def render_active(window):
        if not getattr(window, "_staged_results_ready", False):
            return old_render(window)
        current = window.right.tabs.currentIndex()
        if current == GRIND_INDEX:
            window._refresh_grinding_stages()
            return
        if current == MEDIA_INDEX:
            window._refresh_media_stages()
            return
        return old_render(window)

    def done(window, generation, result):
        old_done(window, generation, result)
        if not getattr(window, "_staged_results_ready", False):
            return
        if generation != getattr(window, "_sim_generation", -1):
            return
        current = window.right.tabs.currentIndex()
        if current == GRIND_INDEX:
            window._refresh_grinding_stages()
        elif current == MEDIA_INDEX:
            window._refresh_media_stages()

    MillWindow._build = build
    MillWindow._render_active = render_active
    MillWindow._sim_done = done
    MillWindow._refresh_grinding_stages = _refresh_quality
    MillWindow._refresh_media_stages = _refresh_media
