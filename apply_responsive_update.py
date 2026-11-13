"""Apply the stage navigation, true responsive forms and sharp fraction plots.

Windows / PyCharm:
py -3.11 apply_responsive_update.py C:\\Users\\Lococo\\Desktop\\melnitsa

No git operations; generated backups are untracked .bak files.
"""
from __future__ import annotations

import ast
from pathlib import Path
import shutil
import sys

from apply_staged_results import install as install_stages
from apply_staged_results import prepare as stage_prepare
from patch_renderer import patch_renderer

OLD_IMPORT = ("from staged_results_ui import install as install_staged_results_ui\n"
              "install_staged_results_ui(MillWindow)")
NEW_IMPORT = OLD_IMPORT + ("\nfrom responsive_ui import install as install_responsive_ui\n"
                           "install_responsive_ui(MillWindow)")

DOCS = {
    'README.md': '''## Адаптивная ширина колонок и чёткие графики фракций (13.11.2026)

- Кнопки показа/скрытия и разделитель QSplitter изменяют реальную ширину страниц.
  Формы в узкой левой панели переносят подписи над числовыми полями; при
  расширении возвращаются к более компактному размещению. Убрано жёсткое
  ограничение 345 px. Сохраняются значения полей и обработчики событий.
- Табличные результаты не заставляют весь раздел сохранять исходную ширину:
  когда сит слишком много, горизонтальная прокрутка есть внутри таблицы.
- «Мелющие тела» → «Износ фракций»: добавлен выбор показателя
  (диаметры / массы / удельный износ). Вместо трёх тесных PNG отображается
  один большой график. Изображение рисуется без растяжения сторон; Matplotlib
  создаёт PNG под текущий размер панели с высоким разрешением.
- Перемещение временного курсора в PNG учитывает поля сохранённого
  изображения, поэтому линия часа совпадает с осью X после изменения ширины.

### Проверка после обновления

```powershell
python -m pytest -q tests/test_responsive_installer.py tests/test_responsive_renderer.py tests/test_responsive_qt.py
```

На Windows проверьте ширину левой колонки 250–300 px и широкую колонку
600+ px, изменение ширины правой части, прокрутку таблицы проб и график
износа каждой из двух камер. Эта проверка обязательна перед внедрением.
''',
    'AGENTS.md': '''## Фаза 12: адаптивность Qt и качество временных графиков

- `project/responsive_ui.py` устанавливается ПОСЛЕ `staged_results_ui`.
  Он настраивает размеры QWidget/QScrollArea/QFormLayout, а не копирует
  оригинальные формы: все поля и обработчики должны оставаться прежними.
- QFormLayout: `WrapAllRows` в узкой панели, `WrapLongRows` в широкой;
  избегать `minimumWidth` > 0 у больших контейнеров и формы со слайдерами.
- `project/multicore_render.py` принимает необязательный `target_size`,
  создает высокоразрешённое PNG в отдельном процессе, без Qt в нём.
- `HourPlotImage` — QPainter с сохранением пропорций и верной координатой
  курсора; `setScaledContents(True)` не использовать для научных графиков.
- Износ фракций: одна выбранная метрика за раз, перерендер при существенном
  изменении размера в отложенном фоновом процессе.
- Проверять вручную Windows/PySide6 и локальные тесты. GitHub Actions
  не восстанавливать, никаких коммитов без прямой команды пользователя.
''',
    'CHANGELOG.production.md': '''## 13.11.2026 — адаптивные колонки и чёткий износ фракций

- Удалено прежнее принудительное ограничение ширины левой панели 345 px.
- Перенос строк QFormLayout в зависимости от текущей ширины; согласованы
  `QSizePolicy`, `QScrollArea.widgetResizable`, QSplitter и табличная прокрутка.
- Исправлено искажение PNG: графики больше не растягиваются без сохранения
  пропорций; курсор часа преобразуется через фактический прямоугольник рисунка.
- Выбор одного из трёх показателей износа фракций вместо трёх сжатых графиков.
- Чёткий фоновой PNG под актуальный размер колонки (до 2x по пикселям),
  перерендер с дебаунсом после существенного изменения ширины.
- Добавлены ручные Qt-тесты и тесты разрешения Agg. GitHub Actions не включены.
''',
    'doc/todo.md': '''## Фаза 12 — проверка адаптивности и качества графиков

- [ ] Windows: перетащить QSplitter в узкое и широкое положения; поля, подписи,
  слайдеры, секции и таблицы должны корректно изменять ширину.
- [ ] Windows: проверить числовые остатки R0,045 и горизонтальную прокрутку.
- [ ] Проверить график износа фракций при узкой/широкой панели, переключении
  трёх метрик, камер и выборе часа; отсутствие растяжения и нечётких подписей.
- [ ] При необходимости замерить производительность фонового PNG на 4K/HiDPI.
- [ ] Прогнать локально тесты `test_responsive_*`; CI отключён по требованию.
''',
}


