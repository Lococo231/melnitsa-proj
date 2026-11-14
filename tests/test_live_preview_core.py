import pytest
from live_preview_core import overview_config, workers_available


def test_horizon_is_independent_and_event_logs_are_filtered():
    cfg={'simulation_days':5,'simulation_hours_per_day':8,
         'horizon_h':40, 'cement_events':[{'hour':60,'profile':'B'}, {'hour':20,'profile':'A'}],
         'manual_reloads':[{'hour':20},{'hour':200}]}
    before=cfg.copy()
    out=overview_config(cfg,120)
    assert out['simulation_days']==5
    assert out['simulation_hours_per_day']==24
    assert out['horizon_h']==120
    assert len(out['cement_events'])==2
    assert len(out['manual_reloads'])==1
    assert cfg['horizon_h']==40
    assert cfg['manual_reloads']==before['manual_reloads']
    out2=overview_config(cfg,25.)
    assert out2['horizon_h']==25.
    assert out2['simulation_days']==2
    assert out2['simulation_hours_per_day']==12.5
    assert len(out2['cement_events'])==1


def test_worker_count_is_reasonable():
    assert 2<=workers_available()<=4
