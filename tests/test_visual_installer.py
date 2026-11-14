import subprocess
import sys
from pathlib import Path


def test_installer_runs_twice_and_does_not_duplicate(tmp_path):
    root=Path(__file__).resolve().parents[1]
    repo=tmp_path/'melnitsa'
    (repo/'project').mkdir(parents=True)
    (repo/'project/qt_app.py').write_text(
        'from operator_workflow_ui import install as install_operator_workflow_ui\n'
        'install_operator_workflow_ui(MillWindow)\n',encoding='utf-8')
    cmd=[sys.executable,str(root/'apply_visual_multicore_update.py'),str(repo)]
    first=subprocess.run(cmd,capture_output=True,text=True)
    assert first.returncode==0,first.stderr
    second=subprocess.run(cmd,capture_output=True,text=True)
    assert second.returncode==0,second.stderr
    assert 'No changes' in second.stdout
    text=(repo/'project/qt_app.py').read_text(encoding='utf-8')
    assert text.count('install_live_multicore_ui(MillWindow)')==1
    assert (repo/'project/mill_dynamics.py').exists()
    assert (repo/'project/mill_visual_ui.py').exists()
    assert (repo/'project/qt_app.py.bak').exists()
    assert 'Фаза 16' in (repo/'README.md').read_text(encoding='utf-8')
