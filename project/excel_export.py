"""Экспорт прогноза Black Box в Excel с диаграммами.

Использует публичную библиотеку XlsxWriter (pip install XlsxWriter),
не требует artifact_tool или доступа к сервисам OpenAI.
"""
from __future__ import annotations

from io import BytesIO
from math import isfinite
from typing import Any

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

from model import initial_cohorts, quality_at, quality_over_time, recommends


def clean(value: Any) -> Any:
    """Корректное Excel-значение без NaN/Inf и сложных типов."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if isfinite(value) else ""
    return str(value)


class Report:
    def __init__(self, workbook):
        self.wb = workbook
        self.header = workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#163A50",
                                           "text_wrap": True, "valign": "vcenter", "border": 0})
        self.title = workbook.add_format({"bold": True, "font_size": 15, "font_color": "#FFFFFF", "bg_color": "#0E2938"})
        self.input = workbook.add_format({"font_color": "#006EA0", "bg_color": "#EAF4FA"})
        self.numeric = workbook.add_format({"num_format": "#,##0.000"})
        self.emphasis = workbook.add_format({"bold": True, "bg_color": "#EAF4FA", "num_format": "#,##0.00"})
        self.link = workbook.add_format({"font_color": "#0563C1", "underline": 1})

    def sheet(self, name: str, rows: list[dict], widths: dict | None = None):
        ws = self.wb.add_worksheet(name)
        ws.freeze_panes(1, 0)
        ws.set_default_row(19)
        if not rows:
            ws.write(0, 0, "Нет данных")
            ws.set_column(0, 0, 22)
            return ws, [], 1
        cols = list(rows[0].keys())
        ws.set_row(0, 31)
        for j, key in enumerate(cols):
            ws.write(0, j, key, self.header)
            width = (widths or {}).get(key, min(31, max(16, len(str(key)) + 3)))
            ws.set_column(j, j, width, self.numeric)
        for i, row in enumerate(rows, start=1):
            for j, key in enumerate(cols):
                v = clean(row.get(key))
                if isinstance(v, bool):
                    ws.write_boolean(i, j, v)
                elif isinstance(v, (float, int)):
                    ws.write_number(i, j, v, self.numeric)
                elif isinstance(v, str) and (v.startswith('https://') or v.startswith('http://')):
                    ws.write_url(i, j, v, self.link, v)
                else:
                    ws.write_string(i, j, v)
        if len(rows) > 1:
            ws.autofilter(0, 0, len(rows), len(cols)-1)
        return ws, cols, len(rows) + 1  # row count including header, 1-indexed end

    def line(self, ws, name: str, x_col: int, traces: list[tuple[int, str]], last: int,
             cell: str = "P2", rows: int = 16, x_label: str = "Наработка, ч", y_label: str = ""):
        if last <= 2 or not traces:
            return
        chart = self.wb.add_chart({"type": "line"})
        sheet = ws.name
        for col, label in traces:
            chart.add_series({
                "name": label,
                "categories": [sheet, 1, x_col, last - 1, x_col],
                "values": [sheet, 1, col, last - 1, col],
                "line": {"width": 2.25},
            })
        chart.set_title({"name": name})
        chart.set_legend({"position": "bottom"})
        chart.set_x_axis({"name": x_label, "major_gridlines": {"visible": False}})
        chart.set_y_axis({"name": y_label, "major_gridlines": {"visible": True,
                                                                     "line": {"color": "#E4EAF0"}}})
        chart.set_size({"width": 680, "height": max(310, rows * 22)})
        chart.set_chartarea({"border": {"none": True}, "fill": {"color": "#FFFFFF"}})
        chart.set_plotarea({"border": {"none": True}})
        ws.insert_chart(cell, chart, {"x_offset": 8, "y_offset": 4})


def export_excel(cfg: dict, run: dict) -> bytes:
    """Готовый .xlsx как bytes; подходит для st.download_button и Python CLI."""
    output = BytesIO()
    wb = xlsxwriter.Workbook(output, {"in_memory": True})
    report = Report(wb)
    try:
        q0 = quality_at(cfg, initial_cohorts(cfg))
        q1 = quality_at(cfg, run["cohorts"])
        recommended = recommends(cfg, run)

        summary = wb.add_worksheet("Сводка")
        summary.hide_gridlines(2)
        summary.merge_range("A1:F1", "BLACK BOX | ЦЕМЕНТНАЯ МЕЛЬНИЦА | ОТЧЁТ", report.title)
        summary.set_row(0, 35)
        summary.write_row("A3", ["Параметр", "Значение", "Пояснение / происхождение"], report.header)
        summary.set_row(2, 30)
        summary.set_column("A:A", 46)
        summary.set_column("B:B", 23)
        summary.set_column("C:C", 69)
        summary.freeze_panes(3, 0)
        inputs = [
            ("Производительность продукта, т/ч", run["throughput"]["product_tph"], "Измеренная / расчётная"),
            ("Внутренний поток через мельницу, т/ч", run["throughput"]["mill_feed_tph"], "При возврате сепаратора"),
            ("Мощность, кВт", sum(m["power_kw"] for m in cfg["mills"]), "Из исходных параметров приводов"),
            ("Удельная энергия, кВт·ч/т", run["throughput"]["operating_specific_energy"], "Мощность / продукт"),
            ("Наработка, ч", cfg["horizon_h"], "Состояние на конец горизонта"),
            ("Базовый износ, г/т", cfg["wear_g_t"], "КАЛИБРОВОЧНЫЙ параметр, не заводское измерение"),
            ("Показатель закона износа Δ", cfg["delta"], "0 — поверхность; 1 — модель d³"),
            ("Относительная абразивность", cfg["abrasion_factor"], "Нужна калибровка на данных предприятия"),
            ("Масса исходной загрузки, т", run["initial_media_t"], "По размерам и загрузке"),
            ("Потеря массы за период, т", run["total_wear_t"], "Результат численной интеграции"),
            ("R0.08 в начале, %", q0["r008"], "Модель, не лабораторное измерение"),
            ("R0.08 в конце, %", q1["r008"], "Модель, не лабораторное измерение"),
            ("R0.045 в конце, %", q1["r0045"], "Модель, не лабораторное измерение"),
            ("Блейн-прокси, см²/г", q1["blaine_proxy"], "Эмпирический индикатор, не лабораторное измерение"),
        ]
        for idx, (name, value, note) in enumerate(inputs, 3):
            summary.write_string(idx, 0, name)
            summary.write_number(idx, 1, float(value), report.input)
            summary.write_string(idx, 2, note)
        base = 3 + len(inputs) + 2
        summary.write_string(base, 0, "Расчётный удельный расход по периоду, г/т")
        # 0-based: B4 -> выпуск Q, B8 -> наработка, B13 -> масса износа, т
        summary.write_formula(base, 1, "=IFERROR(B13*1000000/(B4*B8),0)", report.emphasis)
        summary.merge_range(base + 2, 0, base + 2, 5,
                            "Примечание: прогнозные графики — результаты расчёта, не данные АСУ ТП.")
        summary.set_row(base + 2, 29)

        hist = run["rows"]
        wsh, wcols, wend = report.sheet("Износ_во_времени", hist,
            {"hours": 17, "production_t": 19, "loss_t": 16, "total_media_t": 20})
        report.line(wsh, "Кумулятивная потеря массы, т", 0, [(2, "Износ, т")], wend,
                    "P2", y_label="т")
        report.line(wsh, "Масса мелющих тел, т", 0, [(3, "Остаток, т")], wend,
                    "P21", y_label="т")
        rate_idx = len(wcols)
        wsh.write(0, rate_idx, "Удельный расход интервала, г/т", report.header)
        wsh.set_column(rate_idx, rate_idx, 31, report.numeric)
        for excel_row in range(3, wend + 1):
            wsh.write_formula(excel_row-1, rate_idx,
                f"=IFERROR((C{excel_row}-C{excel_row-1})*1000000/(B{excel_row}-B{excel_row-1}),0)",
                report.numeric)
        report.line(wsh, "Удельный расход по шагам, г/т", 0,
                    [(rate_idx, "г/т")], wend, "P40", y_label="г/т")

        diam = run.get("diameter_history", [])
        if diam:
            sh, cols, n = report.sheet("Диаметры_во_времени", diam)
            report.line(sh, "Уменьшение диаметра по фракциям, мм", 0,
                        [(i, cols[i]) for i in range(1, min(len(cols), 5))], n,
                        "Q2", y_label="мм")
        fractions = run.get("fraction_mass_history", [])
        if fractions:
            sh, cols, n = report.sheet("Масса_фракций_по_времени", fractions)
            report.line(sh, "Масса отдельных фракций, т", 0,
                        [(i, cols[i]) for i in range(1, min(len(cols), 5))], n,
                        "Q2", y_label="т")
        coeff = run.get("coefficient_history", [])
        if coeff:
            sh, cols, n = report.sheet("Износ_по_фракциям_г_т", coeff)
            report.line(sh, "Удельный износ отдельных фракций, г/т", 0,
                        [(i, cols[i]) for i in range(1, min(len(cols), 5))], n,
                        "Q2", y_label="г/т")
            if "Вся загрузка, г/т" in cols:
                report.line(sh, "Суммарный расход мелющих тел, г/т", 0,
                    [(cols.index("Вся загрузка, г/т"), "Суммарно")], n, "Q22", y_label="г/т")

        report.sheet("Фракции_износ", run["cohort_results"])
        report.sheet("Догрузка", recommended or [{"Состояние": "Догрузка пока не требуется"}])

        quality = quality_over_time(cfg, run)
        sh, cols, n = report.sheet("Тонкость_во_времени", quality)
        if n > 2:
            report.line(sh, "Полные остатки во времени, %", 0,
                [(1, "R0.08"), (2, "R0.045")], n, "F2", y_label="%")

        probes = q1["samples"]
        sh, cols, n = report.sheet("Диаграмма_помола", probes)
        if n > 2:
            x = cols.index("Расстояние по камерам, м") if "Расстояние по камерам, м" in cols else 1
            series = [(cols.index(label), label) for label in ("R0.08, %", "R0.045, %") if label in cols]
            report.line(sh, "Полные остатки по длине камер", x, series, n,
                        "N2", x_label="Расстояние, м", y_label="%")

        geometry = []
        for drum, mill in enumerate(cfg["mills"], 1):
            for chamber, ch in enumerate(mill["chambers"], 1):
                geometry.append({"Барабан": drum, "Название": mill["name"],
                                 "Диаметр, м": mill["diameter_m"],
                                 "Длина барабана, м": mill["length_m"],
                                 "Камера": chamber, "Длина камеры, м": ch["length_m"],
                                 "Обороты, об/мин": mill["rpm"],
                                 "Мощность, кВт": mill["power_kw"]})
        report.sheet("Геометрия", geometry)
        sources = [
            {"Раздел": "Закон износа", "Источник": "Austin & Klimpel, Powder Technology (1985)", "URL": "https://www.sciencedirect.com/science/article/pii/0032591085800267"},
            {"Раздел": "Износ цементной мельницы", "Источник": "Çolak et al., Powder Technology (2018)", "URL": "https://www.sciencedirect.com/science/article/pii/S0032591017309130"},
            {"Раздел": "GMCR, г/т", "Источник": "FLSmidth KPI handbook", "URL": "https://www.cementbook.com/downloads/tech/gen/fls_kpi_handbook.pdf"},
            {"Раздел": "Удельная энергия", "Источник": "SMC Testing / GMG", "URL": "https://www.smctesting.com/about/publications?file=publication_file&id=197&task=download"},
            {"Раздел": "Параметры АСУ ТП", "Источник": "Industrial cement mill dataset (2025)", "URL": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12117027/"},
            {"Раздел": "Осевой тест", "Источник": "Cement Mill Axial Test", "URL": "https://www.thecementgrindingoffice.com/Preview.pdf"},
        ]
        report.sheet("Источники", sources, {"URL": 70, "Источник": 47})
    finally:
        wb.close()
    return output.getvalue()
