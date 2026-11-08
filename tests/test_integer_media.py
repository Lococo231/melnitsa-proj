"""Ручные тесты целочисленной модели и управления часами (без GitHub Actions)."""
from copy import deepcopy
import pytest
from model import (default_config, mass_kg, piece_count, mass_for_count_t,
                   initial_cohorts, cohort_mass, simulate_wear)
from shift_simulation import _change_media, _candidates, _install_manual
from production_planning import starting_media


def test_initial_cohorts_are_whole_pieces_and_mass_is_consistent():
    cfg=default_config()
    for c in initial_cohorts(cfg):
        assert type(c['n']) is int
        assert c['initial_kg'] == pytest.approx(c['n']*mass_kg(c,c['d0']))
    for row in starting_media(cfg):
        assert type(row['Количество, шт']) is int
    result=simulate_wear({**cfg,'horizon_h':20.,'step_h':2.})
    assert all(type(c['n']) is int for c in result['cohorts'])


def test_remove_counts_whole_and_preserves_each_remaining_diameter():
    cfg=default_config()
    cohorts=initial_cohorts(cfg)
    first=cohorts[0]
    group=dict(chamber=first['chamber'],type=first['type'],material=first['material'],
               diameter_mm=first['d0'],aspect=first.get('aspect',1.))
    before=first['n']
    diameter=first['d']
    action=dict(direction='remove',target=group,pieces=7,tons=7*mass_kg(first,first['d'])/1000,hour=0)
    _change_media(cfg,cohorts,action)
    assert first['n']==before-7
    assert first['d']==diameter
    assert type(first['n']) is int
    assert first['initial_kg']==pytest.approx(first['n']*mass_kg(first,first['d0']))


def test_shift_candidates_use_exact_pieces():
    cfg=default_config()
    cohorts=initial_cohorts(cfg)
    possibilities=list(_candidates(cfg,cohorts,0))
    assert possibilities
    for action in possibilities:
        assert type(action['pieces']) is int
        assert action['pieces']>0
        changed=deepcopy(cohorts)
        old_count=sum(c['n'] for c in changed)
        _change_media(cfg,changed,action)
        expected=old_count+action['pieces'] if action['direction']=='add' else old_count-action['pieces']
        assert sum(c['n'] for c in changed)==expected
        assert all(type(c['n']) is int for c in changed)


def test_reloads_whole():
    cfg=default_config()
    r=cfg['media'][0]
    extra={'drum':1,'chamber':r['chamber'],'type':r['type'],'material':r['material'],
           'diameter_mm':r['diameter_mm'],'aspect':r.get('aspect',1.),
           'tons':0.0143,'hour':2.}
    out=initial_cohorts(cfg)
    _install_manual({'manual_reloads':[extra]},out,2.)
    assert type(out[-1]['n']) is int
    assert out[-1]['initial_kg']==pytest.approx(out[-1]['n']*mass_kg(out[-1],out[-1]['d0']))