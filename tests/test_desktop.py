"""Валидация пользовательских данных не зависит от Qt и выполняется без дисплея."""
import json
from pathlib import Path

import pytest
from calibration import parse_history_csv
from model import default_config, simulate_wear
from ui_data import (
    FIELDS, MODES, MEDIA_FIELDS, is_valid_input,
    default_table_row, row_from_cells, clinker_from_csv, merge_lab_parameters,
)

ROOT = Path(__file__).resolve().parents[1]


def test_default_two_chamber():
    cfg = default_config()
    assert is_valid_input(cfg)
    assert len(cfg['mills']) == 1 and len(cfg['mills'][0]['chambers']) == 2
    assert simulate_wear(cfg)['total_wear_t'] > 0


def test_one_chamber_import():
    cfg = json.loads((ROOT / 'examples/one_chamber_input.json').read_text())
    assert is_valid_input(cfg)
    assert len(cfg['mills'][0]['chambers']) == 1


def test_history_csv():
    # Файл истории сохраняется в проекте как импортируемый пример, не отдельная программа.
    file = ROOT / 'examples/history_input.csv'
    if file.exists():
        assert len(parse_history_csv(file.read_bytes())) == 3


def test_clinker_is_not_operator_field():
    fields = [key for group in FIELDS.values() for key, *_ in group]
    for k in ('work_index_kwh_t','f80_um','p80_um','feed_fraction','wear_g_t','grindability'):
        assert k not in fields
    assert MODES == ['Измеренная подача, т/ч', 'Масса / время']
    assert 'diameter_mm' in [k for k, _ in MEDIA_FIELDS]


def test_default_inline_reload_with_valid_values():
    cfg = default_config()
    cfg.setdefault('manual_reloads', [])
    reload = default_table_row('manual_reloads', cfg)
    assert reload['drum'] == 1
    assert reload['tons'] == .5
    cfg['manual_reloads'] = [reload]
    assert is_valid_input(cfg)


def test_default_schedule_row():
    cfg = default_config()
    cfg['throughput_schedule'] = []
    row = default_table_row('throughput_schedule', cfg)
    assert row['tph'] == cfg['fresh_feed_tph']
    cfg['throughput_schedule'].append(row)
    assert is_valid_input(cfg)


def test_row_numeric_validation():
    with pytest.raises(ValueError, match='конечным'):
        row_from_cells('manual_reloads', {
            'chamber':'2','type':'Цильпебс','material':'Сталь','hour':'NaN',
            'diameter_mm':'30','tons':'1','aspect':'1'
        })


def test_lab_import_and_clinker_input():
    file = ROOT / 'examples/clinker_fractions.csv'
    if file.exists():
        parts = clinker_from_csv(file.read_bytes())
        assert len(parts) == 10
        assert 99 <= sum(parts) <= 101
    cfg = default_config()
    cfg2 = merge_lab_parameters(cfg, {'grindability':1.1, 'abrasion_factor':1.02})
    assert cfg2['grindability'] == pytest.approx(1.1)
    assert cfg['grindability'] != 1.1
