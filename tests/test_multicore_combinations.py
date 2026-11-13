"""Локальные регрессионные проверки комбинаций (без GitHub Actions)."""
from copy import deepcopy
import pytest
from model import default_config, initial_cohorts
import operation_timeline as timeline


def quick_cfg():
    cfg=default_config()
    cfg.update(simulation_days=1,simulation_hours_per_day=1.,horizon_h=1.,
               step_h=.5,wear_g_t=0.,cement_profile='ЦЕМ I 42,5Н',
               target_product_tph=72.,cement_events=[],media_events=[],
               parameter_events=[],manual_reloads=[])
    return cfg


def test_throughput_violation_does_not_launch_useless_search():
    cfg=quick_cfg()
    cfg['target_product_tph']=1000.
    result=timeline.simulate_operation_timeline(cfg,max_actions=3)
    assert result['blocked_by_throughput']
    assert result['evaluated']==0
    assert not result['actions']
    assert 'производительност' in result['status'].lower()


def test_combination_of_three_different_fractions(monkeypatch):
    """Условия специально заданы так, что одно/два действия недостаточны.

    Это проверка логики оптимизатора, а НЕ физическая модель кинетики помола.
    """
    cfg=quick_cfg()
    baseline=initial_cohorts(cfg)
    keys=[(1,'Шары',70.),(1,'Шары',80.),(2,'Цильпебс',20.)]

    def pieces(cohorts,key):
        return sum(int(c['n']) for c in cohorts if
                   (int(c['chamber']),c['type'],float(c['d0']))==key)

    base={key:pieces(baseline,key) for key in keys}
    def quality(_cfg,cohorts,samples=2):
        add70=pieces(cohorts,keys[0])>base[keys[0]]
        remove80=pieces(cohorts,keys[1])<base[keys[1]]
        add20=pieces(cohorts,keys[2])>base[keys[2]]
        return {'r008':1.5 if add70 else 3.,
                'r0045':34. if remove80 else 38.,
                'blaine_proxy':3400. if add20 else 3100.}
    monkeypatch.setattr(timeline,'quality_at',quality)
    original=deepcopy(cfg)
    result=timeline.simulate_operation_timeline(cfg,parallel=False,
            max_actions=3,candidate_limit=84,pair_limit=120,triple_limit=60,
            observations=3)
    assert cfg==original
    assert len(result['actions'])==3, result['status']
    assert len({(a['target']['chamber'],a['target']['type'],a['target']['diameter_mm'])
                for a in result['actions']})==3
    assert all(isinstance(a['pieces'],int) and a['pieces']>0 for a in result['actions'])
    assert result['optimized'][-1]['ok']
    assert result['action'] is None  # Нельзя незаметно записать лишь первую операцию.
    assert sum(result['search_levels'].values())==result['evaluated']


def test_single_action_is_backward_compatible():
    cfg=quick_cfg()
    result=timeline.simulate_operation_timeline(cfg,optimize=False)
    assert isinstance(result['actions'],list)
    assert result['action'] is None
    assert result['parallel_workers']==1
