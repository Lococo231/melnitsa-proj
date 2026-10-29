import math
import pytest
from model import (default_config, simulate_wear, recommends, throughput,
                   quality_at, initial_cohorts, volume_m3, mass_kg, surface_m2)
from calibration import parse_history_csv, summarize_history, DEMO_CSV


def test_mass_balance_wo_reload():
    c=default_config();r=simulate_wear(c)
    assert abs((r['initial_media_t']-r['rows'][-1]['total_media_t'])-r['total_wear_t'])<1e-8
    assert all(r['rows'][i]['loss_t']<=r['rows'][i+1]['loss_t'] for i in range(len(r['rows'])-1))
    assert all(r['rows'][i]['total_media_t']>=r['rows'][i+1]['total_media_t'] for i in range(len(r['rows'])-1))


def test_zero_hours_and_no_wear():
    c=default_config();c['horizon_h']=0
    r=simulate_wear(c)
    assert r['total_wear_t']==0
    c['horizon_h']=1000;c['wear_g_t']=0
    r=simulate_wear(c)
    assert r['total_wear_t']==0


def test_wear_increases_with_abrasivity():
    c=default_config();a=simulate_wear(c)['total_wear_t']
    c['abrasion_factor']=1.5;b=simulate_wear(c)['total_wear_t']
    assert b>a


def test_geometry_and_two_drums():
    c=default_config()
    c['mills'].append(dict(name='Б2',diameter_m=3.8,length_m=10.,rpm=15.,power_kw=1700.,diaphragm_m=.5,
                           chambers=[dict(length_m=4.),dict(length_m=5.5)]))
    c['media'].append(dict(drum=2,chamber=1,type='Шары',material='Высокохромистый чугун',diameter_mm=80.,initial_t=50.,aspect=1.))
    c['media'].append(dict(drum=2,chamber=2,type='Цильпебс',material='Серый чугун',diameter_mm=30.,initial_t=40.,aspect=1.))
    r=simulate_wear(c)
    assert r['rows'][-1]['Б2К1 масса, т']<50
    assert r['rows'][-1]['Б2К2 масса, т']<40
    assert math.isclose(volume_m3(c['mills'][1],1),math.pi*(3.8**2)/4*4)
    assert len(quality_at(c,r['cohorts'])['samples'])==14


def test_material_ratio_and_shapes():
    c=default_config()
    a=mass_kg(dict(type='Шары',material='Сталь'),40)
    b=mass_kg(dict(type='Цильпебс',material='Сталь',aspect=1),40)
    assert b>a
    assert surface_m2(dict(type='Цильпебс',material='Сталь',aspect=1),40)>surface_m2(dict(type='Шары',material='Сталь'),40)
    r=recommends(c,simulate_wear(c))
    assert any(x['Догрузить, шт']>0 for x in r)


def test_throughput_modes():
    c=default_config()
    c['throughput_mode']='Масса / время'
    assert throughput(c)['product_tph']==72
    c['throughput_mode']='По мощности и удельной энергии'
    assert throughput(c)['product_tph']==75
    c['throughput_mode']='По мощности и Бонду (оценка)'
    assert throughput(c)['product_tph']>0


def test_bad_geometry():
    c=default_config();c['mills'][0]['length_m']=99
    with pytest.raises(ValueError): simulate_wear(c)


def test_wear_from_plant_csv():
    lines=parse_history_csv(DEMO_CSV.encode())
    assert len(lines)==3
    assert 0<summarize_history(lines)['gmcr_g_t']<1000
