"""Регрессионная проверка экспорта без закрытых зависимостей."""
from io import BytesIO
from zipfile import ZipFile

from model import default_config, simulate_wear
from excel_export import export_excel


def test_excel_export_has_data_and_charts():
    config = default_config()
    result = simulate_wear(config)
    content = export_excel(config, result)
    assert content.startswith(b"PK")
    with ZipFile(BytesIO(content)) as archive:
        files = archive.namelist()
        charts = [name for name in files if name.startswith("xl/charts/chart") and name.endswith(".xml")]
        sheets = [name for name in files if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")]
        assert len(charts) == 9
        assert len(sheets) == 11
        assert b"F80" in archive.read("xl/sharedStrings.xml")
        assert b"P80" in archive.read("xl/sharedStrings.xml")
