"""Запускать в репозитории после применения обновления: pytest -q tests/test_shift_simulation.py."""
from copy import deepcopy
from model import default_config, mass_kg, initial_cohorts, cohort_mass
from production_planning import PROFILES, assessments
from shift_simulation import (simulate_shifts, operation_day, hours_of_operation,
                              _change_media)


def test_profiles_from_html():
    assert len(PROFILES) == 6  # пять видов + без ограничений
    assert PROFILES['ЦЕМ I 42,5Б']['r008']['max'] == 1.5
    assert 'r008' not in PROFILES['ЦЕМ I 52,5Н']
    assert PROFILES['ЦЕМ II/А-Ш 42,5Н']['r0045']['min'] == 34.


def test_shift_timing_and_non_mutation():
    cfg=default_config()
    cfg.update(simulation_days=2, simulation_hours_per_day=3.,
               horizon_h=6., step_h=1., cement_profile='ЦЕМ I 42,5Н')
    before=deepcopy(cfg)
    out=simulate_shifts(cfg,observations=5,candidate_limit=4)
    assert out['hours']==6
    assert out['baseline'][0]['hour']==0
    assert out['baseline'][-1]['hour']==6
    assert len(out['baseline'])>=2
    assert cfg==before
    assert operation_day(3.,3.)=='день 1, час 3 из 3'
    assert operation_day(3.1,3.)=='день 2, час 0.1 из 3'


def test_removal_keeps_remaining_diameter():
    cfg=default_config()
    cohort=initial_cohorts(cfg)[0]
    before=cohort['d']
    available=cohort_mass(cohort)/1000
    act={'hour':0.,'direction':'remove','tons':available*.10,
         'target':{'chamber':cohort['chamber'],'type':cohort['type'],
                   'material':cohort['material'],'diameter_mm':cohort['d0'],
                   'aspect':cohort.get('aspect',1.)}}
    _change_media(cfg,[cohort],act)
    assert isinstance(cohort['n'], int)
    assert abs(cohort_mass(cohort)/1000-available*.9)<=mass_kg(cohort,cohort['d'])/1000
    assert cohort['d']==before