"""Installer syntax/idempotence without Qt and without GitHub Actions."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path


def test_installer_can_apply_twice(tmp_path):
    root=Path(__file__).resolve().parents[1]
    repo=tmp_path/'melnitsa'
    (repo/'project').mkdir(parents=True)
    (repo/'project/qt_app.py').write_text(
        "class AdaptiveTabs:\n"
        "    def resizeEvent(self,event):\n"
        "        required = sum(bar.tabSizeHint(i).width() for i in range(bar.count())) + 25\n"
        "        return required\n\n"
        "from workspace_ui import install as install_workspace_ui\n"
        "install_workspace_ui(MillWindow)\n", encoding='utf-8')
    # Use the patched source as a valid fixture; idempotence also covers
    # projects already updated to the newest renderer.
    (repo/'project/multicore_render.py').write_text(
        (root/'project/multicore_render.py').read_text(encoding='utf-8'),
        encoding='utf-8')
    command=[sys.executable,str(root/'apply_responsive_update.py'),str(repo)]
    first=subprocess.run(command,text=True,capture_output=True)
    assert first.returncode==0,first.stderr+first.stdout
    second=subprocess.run(command,text=True,capture_output=True)
    assert second.returncode==0,second.stderr+second.stdout
    qt=(repo/'project/qt_app.py').read_text(encoding='utf-8')
    assert qt.count('install_responsive_ui(MillWindow)')==1
    assert qt.count('install_staged_results_ui(MillWindow)')==1
    assert (repo/'project/responsive_ui.py').is_file()
    assert (repo/'project/staged_results_ui.py').is_file()
    assert (repo/'project/qt_app.py.bak').is_file()
    assert 'Адаптивная ширина' in (repo/'README.md').read_text(encoding='utf-8')
    assert 'Обновление готово; изменено файлов: 0' in second.stdout
