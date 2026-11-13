"""Pure text transformations for multicore_render.py, no Qt dependency."""
from __future__ import annotations


def _replace_once(text: str, old: str, new: str, anchor: str) -> str:
    if new in text:
        return text
    number = text.count(old)
    if number != 1:
        raise RuntimeError(f'{anchor}: ожидается одно вхождение, найдено {number}.')
    return text.replace(old, new)


def patch_renderer(src: str) -> str:
    # The all-graphs renderer is the next version of the fraction-only patch.
    # Do not accidentally insert the old block when the new block is present.
    if '# ALL Matplotlib Agg figures must match' in src:
        return src
    src = _replace_once(src,
        "fig = Figure(figsize=(10.8, 2.20), dpi=110, facecolor='#162a3d')",
        """# Use two physical pixels per display pixel for sharp curves/text.\n    # With target_size the image aspect follows the *current Qt pane*.\n    pixel_w, pixel_h = job.get('render_px', (1920, 540))\n    pixel_w = max(620, min(3200, int(pixel_w)))\n    pixel_h = max(270, min(1900, int(pixel_h)))\n    dpi = 170\n    fig = Figure(figsize=(pixel_w/dpi, pixel_h/dpi), dpi=dpi, facecolor='#162a3d')""",
        'figure resolution')
    src = _replace_once(src,
        "fig.savefig(buf,format='png',dpi=110,facecolor=fig.get_facecolor())",
        "fig.savefig(buf,format='png',dpi=dpi,facecolor=fig.get_facecolor())",
        'save resolution')
    src = _replace_once(src,
        "enabled:bool=True, groups:tuple[str,...]|None=None):",
        "enabled:bool=True, groups:tuple[str,...]|None=None,\n                           target_size:tuple[int,int]|None=None):",
        'target size signature')
    src = _replace_once(src,
        "    if not jobs:\n        return {},1,None",
        """    if target_size is not None:\n        # Fraction charts are prepared for the available canvas aspect ratio.\n        pane_width, pane_height = target_size\n        for job in jobs:\n            if job['id'].startswith('fraction_'):\n                job['render_px'] = (2*int(pane_width), 2*int(pane_height))\n    if not jobs:\n        return {},1,None""",
        'target size jobs')
    return src
