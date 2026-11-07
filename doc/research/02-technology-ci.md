# Исследования: PySide6, тесты, CI

## Технологии и архитектурные решения
- [Qt for Python](https://doc.qt.io/qtforpython-6/): PySide6 — официальные Python bindings Qt6; UI, сигналы/слоты, QTimer, QTableWidget. Вызовы долгих расчётов не должны блокировать интерфейс; при усложнении перейти на worker с сигналами.
- [Matplotlib embedding in Qt](https://matplotlib.org/stable/gallery/user_interfaces/embedding_in_qt_sgskip.html): FigureCanvasQTAgg и NavigationToolbar2QT; перерисовывать существующие canvas, закрывать ресурсы и избегать дублированных таймеров.
- [XlsxWriter](https://xlsxwriter.readthedocs.io/working_with_charts.html): встроенные диаграммы привязываются к диапазонам; тестировать числа, листы, серии, а не только существование XLSX.
- [pytest import modes](https://docs.pytest.org/en/stable/explanation/goodpractices.html), [pytest pythonpath](https://docs.pytest.org/en/stable/reference/reference.html#confval-pythonpath): при плоских импортах модулей из `project/` надо явно включить этот путь. В данной поставке `pytest.ini: pythonpath = project`.
- [GitHub Actions Python](https://docs.github.com/en/actions/tutorials/build-and-test-code/python): матрица версий Python, отладка по шагу установки и traceback первого упавшего теста.

## Подтверждённая причина падения CI (2026-11-07)
GitHub Actions run [41988014649](https://github.com/Lococo231/melnitsa-proj/actions/runs/41988014649), commit `f325ee9b`, обе матрицы Python 3.11/3.13: шаг `Install dependencies` успешен, шаг `Run tests` падает ещё при collection `tests/test_qt_app.py:5` на `from PySide6.QtWidgets import QApplication`:
```
ImportError: libEGL.so.1: cannot open shared object file: No such file or directory
```
Корень — отсутствующая системная runtime-библиотека OpenGL/EGL в Ubuntu runner, а не путь импорта Python. В репозитории **уже существовал** `pytest.ini` с `pythonpath = project`. `QT_QPA_PLATFORM=offscreen` не устраняет отсутствующие ELF shared libraries.

В `.github/workflows/tests.yml` добавлен шаг `apt-get install -y libegl1 libopengl0 libxkbcommon-x11-0 libxcb-cursor0` до установки pip-зависимостей. Это устраняет известную нехватку `libEGL.so.1`; полная зелёная матрица должна быть проверена после push, так как могут проявиться следующие сбои.

## Дополнительные риски
1. Smoke-тесты создают `QApplication`: проверять единственный экземпляр, завершение и работу offscreen.
2. Незакреплённые верхние диапазоны `>=` могут в будущем менять окружение; при подтверждённой несовместимости фиксировать версии и оформить constraints-файл.
3. Проверять оба job по логам и полный запуск pytest; не скрывать падения отключением тестов.

## Минимальная матрица проверок
- `python -m pytest -q` — расчёт, CSV, JSON, Excel, CLI, UI.
- `QT_QPA_PLATFORM=offscreen python -m pytest -q` — Qt smoke без X-сервера.
- `python -m compileall -q main.py project` — синтаксис и циклы импорта на уровне компиляции.
- Инварианты: сохранение массы и накопленного выпуска, ввод недопустимых данных, 1/2 камеры, смена материала и L/D, догрузки на границах горизонта, импорт/экспорт, интерактивные таблицы и таймер.
- Раздельные CI job outputs для 3.11/3.13: фиксировать ссылку на failed job и первый traceback.