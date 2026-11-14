from pathlib import Path
import importlib.util
import sys


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_dynamics_advance_without_qt():
    root = Path(__file__).resolve().parents[1] / 'project'
    dynamics = load_module('mill_dynamics_test', root / 'mill_dynamics.py')
    drum = dynamics.DrumCharge(rpm=16.0, diameter_m=4.0, chamber=1)
    axial = dynamics.AxialTransport([6.3, 6.6])
    for _ in range(10):
        drum.step(0.03)
        axial.step(0.03, 72.0)
    assert drum.impact_count >= 0
    assert drum.breakage_count >= 0
    assert len(axial.media_layout()['ch1']) > 0
    assert 0.1 < axial.split < 0.9


def test_no_invalid_alignment_flag_left_in_source():
    source = (Path(__file__).resolve().parents[1] / 'project' / 'mill_visual_ui.py').read_text(encoding='utf-8')
    assert 'AlignmentFlag.TextWordWrap' not in source


def test_worker_never_reads_qt_widget_config_in_run_loop():
    source = (Path(__file__).resolve().parents[1] / 'project' / 'mill_visual_ui.py').read_text(encoding='utf-8')
    worker_run = source.split('    def run(self) -> None:', 1)[1].split('\n\nclass MillCutWidget', 1)[0]
    assert 'current_parameters()' not in worker_run
    assert 'self._stop_event' in worker_run
