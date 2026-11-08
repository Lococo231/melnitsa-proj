"""pytest после установки дополнения в исходный репозиторий."""
import zipfile
from io import BytesIO

from model import default_config, simulate_wear, quality_at, config_at_time
from production_planning import assessments, plan_reload, starting_media
from excel_export import export_excel


def test_production_plan_computes_without_destructive_changes():
    cfg = default_config()
    cfg['horizon_h'] = 20.
    cfg['step_h'] = 5.
    run = simulate_wear(cfg)
    before = len(cfg['manual_reloads'])
    plan = plan_reload(cfg, run)
    assert plan['total_t'] >= 0
    assert isinstance(plan['feasible'], bool)
    assert before == len(cfg['manual_reloads'])
    assert len(starting_media(cfg)) == len(cfg['media'])
    quality = quality_at(config_at_time(cfg, cfg['horizon_h']), run['cohorts'])
    assert all(isinstance(x['ok'], bool) for x in assessments(cfg, quality))


def test_production_excel_sheets():
    cfg = default_config()
    cfg['horizon_h'] = 20.
    cfg['step_h'] = 5.
    run = simulate_wear(cfg)
    with zipfile.ZipFile(BytesIO(export_excel(cfg, run))) as report:
        wb = report.read('xl/workbook.xml').decode('utf-8')
        for name in ('Пробы_по_длине', 'Начальная_загрузка',
                     'Нормы_и_выпуск', 'План_догрузки_к_концу'):
            assert name in wb
