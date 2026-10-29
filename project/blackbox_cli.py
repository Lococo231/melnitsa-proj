"""JSON -> Black Box -> JSON для внешнего приложения/АСУ ТП.

Пример: python blackbox_cli.py example_config.json out.json
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from model import simulate_wear, quality_at, initial_cohorts, recommends


def process(payload:dict)->dict:
    run=simulate_wear(payload)
    return {
        "schema_version":"1.0",
        "provenance":"расчётная модель; не натурные измерения",
        "throughput":run["throughput"],
        "quality_initial":{k:v for k,v in quality_at(payload,initial_cohorts(payload)).items() if k in ("r008","r0045","blaine_proxy","residence_min")},
        "quality_final":{k:v for k,v in quality_at(payload,run["cohorts"]).items() if k in ("r008","r0045","blaine_proxy","residence_min")},
        "wear_trajectory":run["rows"],
        "diameter_trajectory":run["diameter_history"],
        "wear_coefficient_trajectory":run["coefficient_history"],
        "fraction_mass_trajectory":run["fraction_mass_history"],
        "fractions_final":run["cohort_results"],
        "recommendations":recommends(payload,run),
        "grinding_diagram":quality_at(payload,run["cohorts"])["samples"],
    }


def main():
    ap=argparse.ArgumentParser(description="Расчётный Black Box помола и износа")
    ap.add_argument("input_json",type=Path)
    ap.add_argument("output_json",type=Path)
    args=ap.parse_args()
    data=json.loads(args.input_json.read_text(encoding="utf-8"))
    args.output_json.write_text(json.dumps(process(data),ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Результат: {args.output_json}")

if __name__=="__main__":main()
