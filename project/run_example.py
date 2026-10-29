"""Сформировать демонстрационные JSON и XLSX в папке examples/."""
import json
from pathlib import Path
from model import default_config, simulate_wear, quality_at
from excel_export import export_excel

out = Path(__file__).resolve().parent.parent / 'examples'
out.mkdir(parents=True, exist_ok=True)
cfg = default_config()
run = simulate_wear(cfg)
quality = quality_at(cfg, run['cohorts'])
(out / 'example_report.xlsx').write_bytes(export_excel(cfg, run))
(out / 'example_config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
(out / 'example_results.json').write_text(json.dumps({
    'wear_t': run['total_wear_t'],
    'quality': {k: quality[k] for k in ('r008', 'r0045', 'blaine_proxy')}
}, ensure_ascii=False, indent=2), encoding='utf-8')
print('Пример Excel:', out / 'example_report.xlsx')
