"""Install live preview and improved mill animations; no Git changes."""
from __future__ import annotations

import ast
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parent
FILES=[
    'project/mill_dynamics.py','project/mill_visual_ui.py',
    'project/live_preview_core.py','project/live_multicore_ui.py',
    'tests/test_mill_dynamics.py','tests/test_live_preview_core.py',
    'tests/test_live_multicore_qt.py','tests/test_visual_installer.py',
    'doc/plan/16-live-preview-and-drum-motion.md',
    'doc/research/08-drum-motion-reference.md',
]
ANCHOR='install_operator_workflow_ui(MillWindow)'
ADDITION=(ANCHOR+'\nfrom live_multicore_ui import install as install_live_multicore_ui\n'
          'install_live_multicore_ui(MillWindow)')
DOCUMENTS={
'README.md':'''## Фаза 16 — движение мелющих тел и многопроцессные превью (14.11.2026)

- Меню «Как работает?» показывает поперечный разрез с гравитацией, контактами шаров, взаимодействием со стенкой и частицами клинкера. Продольный разрез показывает перенос материала через камеры с изменением размерных классов.
- Динамическая анимация — учебная приближённая 2D-модель контактов, **не промышленная DEM и не источник реальных прогнозов R0,08/Блейна/износа**. Расчётные показатели продолжают использовать исходную модель.
- Убрана пустая таблица «Плановые выгрузки (из симуляции)»; реальные операции отображаются в автоматическом журнале. Прокрутка колесом мыши не переключает QComboBox графиков.
- Вкладка «Обзор» имеет свой период наработки в часах, не связанный с днями и часами на вкладке «Симуляция работы». Нижний часовой ползунок выбирает только точку просмотра на графике.
- Изменение параметров вызывает задержанный пересчёт в ProcessPoolExecutor (spawn): износ, проверка качества и рекомендации считаются в рабочих процессах (до 4 ядер). Изменения во время перетаскивания объединяются, устаревшие результаты не отображаются.
- Полный подбор комбинированных догрузок выполняется только по «Пуск», не от каждого движения ползунка. QtAgg рисуется только основным GUI-потоком; PNG по-прежнему готовятся фоновыми процессами.

### Windows

После `git pull` (только после коммита изменений) или установки обновления запустить `main.py`. Для локальной проверки: `python -m pytest -q tests/test_mill_dynamics.py tests/test_live_preview_core.py tests/test_visual_installer.py tests/test_live_multicore_qt.py`.

См. `doc/research/08-drum-motion-reference.md` и `doc/plan/16-live-preview-and-drum-motion.md`. Полный запуск в Windows/PySide6 ещё требуется проверить.''',
'AGENTS.md':'''## Фаза 16 — моделирование движения загрузки и live preview

- Подключать последним `live_multicore_ui.install(MillWindow)` после `operator_workflow_ui.install`.
- Модель движения `mill_dynamics.py` независима от Qt, представляет ограниченную 2D-схему контактов; не передавать её параметры столкновений в заводскую кинетику износа без калибровки.
- `live_preview_core.py` выполняет `simulate_wear`, `quality_at`, `recommends` в spawn-процессах, использует ограниченное число работников. Qt-холст и виджеты строго в главном потоке.
- Ползунки через `schedule()` дебаунсятся, не запускают многоразовую оптимизацию `simulate_operation_timeline(... optimize=True)`. Полную симуляцию запускает только кнопка.
- На «Обзоре» свой горизонт, который не должен менять `simulation_days`/`simulation_hours_per_day` в рабочей конфигурации. Ползунок `hour_spin` — курсор просмотра.
- Сохранять `freeze_support` до загрузки Qt для Windows/PyInstaller. Проверять и локальные тесты, и GUI на Windows. GitHub Actions не восстанавливать; коммит только по отдельной команде.''',
'CHANGELOG.production.md':'''## 14.11.2026 — новая анимация и многопроцессное живое обновление

- Вместо статических шариков реализована двухмерная модель движения с гравитацией, вращением футеровки, контактами шаров, потерями энергии при ударах, частицами клинкера и условным уменьшением размерных классов.
- Добавлен продольный разрез с двумя камерами, межкамерной перегородкой, транспортом материала и сменой механизма помола. Визуализация не приравнивается к промышленному DEM.
- Скрыта дублирующая пустая таблица «Плановые выгрузки (из симуляции)»; реальные операции находятся в журнале.
- В любом выпадающем списке колесо мыши не меняет выбранный график и передаёт прокрутку родительской области.
- В «Обзоре» отдельный горизонт расчёта и отдельный курсор выбранного часа.
- Live-пересчёт `simulate_wear`/`quality_at`/`recommends` выполняется в многопроцессном пуле. 340-мс дебаунс и отбрасывание устаревшего поколения; тяжёлый подбор догрузки остаётся кнопкой «Пуск».
- Добавлены проверки динамики, границ, horizon и установки. Windows Qt GUI ещё не проверен; GitHub не изменялся.''',
'doc/todo.md':'''## Фаза 16 — проверки визуальной модели и live preview

- [ ] На Windows проверить анимации поперечного/продольного разреза, разницу камер, отсутствие прохода шаров друг сквозь друга при нормальном FPS.
- [ ] Проверить, что выпадающий список всех графиков не меняется от колеса мыши, а страница прокручивается.
- [ ] Проверить отдельный период «Обзора» (например, 120 ч) независимо от длительности симуляции; курсор просмотра не запускает новый расчёт.
- [ ] Во время перемещения ползунков мониторить диспетчер задач Windows: отдельные процессы Python, отсутствие блокировки интерфейса, отсутствие длинной очереди устаревших задач.
- [ ] Проверить экспорт XLSX и несколько последовательных симуляций после внедрения новой пересчётной очереди.
- [ ] Реализовать физическую передачу состояния когорт тел между последовательными симуляциями (ещё не решено).'''
}

