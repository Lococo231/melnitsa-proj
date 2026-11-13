"""Static release checks: no Windows runner or automatic GitHub Actions required."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_onefile_build_script_covers_multiprocessing_gui_and_matplotlib():
    script = (ROOT / 'scripts/build_windows.ps1').read_text('utf-8')
    assert "'OneFile','OneDir'" in script
    assert "'--onefile'" in script
    assert "'--onedir'" in script
    assert "'--windowed'" in script
    assert 'matplotlib.backends.backend_qtagg' in script
    assert 'matplotlib.backends.backend_agg' in script
    assert "--paths'" in script
    assert 'CementMill' in script
    assert (ROOT / 'build_windows.cmd').is_file()
    assert (ROOT / 'requirements-build.txt').is_file()


def test_entrypoint_guards_frozen_multiprocessing():
    main = (ROOT / 'main.py').read_text('utf-8')
    assert "if __name__ == '__main__':" in main
    assert main.index('freeze_support()') < main.index('from qt_app import main')