def _replace_once(source: str, old: str, new: str, name: str) -> str:
    if new in source:
        return source
    n = source.count(old)
    if n != 1:
        raise RuntimeError(f'{name}: точка подключения отсутствует или повторяется ({n}).')
    return source.replace(old, new)


def _write(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding='utf-8') == content:
        return False
    if path.exists():
        backup = path.with_name(path.name + '.bak')
        if not backup.exists():
            shutil.copy2(path, backup)
    path.write_text(content,encoding='utf-8')
    return True


def install(repo: Path) -> None:
    repo = repo.expanduser().resolve()
    here = Path(__file__).resolve().parent
    qt_file = repo / 'project/qt_app.py'
    renderer_file = repo / 'project/multicore_render.py'
    if not qt_file.exists() or not renderer_file.exists():
        raise FileNotFoundError('Не найден исходный Qt-проект с multicore_render.py. Выполните git pull origin main.')

    # Preflight EVERYTHING, before any backups or repository file mutations.
    _, staged_qt = stage_prepare(repo,here)
    final_qt = _replace_once(staged_qt, OLD_IMPORT, NEW_IMPORT,'qt_app.py')
    final_renderer = patch_renderer(renderer_file.read_text(encoding='utf-8'))
    for name,code in (
        ('qt_app.py',final_qt),('multicore_render.py',final_renderer),
        ('staged_results_ui.py',(here/'project/staged_results_ui.py').read_text(encoding='utf-8')),
        ('responsive_ui.py',(here/'project/responsive_ui.py').read_text(encoding='utf-8')),
    ):
        ast.parse(code,filename=name)
    print('Предварительная проверка исходников: OK')

    # Adds grouped tabs when absent and updates the older staged module if present.
    install_stages(repo)
    changed=[]
    if _write(qt_file, final_qt): changed.append('project/qt_app.py')
    if _write(renderer_file, final_renderer): changed.append('project/multicore_render.py')
    for relative in ('project/responsive_ui.py','patch_renderer.py',
                     'tests/test_responsive_installer.py',
                     'tests/test_responsive_renderer.py',
                     'tests/test_responsive_qt.py',
                     'doc/plan/12-responsive-layout.md',
                     'doc/research/06-qt-responsive-diagnostics.md'):
        source=here/relative
        if _write(repo/relative,source.read_text(encoding='utf-8')):
            changed.append(relative)
    for relative,addition in DOCS.items():
        target=repo/relative
        previous=target.read_text(encoding='utf-8') if target.exists() else ''
        if addition.split('\n',1)[0] not in previous:
            if _write(target,previous.rstrip()+'\n\n'+addition):
                changed.append(relative)
    print('Обновление готово; изменено файлов:',len(changed))
    for path in changed: print('  ',path)
    print('В GitHub ничего не отправлено. Тесты запускаются локально.')


if __name__=='__main__':
    if len(sys.argv)!=2:
        print('Использование: py -3.11 apply_responsive_update.py <путь-к-melnitsa>')
        raise SystemExit(2)
    install(Path(sys.argv[1]))
