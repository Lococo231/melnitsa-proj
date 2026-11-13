"""Проверка установщика без PySide6; GitHub Actions не нужен."""
import subprocess
import sys
from pathlib import Path


def test_staged_results_installer_can_be_applied_twice(tmp_path):
    source = Path(__file__).resolve().parents[1]
    folder = tmp_path / "melnitsa"
    (folder / "project").mkdir(parents=True)
    (folder / "project/qt_app.py").write_text(
        "class AdaptiveTabs:\n"
        "    def resizeEvent(self, event):\n"
        "        required = sum(bar.tabSizeHint(i).width() for i in range(bar.count())) + 25\n"
        "        return required\n"
        "from workspace_ui import install as install_workspace_ui\n"
        "install_workspace_ui(MillWindow)\n",
        encoding="utf-8",
    )
    command = [sys.executable, str(source / "apply_staged_results.py"), str(folder)]
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    second = subprocess.run(command, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert "Новых изменений нет" in second.stdout
    app = (folder / "project/qt_app.py").read_text(encoding="utf-8")
    assert app.count("install_staged_results_ui(MillWindow)") == 1
    assert "if self.tabs.isTabVisible(i)" in app
    assert (folder / "project/qt_app.py.bak").exists()
    assert (folder / "doc/plan/11-grouped-results.md").is_file()
    assert "Контроль помола" in (folder / "README.md").read_text(encoding="utf-8")