def patch_once(src:str, old:str, new:str, label:str):
    if new in src:
        return src
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f'{label}: expected 1 anchor, found {count}')
    return src.replace(old,new,1)


def write_if_changed(path:Path, data:str):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_text(encoding='utf-8')==data:
        return False
    if path.exists():
        backup=path.with_name(path.name+'.bak')
        if not backup.exists():shutil.copy2(path,backup)
    path.write_text(data,encoding='utf-8')
    return True


def install(target:Path):
    target=target.resolve()
    entry=target/'project/qt_app.py'
    if not entry.is_file():raise FileNotFoundError('Not a mill project: '+str(entry))
    s=patch_once(entry.read_text(encoding='utf-8'),ANCHOR,ADDITION,'Qt extension')
    ast.parse(s,filename=str(entry))
    for rel in FILES:
        source=ROOT/rel
        if not source.is_file():raise FileNotFoundError(str(source))
        if source.suffix=='.py':ast.parse(source.read_text(encoding='utf-8'),filename=str(source))
    changes=[]
    if write_if_changed(entry,s):changes.append('project/qt_app.py')
    for rel in FILES:
        if write_if_changed(target/rel,(ROOT/rel).read_text(encoding='utf-8')):
            changes.append(rel)
    for rel,section in DOCUMENTS.items():
        file=target/rel
        existing=file.read_text(encoding='utf-8') if file.exists() else ''
        if section.splitlines()[0] not in existing:
            if write_if_changed(file,existing.rstrip()+'\n\n'+section+'\n'):
                changes.append(rel)
    print('Installed visual + multi-core preview update:',target)
    print('\n'.join(' + '+path for path in changes) if changes else 'No changes (already installed).')
    print('No git operations performed.')


if __name__=='__main__':
    if len(sys.argv)!=2:
        print('Usage: python apply_visual_multicore_update.py <repository>')
        raise SystemExit(2)
    install(Path(sys.argv[1]))
