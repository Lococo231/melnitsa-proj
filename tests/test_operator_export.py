"""Unit checks for selective export; these run without PySide6 or a Windows GUI."""
import json
import sys
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'project'))

from operator_export import save_selected_export


def fixture_payload():
    return {
        'created_at': '2026-11-14T03:00:00',
        'selected': ['segments', 'segment_details', 'sim_status'],
        'segments': [
            {'index': 1, 'cement': 'ЦЕМ I 42,5Н', 'duration': '40 ч', 'timestamp': '14.11.2026'},
        ],
        'segment_details': [
            {'index': 1, 'snapshot': {'rpm': 16, 'media': [{'chamber': 1, 'tons': 3.7}]}},
        ],
        'sim_status': [
            {'Результат проверки': 'В пределах целей'},
            {'Результат проверки': '=HYPERLINK("https://evil.example")'},
        ],
    }


def test_json_selected_export_keeps_nested_snapshot(tmp_path):
    path = tmp_path / 'selected.json'
    save_selected_export(fixture_payload(), path)
    loaded = json.loads(path.read_text('utf-8'))
    assert loaded['segment_details'][0]['snapshot']['media'][0]['tons'] == 3.7
    assert 'current_config' not in loaded


def test_xlsx_selected_export_sections_and_safe_text(tmp_path):
    path = tmp_path / 'selected.xlsx'
    save_selected_export(fixture_payload(), path)
    assert path.stat().st_size > 1000
    with ZipFile(path) as z:
        ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        root = ET.fromstring(z.read('xl/workbook.xml'))
        names = {e.attrib['name'] for e in root.findall('.//x:sheet', ns)}
        assert names == {'Сводка', 'Журнал симуляций', 'Результат режима', 'Симуляция 1'}
        shared = z.read('xl/sharedStrings.xml').decode('utf-8')
        assert 'HYPERLINK' in shared
        assert 'media' in shared  # nested snapshot was not dropped
        xmls = [name for name in z.namelist() if name.startswith('xl/worksheets/sheet')]
        assert all(b'<f>' not in z.read(name) for name in xmls)


def test_unsupported_format(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        save_selected_export(fixture_payload(), tmp_path / 'file.csv')
