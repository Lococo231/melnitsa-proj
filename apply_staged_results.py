"""Установка объединённых вкладок результатов в существующий проект.

Использование:
    py -3.11 apply_staged_results.py "C:/Users/Lococo/Desktop/melnitsa"

Без GitHub push/commit. Только локальные изменения и резервные копии.
"""
from __future__ import annotations

import ast
from pathlib import Path
import shutil
import sys


IMPORT_OLD = (
    "from workspace_ui import install as install_workspace_ui\n"
    "install_workspace_ui(MillWindow)"
)
IMPORT_NEW = (
    IMPORT_OLD + "\n"
    "from staged_results_ui import install as install_staged_results_ui\n"
    "install_staged_results_ui(MillWindow)"
)
TABS_OLD = (
    "required = sum(bar.tabSizeHint(i).width() for i in range(bar.count())) + 25"
)
TABS_NEW = (
    "required = sum(bar.tabSizeHint(i).width() for i in range(bar.count()) "
    "if self.tabs.isTabVisible(i)) + 25"
)

ADDITIONS = {
    "README.md": (
        "## Контроль помола и мелющих тел по этапам (13.11.2026)\n\n"
        "Справа результаты сгруппированы по технологическим этапам:\n"
        "- **Контроль помола:** 1. Диаграмма помола → 2. Таблица проб.\n"
        "- **Мелющие тела:** 1. Начальная загрузка → 2. Износ фракций.\n\n"
        "Старые расчёты, данные и объекты PlotPanel не дублируются и не удаляются; "
        "правые индексы вкладок сохраняются для совместимости с обработчиками.\n\n"
        "В таблице проб `R0,045` не был утрачен — расширенная последняя колонка "
        "создавала впечатление отсутствующих значений. "
        "Числовые колонки теперь распределяют ширину равномерно, первые три "
        "имеют фиксированный начальный размер; при нехватке места есть "
        "горизонтальная прокрутка. Запятая используется только в названии сита, "
        "а ключи данных остаются `R0.045, %`.\n\n"
        "Тестирование вручную: `python -m pytest -q tests/test_staged_results_qt.py` "
        "при установленном PySide6. GitHub Actions не включены.\n"
    ),
    "AGENTS.md": (
        "## Фаза 11: группировка результатов PySide6\n\n"
        "- `project/staged_results_ui.py` устанавливается **последним** после "
        "`workspace_ui.install(MillWindow)`; не меняйте порядок.\n"
        "- Объединены только правые страницы: контроль помола (диаграмма → пробы) "
        "и мелющие тела (начальная загрузка → износ).\n"
        "- Сохранить физические виджеты `quality_plot`, `sample_table`, "
        "`start_plot`, `start_table`, `fraction_plot`, `fraction_combo`; "
        "не заменять их фиктивными новыми результатами.\n"
        "- Сохранять индексы внешних QTabWidget: 1/2 являются группами, 4/7 "
        "скрытыми заглушками ради обратной совместимости. "
        "При изменении табличных ключей помнить, что видимый `R0,045` "
        "соответствует ключу словаря `R0.045, %`.\n"
        "- После изменения Qt-архитектуры проверять навигацию и отрисовку "
        "в `tests/test_staged_results_qt.py` локально. GitHub Actions не включать.\n"
    ),
    "CHANGELOG.production.md": (
        "## 13.11.2026 — этапная навигация результатов и исправление столбцов\n\n"
        "- «Диаграмма помола» и «Таблица проб» собраны в «Контроль помола» "
        "(сначала график, затем таблица).\n"
        "- «Начальная загрузка» и «Износ фракций» собраны в «Мелющие тела» "
        "(от начального состава к износу во времени).\n"
        "- Исправлен растянутый столбец R0,045: выравнивание и равномерное "
        "распределение ширины числовых колонок, горизонтальная прокрутка.\n"
        "- Скрытые вкладки исключены из расчёта ширины строки внешних вкладок.\n"
        "- Сохранены прежние объекты графиков, таблиц и совместимые индексы Qt. "
        "Добавлены локальные GUI-тесты; GitHub Actions не восстановлены.\n"
    ),
    "doc/todo.md": (
        "## Фаза 11 — проверка этапных вкладок\n\n"
        "- [ ] Проверить в Windows/PyCharm новую вкладку «Контроль помола»: "
        "диаграмма → таблица проб, R0,045, прокрутка и размеры столбцов.\n"
        "- [ ] Проверить вкладку «Мелющие тела»: начальная загрузка → "
        "износ фракций, общий час работы и выбор камеры.\n"
        "- [ ] Проверить скрытие правой/левой панели и размеры окна, "
        "переключение в симуляцию/рекомендации/журнал.\n"
        "- [ ] Запустить локально `tests/test_staged_results_qt.py` с PySide6; "
        "не восстанавливать GitHub Actions.\n"
    ),
}


def replace_once(source: str, old: str, new: str, file: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"{file}: ожидалась одна точка подключения, найдено {count}. "
            "Обновите репозиторий до последнего main или проверьте локальные изменения."
        )
    return source.replace(old, new)


def prepare(repo: Path, source_dir: Path):
    qt_path = repo / "project/qt_app.py"
    if not qt_path.is_file():
        raise FileNotFoundError(f"Не найден {qt_path}")
    original = qt_path.read_text(encoding="utf-8")
    updated = replace_once(original, IMPORT_OLD, IMPORT_NEW, "qt_app.py")
    updated = replace_once(updated, TABS_OLD, TABS_NEW, "AdaptiveTabs")
    # Validate syntax before changing any files.
    ast.parse(updated, filename=str(qt_path))
    extra = source_dir / "project/staged_results_ui.py"
    if not extra.is_file():
        raise FileNotFoundError(f"В архиве нет {extra}")
    ast.parse(extra.read_text(encoding="utf-8"), filename=str(extra))
    return qt_path, updated


def write_if_changed(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    if path.exists():
        # Original first-time snapshot, without suffixes that may be tracked.
        backup = path.with_name(path.name + ".bak")
        if not backup.exists():
            shutil.copy2(path, backup)
    path.write_text(content, encoding="utf-8")
    return True


def install(repo: Path):
    repo = repo.resolve()
    here = Path(__file__).resolve().parent
    qt_path, updated = prepare(repo, here)
    changed = []
    if write_if_changed(qt_path, updated):
        changed.append("project/qt_app.py")
    for relative in (
        "project/staged_results_ui.py",
        "tests/test_staged_results_qt.py",
        "doc/plan/11-grouped-results.md",
    ):
        source = here / relative
        if not source.is_file():
            raise FileNotFoundError(f"В архиве нет {source}")
        if write_if_changed(repo / relative, source.read_text(encoding="utf-8")):
            changed.append(relative)
    for relative, addition in ADDITIONS.items():
        path = repo / relative
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        heading = addition.split("\n", 1)[0]
        if heading not in current:
            if write_if_changed(path, current.rstrip() + "\n\n" + addition):
                changed.append(relative)
    print("Обновление установлено:", repo)
    if changed:
        print("Изменено:\n  " + "\n  ".join(changed))
    else:
        print("Новых изменений нет: пакет уже установлен.")
    print("Коммит и GitHub push не выполнялись.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Использование: py -3.11 apply_staged_results.py "C:\\Users\\Lococo\\Desktop\\melnitsa"')
        raise SystemExit(2)
    install(Path(sys.argv[1]))
