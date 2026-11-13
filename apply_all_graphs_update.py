"""Apply combined stages + responsive forms + all adaptive plot rendering.

Run from a Windows PyCharm terminal with project path as the only argument.
Idempotent; no git commit/push. Creates .bak backups for edited files.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys

from apply_responsive_update import install as install_responsive
from apply_responsive_update import _write

IMPORT = ('from responsive_ui import install as install_responsive_ui\n'
          'install_responsive_ui(MillWindow)')
NEW_IMPORT = IMPORT + ('\nfrom adaptive_graphs_ui import install as install_adaptive_graphs_ui\n'
                       'install_adaptive_graphs_ui(MillWindow)')

OLD_TARGET = '''    if target_size is not None:
        # Fraction charts are prepared for the available canvas aspect ratio.
        pane_width, pane_height = target_size
        for job in jobs:
            if job['id'].startswith('fraction_'):
                job['render_px'] = (2*int(pane_width), 2*int(pane_height))'''
ALL_TARGET = '''    if target_size is not None:
        # ALL Matplotlib Agg figures must match the actual visible Qt viewport:
        # simulation, fraction wear, event history and forecast. The PNG has
        # twice the logical pixels, avoiding blurry upscaling on HiDPI screens.
        pane_width, pane_height = target_size
        if pane_width <= 0 or pane_height <= 0:
            raise ValueError('Размер графика должен быть положительным')
        render_size = (2 * int(pane_width), 2 * int(pane_height))
        for job in jobs:
            job['render_px'] = render_size'''

DOCS = {
    'README.md': '''## 14.11.2026 — разрешение всех диаграмм под окно

- Все PNG-графики симуляции (6), истории (3), износа фракций и прогноза
  подстраиваются под реальные размеры *видимой* области Qt. Matplotlib Agg
  создаёт изображение с удвоенным числом пикселей для чёткости при HiDPI.
- При перетаскивании QSplitter обновляется разрешение только открытой
  диаграммы (или открытой группы), с отложенным запуском 360 мс.
  Расчёт износа/качества из-за изменения размера окна НЕ повторяется.
- Для встроенных QtAgg-графиков (обзор, помол, начальная загрузка)
  используется нативное изменение размера FigureCanvas и `draw_idle`.
- Заполнение колонок и две этапные группы справа включены в обновление:
  «Контроль помола» (диаграмма/пробы) и «Мелющие тела» (загрузка/износ).
- Изображение показывается с сохранением пропорций, курсор часа привязан
  к оси времени. Если параметры изменились, старые результаты не подставляются.

Локальные тесты: `python -m pytest -q tests/test_all_graph_resolutions.py`
и, при наличии PySide6, `tests/test_all_graphs_qt.py`.
Полный тест Windows/HiDPI и визуальная проверка обязателен. GitHub Actions отключён.
''',
    'AGENTS.md': '''## Фаза 13 — все адаптивные графики

- Порядок Qt-модулей: `production_ui` → `workflow_ui` → `timeline_ui` →
  `multicore_ui` → `workspace_ui` → `staged_results_ui` → `responsive_ui` →
  `adaptive_graphs_ui` (последний).
- `multicore_render.py` поддерживает `target_size` для каждой семьи изображений
  (sim*, history*, fraction_*, forecast*). Агент не должен возвращать
  жёстко заданные растровые размеры для отображаемых графиков.
- `HourPlotImage` рисуется QPainter с сохранением пропорций и преобразованием
  положения курсора через реальный прямоугольник картинки.
- События Resize/Show должны приводить к отложенному обновлению *видимого*
  графика, но не к повторному вызову модели и не к неконтролируемому запуску
  новых ProcessPoolExecutor при каждом пикселе перетаскивания.
- Matplotlib QtAgg оставлять в GUI thread. Загружаемые PNG создавать
  только в фоновом потоке/процессах (Agg без Qt).
- Проверки локально; GitHub Actions не восстанавливать; `.bak` и
  `AGENTS.local.md` не коммитить.
''',
    'CHANGELOG.production.md': '''## 14.11.2026 — адаптивное разрешение всех графиков

- Включены предыдущие некоммиченные фазы 11–12: этапные группы справа,
  перенос подписей форм, отзывчивые разделители Qt и чёткий износ фракций.
- Все PNG-графики симуляции, истории и износа пересоздаются в 2x размере
  фактической видимой области, вместо масштабирования фиксированных 1188×242.
- Подключён `adaptive_graphs_ui.py`: отслеживание resize/show, 360мс debounce,
  фоновое рисование только открытых групп, проверка поколения симуляции и
  защита от устаревших размеров.
- Встроенные QtAgg-графики обновляются через `draw_idle` с нативным DPI.
- Добавлены локальные тесты точного разрешения и интерфейса; GitHub Actions
  не включались. Нужна визуальная проверка на Windows/HiDPI.
''',
    'doc/todo.md': '''## Фаза 13 — разрешение графиков на Windows

- [ ] Проверить все графики при ширине правой колонки 350, 650, 1100 пикселей,
  включая диаграмму помола, износ, обзор, симуляцию и журнал.
- [ ] Проверить 100%, 125%, 150%, 200% DPI и перенос окна между мониторами.
- [ ] Проверить курсор часа после изменения размеров графика и отсутствие
  размытия/обрезки легенд, подписей и таблиц проб.
- [ ] Проверить, что при перетаскивании разделителя модель не пересчитывается,
  а `ProcessPoolExecutor` не запускает десятки повторных задач.
- [ ] Прогнать локальные тесты `test_all_graph_resolutions.py`,
  `test_all_graphs_qt.py`, `test_responsive_*.py` и `test_staged_*.py`.
''',
}


def replace_once(text, old, new, path):
    if new in text:
        return text
    if text.count(old) != 1:
        raise RuntimeError(f'{path}: невозможно найти единственную точку исправления')
    return text.replace(old, new)


def install(repo: Path):
    repo = repo.expanduser().resolve()
    here = Path(__file__).resolve().parent
    # Preflight before any changes. The old installer is still idempotent.
    extra = here / 'project/adaptive_graphs_ui.py'
    ast.parse(extra.read_text(encoding='utf-8'), filename=str(extra))
    install_responsive(repo)

    qt = repo / 'project/qt_app.py'
    updated = replace_once(qt.read_text(encoding='utf-8'), IMPORT, NEW_IMPORT, str(qt))
    ast.parse(updated, filename=str(qt))
    renderer = repo / 'project/multicore_render.py'
    code = renderer.read_text(encoding='utf-8')
    code = replace_once(code, OLD_TARGET, ALL_TARGET, str(renderer))
    code = code.replace('min(3200, int(pixel_w))', 'min(6400, int(pixel_w))')
    code = code.replace('min(1900, int(pixel_h))', 'min(3600, int(pixel_h))')
    ast.parse(code, filename=str(renderer))
    changed = []
    if _write(qt, updated):
        changed.append('project/qt_app.py')
    if _write(renderer, code):
        changed.append('project/multicore_render.py')
    for relative in (
        'project/adaptive_graphs_ui.py', 'tests/test_all_graph_resolutions.py',
        'tests/test_all_graphs_qt.py', 'doc/plan/13-all-graphs-adaptive-resolution.md',
    ):
        text = (here / relative).read_text(encoding='utf-8')
        if _write(repo / relative, text):
            changed.append(relative)
    for relative, extra_docs in DOCS.items():
        path = repo / relative
        existing = path.read_text(encoding='utf-8') if path.exists() else ''
        title = extra_docs.split('\n', 1)[0]
        if title not in existing:
            if _write(path, existing.rstrip() + '\n\n' + extra_docs):
                changed.append(relative)
    print('Адаптивные графики установлены. Обновлено:', len(changed))
    for name in changed:
        print(' ', name)
    print('Данные мельницы не изменялись, GitHub не затронут.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Использование: py -3.11 apply_all_graphs_update.py <папка-проекта>')
        raise SystemExit(2)
    install(Path(sys.argv[1]))
