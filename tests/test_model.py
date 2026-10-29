import math
import pytest
from model import (default_config, simulate_wear, recommends, throughput,
                   quality_at, initial_cohorts, volume_m3, mass_kg, surface_m2,
                   size_at_pass_percent, operating_bond_index)
from calibration import parse_history_csv, summarize_history, DEMO_CSV


def test_mass_balance_wo_reload():
    c=default_config();r=simulate_wear(c)
    assert abs((r['initial_media_t']-r['rows'][-1]['total_media_t'])-r['total_wear_t'])<1e-8
    assert all(r['rows'][i]['loss_t']<=r['rows'][i+1]['loss_t'] for i in range(len(r['rows'])-1))
    assert all(r['rows'][i]['total_media_t']>=r['rows'][i+1]['total_media_t'] for i in range(len(r['rows'])-1))

def test_zero_hours_and_no_wear():
    c=default_config();c['horizon_h']=0
    assert simulate_wear(c)['total_wear_t']==0
    c['horizon_h']=1000;c['wear_g_t']=0
    assert simulate_wear(c)['total_wear_t']==0

def test_wear_increases_with_abrasivity():
    c=default_config();a=simulate_wear(c)['total_wear_t']
    c['abrasion_factor']=1.5;b=simulate_wear(c)['total_wear_t']
    assert b>a

def test_two_chambers_different_diameters():
    c=default_config();c['mills'][0]['chambers'][1]['diameter_m']=3.6
    assert math.isclose(volume_m3(c['mills'][0],2),math.pi*3.6**2/4*6.635)
    result=simulate_wear(c)
    q=quality_at(c,result['cohorts'])
    assert len(q['samples'])==14
    assert q['chambers'][1]['diameter_m']==3.6
    assert q['f80_um']>q['p80_um']>0

def test_reject_multiple_drums():
    c=default_config();c['mills'].append(c['mills'][0].copy())
    with pytest.raises(ValueError,match='один барабан'):simulate_wear(c)

def test_material_ratio_and_shapes():
    a=mass_kg(dict(type='Шары',material='Сталь'),40)
    b=mass_kg(dict(type='Цильпебс',material='Сталь',aspect=1),40)
    assert b>a
    assert surface_m2(dict(type='Цильпебс',material='Сталь',aspect=1),40)>surface_m2(dict(type='Шары',material='Сталь'),40)
    c=default_config()
    assert any(x['Догрузить, шт']>0 for x in recommends(c,simulate_wear(c)))

def test_throughput_measured_only():
    c=default_config();c['throughput_mode']='Масса / время'
    assert throughput(c)['product_tph']==72
    c['throughput_mode']='По мощности и Бонду (оценка)'
    with pytest.raises(ValueError):throughput(c)

def test_bad_geometry():
    c=default_config();c['mills'][0]['length_m']=99
    with pytest.raises(ValueError):simulate_wear(c)

def test_sieve_selection_and_calculated_80_values():
    c=default_config();c['sieves_mm']=[.08,.045,.1]
    q=quality_at(c,initial_cohorts(c))
    assert 'R0.1, %' in q['samples'][0]
    assert q['f80_um']==pytest.approx(size_at_pass_percent(c['feed_fraction']))
    assert q['operating_wi_kwh_t']==pytest.approx(operating_bond_index(c['mills'][0]['power_kw'],72,q['f80_um'],q['p80_um']))
    assert operating_bond_index(2400,72,100,110) is None

def test_wear_from_plant_csv():
    lines=parse_history_csv(DEMO_CSV.encode())
    assert len(lines)==3
    assert 0<summarize_history(lines)['gmcr_g_t']<1000
