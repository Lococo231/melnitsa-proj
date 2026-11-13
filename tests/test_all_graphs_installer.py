"""Checks the entire update chain can be installed twice (no Qt required)."""
from pathlib import Path
import subprocess
import sys


def test_combined_installer_runs_twice(tmp_path):
    root = Path(__file__).resolve().parents[1]
    repo = tmp_path / 'repo'
    (repo / 'project').mkdir(parents=True)
    (repo / 'project/qt_app.py').write_text(
        'class AdaptiveTabs:\n'
        '    def resizeEvent(self, event):\n'
        '        required = sum(bar.tabSizeHint(i).width() for i in range(bar.count())) + 25\n'
        '        return required\n\n'
        'from workspace_ui import install as install_workspace_ui\n'
        'install_workspace_ui(MillWindow)\n', encoding='utf-8')
    # An already fraction-sized renderer, just as after the prior update.
    renderer = (root / 'project/multicore_render.py').read_text(encoding='utf-8')
    renderer = renderer.replace(
        '        # ALL Matplotlib Agg figures must match the actual visible Qt viewport:\n'
        '        # simulation, fraction wear, event history and forecast. The PNG has\n'
        '        # twice the logical pixels, avoiding blurry upscaling on HiDPI screens.\n'
        '        pane_width, pane_height = target_size\n'
        '        if pane_width <= 0 or pane_height <= 0:\n'
        "            raise ValueError('Размер графика должен быть положительным')\n"
        '        render_size = (2 * int(pane_width), 2 * int(pane_height))\n'
        '        for job in jobs:\n'
        "            job['render_px'] = render_size",
        '        # Fraction charts are prepared for the available canvas aspect ratio.\n'
        '        pane_width, pane_height = target_size\n'
        '        for job in jobs:\n'
        "            if job['id'].startswith('fraction_'):\n"
        "                job['render_px'] = (2*int(pane_width), 2*int(pane_height))")
    renderer = renderer.replace('min(6400, int(pixel_w))', 'min(3200, int(pixel_w))')
    renderer = renderer.replace('min(3600, int(pixel_h))', 'min(1900, int(pixel_h))')
    (repo / 'project/multicore_render.py').write_text(renderer, encoding='utf-8')
    cmd = [sys.executable, str(root / 'apply_all_graphs_update.py'), str(repo)]
    first = subprocess.run(cmd, text=True, capture_output=True)
    assert first.returncode == 0, first.stderr + first.stdout
    second = subprocess.run(cmd, text=True, capture_output=True)
    assert second.returncode == 0, second.stderr + second.stdout
    assert 'Адаптивные графики установлены. Обновлено: 0' in second.stdout
    app = (repo / 'project/qt_app.py').read_text(encoding='utf-8')
    assert app.count('install_adaptive_graphs_ui(MillWindow)') == 1
    assert app.count('install_staged_results_ui(MillWindow)') == 1
    assert app.count('install_responsive_ui(MillWindow)') == 1
    assert '# ALL Matplotlib Agg figures must match' in (
        repo / 'project/multicore_render.py').read_text(encoding='utf-8')
    assert 'if self.tabs.isTabVisible(i)' in app
    assert (repo / 'project/adaptive_graphs_ui.py').is_file()
    assert (repo / 'project/staged_results_ui.py').is_file()
    assert (repo / 'project/responsive_ui.py').is_file()
