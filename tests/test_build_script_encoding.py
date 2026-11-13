"""Local check: Windows PowerShell 5.1 compatible build-script encoding.

No GitHub Actions. Run: python -m pytest -q tests/test_build_script_encoding.py
"""
from pathlib import Path


def test_windows_build_scripts_contain_only_ascii():
    root = Path(__file__).resolve().parents[1]
    for relative in ('scripts/build_windows.ps1', 'build_windows.cmd'):
        data = (root / relative).read_bytes()
        assert data, relative
        assert all(byte < 128 for byte in data), f'{relative} has non-ASCII bytes'
        assert b'\xef\xbb\xbf' not in data


def test_build_script_modes_and_error_handling():
    root = Path(__file__).resolve().parents[1]
    ps = (root / 'scripts/build_windows.ps1').read_text(encoding='ascii')
    cmd = (root / 'build_windows.cmd').read_text(encoding='ascii')
    assert "[ValidateSet('OneFile', 'OneDir')]" in ps
    assert "'--onefile'" in ps and "'--onedir'" in ps
    assert "'--collect-all', 'matplotlib'" in ps
    assert "if ($LASTEXITCODE -ne 0)" in ps
    assert 'finally {' in ps
    assert 'powershell.exe -NoProfile' in cmd
    assert 'if errorlevel 1 (' in cmd
