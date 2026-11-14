"""Multi-core, GUI-free preview calculations for all mill input plots.

ProcessPoolExecutor(spawn) prevents Python GIL from bottlenecking model work.
Qt widgets/Matplotlib QtAgg must be updated only by the GUI thread.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from math import ceil
import atexit
import multiprocessing as mp
import os
import threading

_LOCK = threading.Lock()
_POOL = None


def workers_available() -> int:
    return min(4,max(2, (os.cpu_count() or 2)-1))


def _pool():
    global _POOL
    with _LOCK:
        if _POOL is None:
            _POOL=ProcessPoolExecutor(max_workers=workers_available(),
                                      mp_context=mp.get_context('spawn'))
        return _POOL


def shutdown():
    global _POOL
    with _LOCK:
        pool,_POOL=_POOL,None
    if pool is not None:
        pool.shutdown(wait=False,cancel_futures=True)


atexit.register(shutdown)


def _execute(part, cfg, run=None):
    # These imports intentionally happen in child processes.
    from model import (initial_cohorts, simulate_wear, quality_at,
                       config_at_time, recommends)
    if part=='wear':
        return simulate_wear(cfg)
    if part=='input_quality':
        return quality_at(cfg,initial_cohorts(cfg),samples=14)
    if part=='final_quality':
        return quality_at(config_at_time(cfg,cfg['horizon_h']),run['cohorts'],samples=14)
    if part=='recommendations':
        return recommends(cfg,run)
    raise ValueError(part)


def calculate_preview(cfg: dict, parallel: bool = True) -> dict:
    """Compute same wear, fineness and reload equations as existing GUI.

    Parallel independent tasks: wear + initial quality, then final quality +
    recommendation. If spawn/pickle fails, fall back to the same pure functions.
    """
    cfg=deepcopy(cfg)
    if parallel:
        try:
            pool=_pool()
            wear_future=pool.submit(_execute,'wear',cfg)
            input_future=pool.submit(_execute,'input_quality',cfg)
            run=wear_future.result()
            feed_quality=input_future.result()
            out_future=pool.submit(_execute,'final_quality',cfg,run)
            reco_future=pool.submit(_execute,'recommendations',cfg,run)
            quality=out_future.result()
            reco=reco_future.result()
            return {'cfg':cfg,'run':run,'quality':quality,'reco':reco,
                    'feed_quality':feed_quality,'parallel':True,
                    'workers':workers_available()}
        except Exception as e:
            # If one subprocess crashed, old executor may be unusable.
            shutdown()
            failure=str(e)
    else:
        failure=None
    run=_execute('wear',cfg)
    return {'cfg':cfg,'run':run,
            'quality':_execute('final_quality',cfg,run),
            'reco':_execute('recommendations',cfg,run),
            'feed_quality':_execute('input_quality',cfg),
            'parallel':False,'workers':1,'warning':failure}


def overview_config(cfg:dict, hours:float) -> dict:
    """Dedicated overview horizon, independent from the simulation's run length."""
    hours=max(.5,float(hours))
    days=max(1,ceil(hours/24.))
    working=hours/days
    out=deepcopy(cfg)
    out['simulation_days']=days
    out['simulation_hours_per_day']=working
    out['horizon_h']=hours
    for name in ('cement_events','media_events','parameter_events','manual_reloads'):
        if name in out:
            out[name]=[e for e in out[name] if 0.<=float(e.get('hour',0))<=hours]
    return out


def calculate_overview(cfg:dict, hours:float, parallel:bool=True) -> dict:
    from operation_timeline import simulate_operation_timeline
    prepared=overview_config(cfg,hours)
    if parallel:
        try:
            r=_pool().submit(simulate_operation_timeline,prepared,
                             optimize=False,observations=65,parallel=False)
            return r.result()
        except Exception:
            shutdown()
    return simulate_operation_timeline(prepared,optimize=False,
                                       observations=65,parallel=False)
