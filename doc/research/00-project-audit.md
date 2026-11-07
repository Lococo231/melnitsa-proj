# Срез проекта и требований (2026-11-07)

## Проверено в GitHub `Lococo231/melnitsa-proj`, ветка `main`
- README: приложение PySide6, один барабан 1–2 камеры, Matplotlib, XlsxWriter; износ/качество — демонстрационные без калибровки.
- `main.py` динамически добавляет `project/` в `sys.path` перед `from qt_app import main`.
- `tests/test_model.py` импортирует `model` и `calibration` напрямую; в репозитории уже есть `pytest.ini` с `pythonpath = project`, поэтому ошибка пути импорта не подтверждена. Лог GitHub Actions [run 41988014649](https://github.com/Lococo231/melnitsa-proj/actions/runs/41988014649) подтвердил `ImportError: libEGL.so.1` в `tests/test_qt_app.py` при импорте `PySide6.QtWidgets` на Python 3.11 и 3.13. Решение — установить системные Qt/EGL библиотеки в workflow перед тестами.
- `.github/workflows/tests.yml`: Ubuntu, Python 3.11/3.13, `QT_QPA_PLATFORM=offscreen`, установка `requirements-dev.txt`, запуск pytest.
- `requirements.txt`: PySide6>=6.7,<7, matplotlib>=3.10,<4, XlsxWriter>=3.1,<4; dev: pytest>=8,<10.
- `project/model.py`: исходные примеры, когортный прогноз массы/диаметра, Q(t), контроль геометрии, грансостава и коэффициентов. `project/ui_data.py`: типы строк/дефолты, проверка CSV/JSON.
- Документ `docs/MODEL_AND_DOMAIN.md` уже описывает формулы и физические ограничения; не дублировать вразрез.

## Из предыдущих итераций проекта
Потребности: анимировать один/два отсека без наложения; отобразить длины камеры, графики ситовых остатков R0.08, R0.045, Blaine, выработки Q(t), износа, перечень догрузок; редактирование без модальных окон; импорт/экспорт. Исторически обсуждались 4 заводские мельницы и их показатели, но текущая кодовая база реализует **одну мельницу за запуск** — расширение на 4 требует отдельной фазы и изменения схемы.
Примерные технологические цели из обсуждений: R0.08 ≤ 2%; Blaine 3200–3500 см²/г; R0.045 около 33–36%. Это **контекст заданного процесса, не универсальные нормативы для всех цементов**. Пример №3 R0.08=1.21%, Blaine=3551, R0.045=31.6 (возможно выход за согласованные цели); не использовать как калибровочный факт без протоколов.

## Не проверено / не делать ложных выводов
Последний лог падения CI получен, но **результат нового workflow ещё не получен**. Полный набор тестов локально не запущен в копии репозитория. Не объявлять CI исправленным до успешного прогона 3.11/3.13.

## Ссылки в коде
https://github.com/Lococo231/melnitsa-proj/blob/main/README.md
https://github.com/Lococo231/melnitsa-proj/blob/main/project/model.py
https://github.com/Lococo231/melnitsa-proj/blob/main/project/ui_data.py
https://github.com/Lococo231/melnitsa-proj/blob/main/tests/test_model.py
https://github.com/Lococo231/melnitsa-proj/blob/main/.github/workflows/tests.yml
https://github.com/Lococo231/melnitsa-proj/blob/main/docs/MODEL_AND_DOMAIN.md