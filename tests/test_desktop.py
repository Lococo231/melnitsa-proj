"""Проверка настольного приложения и импорта, без запуска GUI."""
import json
from pathlib import Path
from desktop_app import is_valid_input, FIELDS, MEDIA_FIELDS, MODES
from calibration import parse_history_csv
from model import simulate_wear
ROOT=Path(__file__).resolve().parents[1]

def test_two_chamber_example():
    c=json.loads((ROOT/'examples/mill3_input.json').read_text())
    assert is_valid_input(c)
    assert len(c['mills'])==1 and len(c['mills'][0]['chambers'])==2
    assert simulate_wear(c)['total_wear_t']>0

def test_one_chamber_example():
    c=json.loads((ROOT/'examples/one_chamber_input.json').read_text())
    assert is_valid_input(c) and len(c['mills'][0]['chambers'])==1
    assert all(r['chamber']==1 for r in c['media'])

def test_history_import_example():
    assert len(parse_history_csv((ROOT/'examples/history_input.csv').read_bytes()))==3

def test_clinker_not_user_controlled():
    fields=[key for group in FIELDS.values() for key,*_ in group]
    for key in ('work_index_kwh_t','f80_um','p80_um','feed_fraction','wear_g_t','grindability'):
        assert key not in fields
    assert MODES==['Измеренная подача, т/ч','Масса / время']
    assert 'diameter_mm' in [key for key,_ in MEDIA_FIELDS]

def test_imported_clinker_csv_example():
    import csv
    with (ROOT/'examples/clinker_fractions.csv').open() as f: rows=list(csv.DictReader(f))
    assert len(rows)==10
    assert 99 <= sum(float(r['percent']) for r in rows) <= 101
