"""Локальные проверки формульных инвариантов (не GitHub Actions)."""
from __future__ import annotations
import math
from copy import deepcopy

import pytest
from model import (default_config, mass_kg, mass_for_count_t, piece_count,
                   volume_m3, initial_cohorts, cohort_mass, simulate_wear,
                   cumulative_residue, operating_bond_index)


def test_sphere_and_cylpebs_mass_units():
    sphere = {'type':'Шары','material':'Сталь','diameter_mm':50.,'aspect':1.}
    cylinder = {**sphere,'type':'Цильпебс','aspect':1.2}
    density = 7850.
    diameter = .05
    assert mass_kg(sphere,50.) == pytest.approx(density * math.pi * diameter**3 / 6)
    assert mass_kg(cylinder,50.) == pytest.approx(density * math.pi * diameter**3 * 1.2 / 4)


def test_volume_of_chamber():
    cfg=default_config()
    mill=cfg['mills'][0]
    assert volume_m3(mill,1)==pytest.approx(math.pi*mill['chambers'][0]['diameter_m']**2/4 *mill['chambers'][0]['length_m'])


def test_all_counts_are_integers_and_mass_derived_from_count():
    cfg=default_config()
    cohorts=initial_cohorts(cfg)
    assert cohorts
    assert all(isinstance(c['n'],int) for c in cohorts)
    for c in cohorts:
        assert cohort_mass(c)==pytest.approx(c['n']*mass_kg(c,c['d']))
    row=cfg['media'][0]
    assert piece_count(row,mass_for_count_t(row,5))==5
    assert piece_count(row,mass_for_count_t(row,5)+0.51*mass_kg(row,row['diameter_mm'])/1000)==6


def test_wear_balance_without_events():
    cfg=default_config()
    cfg['horizon_h']=40.
    cfg['step_h']=5.
    cfg['manual_reloads']=[]
    out=simulate_wear(cfg)
    assert all(isinstance(c['n'],int) for c in out['cohorts'])
    removed_t=sum(float(c.get('removed_kg',0)) for c in out['cohorts'])/1000.
    assert out['initial_media_t']==pytest.approx(out['rows'][-1]['total_media_t']+out['total_wear_t']+removed_t, abs=1e-6)
    assert out['rows'][-1]['production_t']>0


def test_cumulative_residue_is_monotone_by_sieve():
    cfg=default_config()
    from model import quality_at
    data=quality_at(cfg,initial_cohorts(cfg),samples=2)
    product=data['product_fractions']
    assert sum(product)==pytest.approx(100.,abs=1e-5)
    assert all(x>=-1e-8 for x in product)
    # Большое отверстие пропускает больше материала: полный остаток меньше.
    assert cumulative_residue(product,.08)<=cumulative_residue(product,.045)
    assert cumulative_residue(product,.63)<=cumulative_residue(product,.08)
    assert data['r008']==pytest.approx(cumulative_residue(product,.08))


def test_bond_operating_energy_units_and_scope():
    wi=12.5
    f80=1000.
    p80=100.
    e=wi*10*(1/math.sqrt(p80)-1/math.sqrt(f80))
    flow=50.
    assert operating_bond_index(e*flow,flow,f80,p80)==pytest.approx(wi)
    assert operating_bond_index(e*flow,flow,p80,f80) is None
