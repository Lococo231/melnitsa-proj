"""Локальные проверки хронологии. GitHub Actions в проекте отключён."""
from copy import deepcopy

import pytest

from model import default_config
from operation_timeline import simulate_operation_timeline


def example():
    cfg = default_config()
    cfg.update(simulation_days=3, simulation_hours_per_day=3., horizon_h=9.,
               step_h=1., cement_profile='ЦЕМ I 42,5Н')
    return cfg


def test_cement_switch_changes_relevant_bounds_at_exact_hour():
    cfg = example()
    cfg['cement_events'] = [{'hour': 3., 'profile': 'ЦЕМ I 42,5Б'}]
    original = deepcopy(cfg)
    result = simulate_operation_timeline(cfg, optimize=False, observations=9)
    assert cfg == original
    before = next(row for row in result['baseline'] if row['hour'] == 2.)
    after = next(row for row in result['baseline'] if row['hour'] == 3.)
    assert before['profile'] == 'ЦЕМ I 42,5Н'
    assert after['profile'] == 'ЦЕМ I 42,5Б'
    assert before['r008_maximum'] == 2.0
    assert after['r008_maximum'] == 1.5
    assert len(result['cement_changes']) == 3
    assert all(row['Час наработки']==3 for row in result['cement_changes'])


def test_actual_addition_changes_mass_and_integer_piece_count():
    cfg = example()
    cfg['media_events']=[{'hour':3.,'direction':'add','tons':7.0,
                           'target':{'chamber':1,'type':'Шары','material':'Сталь',
                                     'diameter_mm':70.,'aspect':1.}}]
    result = simulate_operation_timeline(cfg,optimize=False,observations=9)
    before = next(row for row in result['baseline'] if row['hour']==2.)
    after = next(row for row in result['baseline'] if row['hour']==3.)
    assert after['media_mass_t'] - before['media_mass_t'] > 6.9
    assert isinstance(after['piece_count'],int)
    record=result['media_changes'][0]
    assert record['Изменение, шт'] > 0
    assert isinstance(record['Изменение, шт'],int)
    assert record['Изменение, т'] == pytest.approx(record['Стало, т'] - record['Было, т'])


def test_removal_is_whole_and_does_not_break_future_wear():
    cfg=example()
    cfg['media_events']=[{'hour':1.,'direction':'remove','tons':1.0,
                           'target':{'chamber':1,'type':'Шары','material':'Сталь',
                                     'diameter_mm':80.,'aspect':1.}}]
    result=simulate_operation_timeline(cfg,optimize=False,observations=9)
    assert result['media_changes'][0]['Изменение, шт'] < 0
    assert isinstance(result['baseline'][-1]['piece_count'],int)
    assert result['baseline'][-1]['hour'] == 9.


def test_operating_parameter_switch_affects_future_state():
    cfg=example()
    cfg['parameter_events'] = [{'hour': 3., 'parameter': 'rpm', 'value': 18.},
                               {'hour': 6., 'parameter': 'diameter_m', 'value': 3.95}]
    result=simulate_operation_timeline(cfg,optimize=False,observations=9)
    r0=next(row for row in result['baseline'] if row['hour']==2.)
    r1=next(row for row in result['baseline'] if row['hour']==3.)
    r2=next(row for row in result['baseline'] if row['hour']==6.)
    assert r0['rpm']==16
    assert r1['rpm']==18
    assert r2['diameter_m']==3.95
    assert result['parameter_changes'][1]['Было']==4.0


def test_rejects_events_out_of_shift_horizon():
    cfg=example()
    cfg['cement_events']=[{'hour':10.,'profile':'ЦЕМ I 42,5Б'}]
    with pytest.raises(ValueError,match='час изменения'):
        simulate_operation_timeline(cfg,optimize=False)


def test_20_days_then_switch_cement_on_day_21():
    cfg = example()
    cfg.update(simulation_days=22, simulation_hours_per_day=8.,
               horizon_h=176., step_h=4.)
    cfg['cement_events'] = [{'hour': 160., 'profile': 'ЦЕМ I 42,5Б'}]
    result = simulate_operation_timeline(cfg, optimize=False, observations=50)
    old = max((r for r in result['baseline'] if r['hour'] < 160),
              key=lambda r:r['hour'])
    new = next(r for r in result['baseline'] if r['hour'] == 160.)
    assert old['profile'] == 'ЦЕМ I 42,5Н'
    assert new['profile'] == 'ЦЕМ I 42,5Б'
    assert result['cement_changes'][0]['Час наработки'] == 160.
    assert result['baseline'][-1]['hour'] == 176.


def test_existing_reload_journal_is_in_history_and_mass_graph():
    cfg = example()
    cfg['manual_reloads']=[{
        'hour':3.,'tons':1.,'drum':1,'chamber':1,'type':'Шары',
        'material':'Сталь','diameter_mm':70.,'aspect':1.}]
    result = simulate_operation_timeline(cfg,optimize=False,observations=9)
    entries=[e for e in result['media_changes']
             if e['Операция']=='Догрузка из общего журнала']
    assert len(entries)==1
    assert entries[0]['Изменение, шт']>0
    assert entries[0]['Изменение, т']>0
    assert isinstance(entries[0]['Изменение, шт'],int)