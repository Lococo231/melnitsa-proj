"""Калибровка базового удельного расхода по заводскому массовому балансу.

Не заменяет оценку многопараметрических коэффициентов и требует верификации
достоверности реестра догрузок / выбраковки / текущих запасов.
"""
from __future__ import annotations
import csv
import io

REQUIRED=["period","production_t","start_media_t","reload_t","end_media_t","removed_media_t"]


def parse_history_csv(data:bytes)->list[dict]:
    try:
        content=data.decode("utf-8-sig")
    except UnicodeError:
        content=data.decode("cp1251")
    rdr=csv.DictReader(io.StringIO(content),delimiter=";" if content.count(";")>content.count(",") else ",")
    if not rdr.fieldnames or any(k not in rdr.fieldnames for k in REQUIRED):
        raise ValueError("Для CSV нужны поля: "+", ".join(REQUIRED))
    rows=[]
    for n,rr in enumerate(rdr,2):
        row={"period":str(rr["period"])}
        for k in REQUIRED[1:]:
            try:row[k]=float(str(rr[k]).replace(",","."))
            except (TypeError,ValueError) as exc: raise ValueError(f"Строка {n}: нечисловое значение в {k}") from exc
            if row[k]<0:raise ValueError(f"Строка {n}: {k} <0")
        if row["production_t"] <= 0:raise ValueError(f"Строка {n}: выпуск должен быть >0")
        # Баланс: начало + догрузка = конец + выбраковка + истёртая масса
        row["loss_t"]=(row["start_media_t"]+row["reload_t"]-row["end_media_t"]-row["removed_media_t"])
        if row["loss_t"]< -0.001:raise ValueError(f"Строка {n}: отрицательный износ; проверьте остатки и догрузки")
        row["gmcr_g_t"]=row["loss_t"]*1e6/row["production_t"]
        rows.append(row)
    if not rows:raise ValueError("В CSV нет периодов")
    return rows


def summarize_history(rows:list[dict])->dict:
    product=sum(x["production_t"] for x in rows)
    lost=sum(x["loss_t"] for x in rows)
    return {"periods":len(rows),"production_t":product,"wear_t":lost,"gmcr_g_t":lost*1e6/product,
            "min_g_t":min(x["gmcr_g_t"] for x in rows),"max_g_t":max(x["gmcr_g_t"] for x in rows)}


DEMO_CSV=("period,production_t,start_media_t,reload_t,end_media_t,removed_media_t\n"
          "Смена 01,864,195,0,194.92,0\n"
          "Смена 02,860,194.92,0.5,195.34,0\n"
          "Смена 03,870,195.34,0,195.25,0\n")
