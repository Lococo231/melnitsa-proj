"""Installer for the animation redesign package (no git operations)."""
from __future__ import annotations

from pathlib import Path
import shutil
import sys

ADDITIONS = {
    'README.md': (Path(__file__).resolve().parent / 'README.md').read_text(encoding='utf-8'),
    'AGENTS.md': (Path(__file__).resolve().parent / 'AGENTS.md').read_text(encoding='utf-8'),
    'CHANGELOG.production.md': (Path(__file__).resolve().parent / 'CHANGELOG.production.md').read_text(encoding='utf-8'),
    'doc/todo.md': (Path(__file__).resolve().parent / 'doc/todo.md').read_text(encoding='utf-8'),
}


def write_file(dst: Path, contents: str) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file() and dst.read_text(encoding='utf-8') == contents:
        return False
    if dst.exists():
        backup = dst.with_name(dst.name + '.bak')
        if not backup.exists():
            shutil.copy2(dst, backup)
    dst.write_text(contents, encoding='utf-8')
    return True


def install(repo: Path) -> list[str]:
    here = Path(__file__).resolve().parent
    repo = repo.resolve()
    required = repo / 'project' / 'qt_app.py'
    if not required.is_file():
        raise FileNotFoundError(f'Project not found: {required}')
    changes: list[str] = []
    for relative in [
        'project/mill_dynamics.py',
        'project/mill_visual_ui.py',
        'tests/test_mill_dynamics_animation.py',
        'doc/research/18-mill-animation-analysis.md',
        'doc/plan/18-mill-animation-redesign.md',
    ]:
        src = here / relative
        if write_file(repo / relative, src.read_text(encoding='utf-8')):
            changes.append(relative)
    for relative, block in ADDITIONS.items():
        path = repo / relative
        current = path.read_text(encoding='utf-8') if path.is_file() else ''
        first = block.splitlines()[0]
        if first not in current:
            if write_file(path, current.rstrip() + '\n\n' + block.rstrip() + '\n'):
                changes.append(relative)
    return changes


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python apply_animation_redesign.py <project-directory>')
        raise SystemExit(2)
    changed = install(Path(sys.argv[1]))
    print('Installed: ' + (', '.join(changed) if changed else 'already up to date'))
    print('Git was not changed.')
