# Исследование: упаковка PySide6-приложения в один Windows EXE

Дата: 14.11.2026

## Задача

Передавать сотруднику `CementMill.exe`, не отправляя исходный GitHub-репозиторий,
Python или `.venv`. Поддержать PySide6 QtWidgets, Matplotlib QtAgg/Agg, XlsxWriter,
многопроцессный поиск коррекции (`ProcessPoolExecutor(spawn)`) и модельные модули
в каталоге `project/`.

## Подтверждённые способы

### 1. PyInstaller (выбран для первой рабочей сборки)

- Поддерживает `--onefile`, `--windowed`, `--paths`, `--collect-all` и `--hidden-import`.
- В `--onefile` при запуске распаковывает библиотеки во временный каталог, поэтому
  первый старт медленнее. Воспользуйтесь `--onedir` для отладки отсутствующих Qt DLL.
- Выполнять сборку на **Windows** под нужную архитектуру (обычно Windows x64).
- Для `multiprocessing` вызвать `freeze_support()` до импортов GUI, иначе возможны
  рекурсивные запуски главного EXE при создании worker-процессов.
- Параметры сборки хранятся в `scripts/build_windows.ps1`; для обычного пользователя
  есть `build_windows.cmd`.

Официальная документация:
- https://pyinstaller.org/en/stable/usage.html
- https://pyinstaller.org/en/stable/operating-mode.html
- https://pyinstaller.org/en/latest/common-issues-and-pitfalls.html

### 2. Nuitka / `pyside6-deploy` (альтернатива)

Qt официально предлагает `pyside6-deploy`: это обёртка над компилятором Nuitka.

```
py -3.11 -m pip install nuitka ordered-set zstandard
pyside6-deploy --mode onefile main.py
```

На современных версиях pyside6-deploy режим `standalone` может быть режимом по
умолчанию, поэтому `--mode onefile` нужно указывать явно. Nuitka обычно собирает
дольше, но даёт бинарник, не требующий отдельно установленного Python.

Официальные источники:
- https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html
- https://doc.qt.io/qtforpython-6/deployment/deployment-nuitka.html

### 3. Папка `--onedir` → ZIP

Самый простой диагностический вариант: `dist/CementMill/CementMill.exe` плюс DLL
и Qt-плагины в той же папке. В качестве единственного файла для передачи можно
передать `CementMill.zip`, куда упакована папка целиком. Распаковать перед запуском.
Обычно запускается быстрее, чем `onefile`, потому что не требует распаковки из EXE.

## Особые риски нашего приложения

1. **Qt platform plugin:** должен присутствовать плагин `windows`; PyInstaller
   обычно подтягивает Qt-плагины через встроенные hooks. При ошибке `could not
   load Qt platform plugin windows` проверить `--onedir` и PySide6/Qt зависимости.
2. **Matplotlib fonts/backends:** сборка включает `matplotlib` data и скрытые
   backend-импорты (`backend_qtagg`, `backend_agg`).
3. **Отдельные процессы:** `main.py` содержит `freeze_support()` в `__main__` до
   импорта `qt_app`. Python worker-модули не должны создавать `QApplication`.
4. **Excel:** выборочный экспорт использует тот же `XlsxWriter`, что основной,
   чтобы не увеличивать EXE ещё одной Excel-библиотекой.
5. **Отсутствующие ресурсы:** файл ресурсов нужно явно включать в сборку, если
   программа начнёт открывать иконки, документы или референсный HTML по пути.
6. **Windows Defender / SmartScreen:** неподписанный новый EXE может потребовать
   ручного подтверждения; для реальной рассылки рекомендуется подпись кода.
7. **Разрешения на запись:** отчёты и пользовательские конфигурации сохранять
   вне временной директории распаковки; использовать диалог сохранения.

## Проверка выпуска

- Собрать `OneDir` и запустить на чистой Windows без Python.
- Проверить импорт JSON/CSV, экран, графики, 2+ симуляции, процессы поиска
  догрузки, Excel/JSON export.
- Собрать `OneFile`; проверить второй компьютер, включая 125/150% DPI.
- Проверить, что выбор файла экспорта не перезаписывает встроенные ресурсы.
- Код не подписан; нельзя утверждать, что Windows Defender везде пропустит его.

Фактическую Windows-сборку **не выполняли** в Linux-контейнере.
