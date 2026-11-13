"""Matplotlib Agg quality checks; no PySide6 required."""
from __future__ import annotations
import io
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'project'))
from patch_renderer import patch_renderer


def test_renderer_is_idempotent():
    source = (ROOT/'project'/'multicore_render.py').read_text(encoding='utf-8')
    assert patch_renderer(source) == source


def test_fraction_render_matches_requested_pixel_size():
    from multicore_render import _part_png
    job = {
        'id':'fraction_all_0', 'title':'Диаметр мелющих тел',
        'unit':'мм', 'end':150, 'legend_side':True,
        'render_px':(960,680),
        'traces':[{'x':[0,50,100,150], 'y':[70,68,65,63],
                   'label':'К1 Шары Ø70'}],
    }
    key,raw=_part_png(job)
    assert key == job['id']
    with Image.open(io.BytesIO(raw)) as img:
        assert img.size == (960,680)
        assert img.mode in ('RGB','RGBA')


def test_selected_fraction_is_rendered_without_other_nine_charts(monkeypatch):
    import multicore_render as r
    monkeypatch.setattr(r,'_jobs_for_result',lambda result: [
        {'id':f'fraction_all_{i}','title':'Test', 'unit':'т','end':12.,
         'traces':[{'x':[0,12],'y':[i,i+1],'label':'К1'}]}
        for i in range(3)
    ])
    pics, workers, error = r.render_timeline_images(
        {},enabled=False,groups=('fraction_all_1',),target_size=(490,300))
    assert list(pics)==['fraction_all_1']
    assert workers==1 and error is None
    with Image.open(io.BytesIO(pics['fraction_all_1'])) as img:
        assert img.size==(980,600)
