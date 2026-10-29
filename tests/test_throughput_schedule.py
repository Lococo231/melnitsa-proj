"""Подача по времени, баланс производства и корректное время догрузки."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from model import default_config,simulate_wear,validate,throughput_at
from excel_export import export_excel


def test_constant_feed():
    cfg=default_config()
    run=simulate_wear(cfg)
    assert len({r['Производительность, т/ч'] for r in run['rows']})==1
    assert run['rows'][-1]['production_t']==pytest.approx(72000)


def test_feed_schedule_changes_wear_and_excel():
    cfg=default_config()
    cfg['throughput_schedule']=[{'hour':250.,'tph':60.},{'hour':500.,'tph':85.}]
    run=simulate_wear(cfg)
    assert throughput_at(cfg,100)==72
    assert throughput_at(cfg,400)==60
    assert throughput_at(cfg,700)==85
    expected=250*72+250*60+500*85
    assert run['rows'][-1]['production_t']==pytest.approx(expected)
    assert len({r['Производительность, т/ч'] for r in run['rows']})==3
    assert run['throughput']['average_product_tph']==pytest.approx(expected/1000)
    assert run['total_wear_t']!=pytest.approx(simulate_wear(default_config())['total_wear_t'])
    with ZipFile(BytesIO(export_excel(cfg,run))) as archive:
        assert any('Производительность во времени'.encode() in archive.read(p)
                   for p in archive.namelist() if p.startswith('xl/charts/chart'))


def test_exact_reload_hour_between_time_steps():
    cfg=default_config()
    cfg['horizon_h']=200.
    cfg['step_h']=90.
    cfg['manual_reloads']=[dict(drum=1,chamber=2,hour=55.,type='Цильпебс',
                                 material='Сталь',diameter_mm=30.,tons=2.,aspect=1.)]
    run=simulate_wear(cfg)
    assert any(abs(row['hours']-55)<1e-8 for row in run['rows'])
    assert run['reload_events'][0]['hour']==pytest.approx(55)
    empty=deepcopy(cfg);empty['manual_reloads']=[]
    assert run['rows'][-1]['total_media_t']>simulate_wear(empty)['rows'][-1]['total_media_t']


def test_invalid_schedule():
    cfg=default_config()
    cfg['throughput_schedule']=[{'hour':-1.,'tph':72.}]
    with pytest.raises(ValueError,match='Час'):validate(cfg)
    cfg['throughput_schedule']=[{'hour':100,'tph':72},{'hour':100,'tph':75}]
    with pytest.raises(ValueError,match='повторяться'):validate(cfg)
