"""Те же результаты независимо от количества процессов."""
from __future__ import annotations
from copy import deepcopy
import pytest
from model import default_config
from operation_timeline import simulate_operation_timeline


def make_config():
    cfg=default_config()
    cfg.update(simulation_days=1,simulation_hours_per_day=2.,
               horizon_h=2.,step_h=.5,cement_profile='ЦЕМ I 52,5Н')
    return cfg


def test_parallel_and_serial_are_identical():
    cfg=make_config()
    original=deepcopy(cfg)
    seq=simulate_operation_timeline(cfg,parallel=False,observations=5,candidate_limit=8)
    par=simulate_operation_timeline(cfg,parallel=True,max_workers=2,
                                    observations=5,candidate_limit=8)
    assert cfg==original
    assert seq['evaluated']==par['evaluated']
    assert seq['first_bad']==par['first_bad']
    assert seq['baseline']==par['baseline']
    assert seq.get('optimized')==par.get('optimized')
    assert seq.get('action')==par.get('action')
    assert seq['cement_changes']==par['cement_changes']
    assert seq['media_changes']==par['media_changes']
    assert seq['parameter_changes']==par['parameter_changes']
    assert seq.get('parallel_workers',1)==1
    assert par.get('parallel_workers',1) in (1,2)


def test_event_timeline_parallel_and_sequential():
    cfg=make_config()
    cfg['cement_events']=[{'hour':1.,'profile':'ЦЕМ I 42,5Н'}]
    cfg['parameter_events']=[{'hour':1.,'parameter':'rpm','value':15.}]
    seq=simulate_operation_timeline(cfg,parallel=False,observations=6,candidate_limit=6)
    par=simulate_operation_timeline(cfg,parallel=True,max_workers=2,
                                    observations=6,candidate_limit=6)
    assert seq['baseline']==par['baseline']
    assert seq.get('optimized')==par.get('optimized')
    assert seq.get('action')==par.get('action')
    assert seq['cement_changes']==par['cement_changes']
    assert seq['parameter_changes']==par['parameter_changes']
