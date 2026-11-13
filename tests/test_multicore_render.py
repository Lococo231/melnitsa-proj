"""Проверка графиков Agg без QWidget (PNG получены вне GUI-потока)."""
from model import default_config
from operation_timeline import simulate_operation_timeline
from multicore_render import render_timeline_images


def make_result():
    cfg=default_config()
    cfg.update(simulation_days=1,simulation_hours_per_day=1.,horizon_h=1.,
               step_h=1.,cement_profile='ЦЕМ I 42,5Н')
    return simulate_operation_timeline(cfg,optimize=False,observations=3)


def test_plot_data_can_be_rendered_headlessly():
    r=make_result()
    images,workers,warning=render_timeline_images(r,enabled=False,groups=('sim',))
    assert workers==1 and warning is None
    assert sorted(images)==['sim0','sim1','sim2','sim3','sim4','sim5']
    assert all(data.startswith(b'\x89PNG\r\n\x1a\n') for data in images.values())


def test_plotting_parallel_processes_match_serial():
    r=make_result()
    single,_,_=render_timeline_images(r,enabled=False,groups=('sim',))
    multi,used,warning=render_timeline_images(r,enabled=True,max_workers=2,groups=('sim',))
    assert used in (1,2)
    assert sorted(single)==sorted(multi)
    assert all(multi[k]==single[k] for k in single)


def test_other_tabs_render_on_demand():
    r=make_result()
    h,_,_=render_timeline_images(r,enabled=False,groups=('history',))
    f,_,_=render_timeline_images(r,enabled=False,groups=('fraction',))
    w,_,_=render_timeline_images(r,enabled=False,groups=('forecast',))
    assert len(h)==3 and len(f)==9 and len(w)==2
