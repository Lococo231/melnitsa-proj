"""Resolution checks for all Agg plot families (no Qt dependencies)."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'project'))


def test_each_chart_family_respects_selected_widget_size(monkeypatch):
    import multicore_render as renderer

    def jobs(_result):
        return [
            {'id': key, 'title': key, 'unit': '%', 'end': 100.,
             'legend_side': True,
             'traces': [{'x': [0, 50, 100], 'y': [0, 2, 5],
                         'label': 'Данные', 'color': '#66cbe1'}]}
            for key in ('sim0', 'sim5', 'history0', 'fraction_all_1', 'forecast0')
        ]

    monkeypatch.setattr(renderer, '_jobs_for_result', jobs)
    dimensions = {
        'sim0': (475, 315),
        'sim5': (720, 245),
        'history0': (510, 210),
        'fraction_all_1': (360, 400),
        'forecast0': (780, 300),
    }
    for name, size in dimensions.items():
        images, workers, warning = renderer.render_timeline_images(
            {}, groups=(name,), enabled=False, target_size=size)
        assert list(images) == [name]
        assert workers == 1 and warning is None
        with Image.open(BytesIO(images[name])) as image:
            assert image.size == tuple(2 * n for n in size)
            assert image.format == 'PNG'


def test_renderer_still_supports_old_unsized_requests():
    from multicore_render import _part_png
    name, raw = _part_png({
        'id': 'sim0', 'title': 'R0.08', 'end': 12., 'unit': '%',
        'traces': [{'x': [0, 12], 'y': [1, 1.5], 'label': 'Без коррекции'}]
    })
    with Image.open(BytesIO(raw)) as image:
        assert name == 'sim0'
        assert image.size == (1920, 540)


def test_renderer_text_patch_remains_idempotent():
    sys.path.insert(0, str(ROOT))
    from patch_renderer import patch_renderer
    text = (ROOT / 'project/multicore_render.py').read_text(encoding='utf-8')
    assert patch_renderer(text) == text
