"""Импорт примеров не запускает сторонние приложения или веб-сервер."""
import json
from pathlib import Path
from desktop_app import is_valid_input, FIELDS, MEDIA_FIELDS
from calibration import parse_history_csv
from model import simulate_wear, recommends

ROOT = Path(__file__).resolve().parents[1]


def test_mill3_example_json():
    config=json.loads((ROOT/'examples'/'mill3_input.json').read_text())
    assert is_valid_input(config)
    result=simulate_wear(config)
    assert result['total_wear_t']>0
    assert recommends(config,result)


def test_two_drums_example_json():
    config=json.loads((ROOT/'examples'/'two_drums_input.json').read_text())
    assert is_valid_input(config)
    assert len(config['mills'])==2
    assert any(row['drum']==2 for row in config['media'])


def test_history_import_example():
    data=(ROOT/'examples'/'history_input.csv').read_bytes()
    assert len(parse_history_csv(data))==3


def test_all_wear_coefficients_editable():
    fields=[key for group in FIELDS.values() for key,*_ in group]
    for key in ['wear_g_t','delta','power_exponent','speed_exponent',
                'loading_exponent','feed_coarseness_exponent','hardness_exponent']:
        assert key in fields
    assert 'diameter_mm' in [key for key,_ in MEDIA_FIELDS]
