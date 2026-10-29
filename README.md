# Melnitsa Project — моделирование цементной мельницы

Python-модель помола и износа мелющих тел с веб-интерфейсом Streamlit, расчётом догрузок и выгрузкой Excel.

> Исследовательский прототип: расчётные коэффициенты необходимо калибровать по производственным замерам. Примеры не являются реальными данными предприятия.

## Структура
- `project/` — Streamlit, математическое ядро, Excel, JSON CLI и калибровка.
- `examples/` — пример входных параметров, результатов и Excel.
- `tests/` — автоматические тесты.
- `docs/` — предметная область, постановка задачи и формулы.
- `legacy_web/` — предыдущая версия браузерного симулятора.
- `.github/workflows/` — автоматическая проверка тестов.

## Запуск в Linux
```bash
git clone https://github.com/Lococo231/melnitsa-proj.git
cd melnitsa-proj
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run project/app.py
```

## Запуск Black Box по JSON
```bash
mkdir -p outputs
python project/blackbox_cli.py examples/example_config.json outputs/result.json
```

## Пример Excel
```bash
python project/run_example.py
```

## Тесты
```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

**Важно:** не публикуйте реальные заводские данные без разрешения предприятия.
