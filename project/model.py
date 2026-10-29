"""Расчётное ядро Black Box: помол и износ мелющих тел.

Инженерный прототип: параметры по умолчанию иллюстративные, а не заводская калибровка.
Обозначения и единицы подробно описаны в README.md.
"""
from __future__ import annotations

from copy import deepcopy
import math
from dataclasses import dataclass
from typing import Any

MATERIALS = {
    "Сталь": {"rho": 7850.0, "k": 1.00, "grind": 1.00},
    "Высокохромистый чугун": {"rho": 7600.0, "k": 0.67, "grind": 1.08},
    "Серый чугун": {"rho": 7100.0, "k": 1.33, "grind": 0.90},
}
DEFAULT_DENSITY = 1200.0  # кг/м3, НАСЫПНАЯ плотность сырья — пример
CLASSES = [">40", "20–40", "10–20", "5–10", "2.5–5", "1.25–2.5", "0.63–1.25", "0.08–0.63", "0.045–0.08", "<0.045"]
LO = [40.0,20.0,10.0,5.0,2.5,1.25,0.63,0.08,0.045,0.01]
HI = [80.0,40.0,20.0,10.0,5.0,2.5,1.25,0.63,0.08,0.045]
MID = [60.,28.,14.,7.,3.5,1.8,0.9,0.24,0.06,0.02]
SIEVES = [40.,20.,10.,5.,2.5,1.25,0.63,0.08,0.045]
FEED_PRESET = [0,8.37,21.99,29.08,18.32,14.15,5.48,1.70,0.50,0.45]


def media_row(drum: int, chamber: int, size_mm: float, tons: float,
              kind: str = "Шары", material: str = "Сталь", aspect: float = 1.0) -> dict:
    return dict(drum=drum, chamber=chamber, type=kind, material=material,
                diameter_mm=float(size_mm), initial_t=float(tons), aspect=float(aspect))


def default_config() -> dict:
    """Пример для одного барабана с двумя камерами; свойства клинкера условные."""
    rows = []
    for size, tons in [(90,3.0),(80,20.82),(70,23.0),(60,25.175),(50,18.0),(40,0)]:
        if tons: rows.append(media_row(1,1,size,tons))
    for size, tons in [(50,4),(40,18),(30,30),(25,30),(20,14),(17,9)]:
        rows.append(media_row(1,2,size,tons,"Цильпебс"))
    return dict(
        mills=[dict(name="Мельница №3", diameter_m=4.0, length_m=13.4,
                    rpm=16.0, power_kw=2400.0, diaphragm_m=0.5,
                    chambers=[dict(length_m=6.265,diameter_m=4.0),dict(length_m=6.635,diameter_m=4.0)])],
        media=rows,
        throughput_mode="Измеренная подача, т/ч", fresh_feed_tph=72.0,
        measured_total_t=720.0, measured_hours=10.0,
        specific_energy_kwh_t=32.0, recycle_ratio=0.0,
        material_hold_t=18.0, feed_bulk_density=DEFAULT_DENSITY,
        abrasion_factor=1.0, moisture_pct=0.8, temperature_c=95.,
        work_index_kwh_t=None,
        grindability=1.0, feed_fraction=list(FEED_PRESET), sieves_mm=[40.,20.,10.,5.,2.5,1.25,.63,.08,.045],
        wear_g_t=90.0, delta=0.0, wear_ref_rpm_fraction=0.76,
        power_exponent=0.45, speed_exponent=0.7, loading_exponent=0.35, feed_coarseness_exponent=0.2, hardness_exponent=0.25,
        retention_mm=7.0, wear_reference_fill=0.30,
        breakage_k=2.80, fines_attrition_k=0.12, lab_blaine_base=1500., lab_blaine_scale=30.,
        horizon_h=1000., step_h=10., reload_threshold_pct=3.0,
        manual_reloads=[]
    )


def validate(cfg: dict) -> None:
    if len(cfg.get("mills",[])) != 1:
        raise ValueError("В модели предусмотрен один барабан с одной или двумя камерами")
    for d, mill in enumerate(cfg["mills"], 1):
        if not 1 <= mill["diameter_m"] <= 10 or not 1 <= mill["length_m"] <= 50:
            raise ValueError(f"Барабан {d}: проверьте диаметр и длину")
        if not 0 < mill["rpm"] <= 40 or not 0 <= mill["power_kw"] <= 30000:
            raise ValueError(f"Барабан {d}: некорректные обороты или мощность")
        if len(mill["chambers"]) not in (1,2):
            raise ValueError("В барабане должна быть одна или две камеры")
        lengths = sum(ch["length_m"] for ch in mill["chambers"])
        diaphragm = (len(mill["chambers"])-1)*mill["diaphragm_m"]
        if any(ch["length_m"] <= 0 for ch in mill["chambers"]):
            raise ValueError(f"Барабан {d}: длина камеры должна быть положительной")
        for ch in mill["chambers"]:
            effective_d = ch.get("diameter_m",mill["diameter_m"])
            if not (0 < effective_d <= mill["diameter_m"]):
                raise ValueError("Внутренний диаметр камеры должен быть > 0 и не больше диаметра барабана")
        if abs(lengths+diaphragm-mill["length_m"]) > 0.011:
            raise ValueError(f"Барабан {d}: сумма длин камер и перегородок должна равняться длине барабана")
    for x in cfg["media"]:
        if x["material"] not in MATERIALS or x["type"] not in ("Шары", "Цильпебс"):
            raise ValueError("Неизвестный материал или тип мелющего тела")
        di, ch = int(x["drum"]), int(x["chamber"])
        if di != 1 or ch < 1 or ch > len(cfg["mills"][0]["chambers"]):
            raise ValueError("Фракция привязана к несуществующей камере")
        if x["diameter_mm"] <= 0 or x["initial_t"] < 0 or x.get("aspect",1) <= 0:
            raise ValueError("Проверьте размер и массу фракций")
    sieves=cfg.get("sieves_mm",SIEVES)
    if not sieves or len(sieves)>20 or any(not isinstance(x,(int,float)) or not math.isfinite(x) or not 0.01<=x<=80 for x in sieves) or len(sieves)!=len(set(sieves)):
        raise ValueError("Выберите от 1 до 20 разных сит в диапазоне 0,01–80 мм")
    for rr in cfg.get("manual_reloads",[]):
        if int(rr["drum"])!=1 or int(rr["chamber"])>len(cfg["mills"][0]["chambers"]) or int(rr["chamber"])<1:
            raise ValueError("Догрузка должна относиться к существующей камере одного барабана")
        if rr["tons"]<=0 or rr["diameter_mm"]<=0 or rr["type"] not in ("Шары","Цильпебс") or rr["material"] not in MATERIALS:
            raise ValueError("Неверная масса, диаметр, тип или материал догрузки")
    if not 0.01 <= cfg["step_h"] <= 1000 or not 0 <= cfg["horizon_h"] <= 100000:
        raise ValueError("Неверный шаг или горизонт расчёта")
    if cfg["recycle_ratio"] < 0 or cfg["material_hold_t"] <= 0:
        raise ValueError("Возврат сепаратора и запас материала должны быть корректными")
    if len(cfg["feed_fraction"]) != 10 or sum(cfg["feed_fraction"]) <= 0 or any(x<0 for x in cfg["feed_fraction"]):
        raise ValueError("Некорректный гранулометрический состав входного материала")
    if cfg["wear_g_t"] < 0 or cfg["abrasion_factor"] <= 0 or not -1 <= cfg["delta"] <= 3:
        raise ValueError("Некорректные коэффициенты износа")
    if cfg["retention_mm"] < 0:
        raise ValueError("Диаметр выбраковки должен быть ≥ 0")
    _ = throughput(cfg)


def throughput(cfg:dict) -> dict:
    mode = cfg["throughput_mode"]
    if mode == "Измеренная подача, т/ч":
        q = float(cfg["fresh_feed_tph"])
    elif mode == "Масса / время":
        if cfg["measured_hours"] <= 0: raise ValueError("Время измерения должно быть >0")
        q = cfg["measured_total_t"] / cfg["measured_hours"]

    else:
        raise ValueError("Неизвестный способ определения производительности")
    if not math.isfinite(q) or q <= 0 or q > 20000: raise ValueError("Производительность должна быть >0 и <20000 т/ч")
    return {"product_tph":q,"mill_feed_tph":q*(1+cfg["recycle_ratio"]),
            "operating_specific_energy":sum(m["power_kw"] for m in cfg["mills"])/q}


def volume_m3(mill: dict, chamber: int) -> float:
    return math.pi*mill["chambers"][chamber-1].get("diameter_m",mill["diameter_m"])**2/4*mill["chambers"][chamber-1]["length_m"]


def mass_kg(row:dict, diameter:float) -> float:
    d = diameter/1000
    volume = math.pi*d**3/6 if row["type"]=="Шары" else math.pi*d**3/4*row.get("aspect",1.0)
    return volume * MATERIALS[row["material"]]["rho"]


def surface_m2(row:dict, diameter:float) -> float:
    d = diameter/1000
    return math.pi*d*d if row["type"]=="Шары" else math.pi*d*d*(row.get("aspect",1.0)+0.5)


def initial_cohorts(cfg:dict) -> list[dict]:
    out=[]
    for i,row in enumerate(cfg["media"]):
        if row["initial_t"] <= 0: continue
        each=mass_kg(row,row["diameter_mm"])
        count=row["initial_t"]*1000/each
        out.append({**deepcopy(row),"id":i,"batch":0,"n":count,
                    "d":row["diameter_mm"],"d0":row["diameter_mm"],
                    "initial_kg":row["initial_t"]*1000,"cumulative_loss_kg":0.0})
    return out


def cohort_mass(c:dict)->float:
    return c["n"]*mass_kg(c,c["d"])


def chamber_info(cfg:dict, cohorts:list[dict]) -> list[dict]:
    out=[]
    for i,m in enumerate(cfg["mills"],1):
        for j,ch in enumerate(m["chambers"],1):
            sub=[c for c in cohorts if c["drum"]==i and c["chamber"]==j and c["d"]>0]
            mass=sum(cohort_mass(c) for c in sub)
            solid=sum(cohort_mass(c)/MATERIALS[c["material"]]["rho"] for c in sub)
            # Более плотная укладка цильпебса и смешанной загрузки — упрощение
            p = 0.62 if sub and sum(cohort_mass(c) for c in sub if c["type"]=="Цильпебс")/max(mass,1)>0.5 else 0.585
            jfill=solid/p/volume_m3(m,j)
            out.append(dict(drum=i,chamber=j,length_m=ch["length_m"],diameter_m=ch.get("diameter_m",m["diameter_m"]),
                            rpm=m["rpm"],power_kw=m["power_kw"],volume_m3=volume_m3(m,j),
                            fill_j=jfill, mass_t=mass/1000,
                            mean_d_mm=sum(cohort_mass(c)*c["d"] for c in sub)/max(mass,1e-9),
                            cohorts=sub))
    return out


def factors(cfg:dict, cohort:dict, chambers:list[dict]) -> float:
    """Эмпирические множители: обязательно подгоняются по заводским данным."""
    mill=cfg["mills"][cohort["drum"]-1]
    ch=next(x for x in chambers if x["drum"]==cohort["drum"] and x["chamber"]==cohort["chamber"])
    crit=42.3/math.sqrt(ch["diameter_m"])
    frac=mill["rpm"]/crit
    speed=(max(frac,.01)/cfg["wear_ref_rpm_fraction"])**cfg["speed_exponent"]
    fill=(max(ch["fill_j"],0.01)/cfg["wear_reference_fill"])**cfg["loading_exponent"]
    # Мощность на единицу суммарной массы шаровой загрузки, кВт/т
    power_ratio=(max(mill["power_kw"],1)/(max(1,ch["mass_t"])*len(mill["chambers"]))) / 13.0
    power=max(0.1,power_ratio)**cfg["power_exponent"]
    wet=1.0 + 0.08*min(max(cfg["moisture_pct"],0),10)/2.0
    heat=1+0.001*max(0,cfg["temperature_c"]-95)
    chamber_factor=1.10 if cohort["chamber"]==1 else 0.92
    def geo_mean(sizes, fractions):
        return math.exp(sum(p*math.log(max(d,.02)) for d,p in zip(sizes,fractions))/max(sum(fractions),1e-12))
    dfeed=geo_mean(MID,cfg["feed_fraction"])
    dref=geo_mean(MID,FEED_PRESET)
    feed=max(.5,min(2.0,dfeed/dref))**cfg.get("feed_coarseness_exponent",0.0)
    hard=(1.0/max(cfg["grindability"],.1))**cfg.get("hardness_exponent",0.0)
    return (cfg["abrasion_factor"]*speed*fill*power*wet*heat*chamber_factor*feed*hard*
            MATERIALS[cohort["material"]]["k"]*
            (1.08 if cohort["type"]=="Цильпебс" else 1.0))


def make_weights(cfg:dict, cohorts:list[dict], chambers:list[dict], use_factors=True) -> list[float]:
    ref_d=50.0
    out=[]
    for c in cohorts:
        if c["d"] <= cfg["retention_mm"]:out.append(0.0);continue
        w=c["n"]*surface_m2(c,c["d"])*(c["d"]/ref_d)**cfg["delta"]
        if use_factors: w*=factors(cfg,c,chambers)
        out.append(w)
    return out


def fractions_at(cohorts:list[dict], hours:float)->tuple[dict,dict]:
    """Агрегированный актуальный диаметр/масса каждой номинальной фракции."""
    grouped={}
    for c in cohorts:
        key=f"Б{c['drum']}К{c['chamber']} · {c['type']} · {c['material']} · Ø{c['d0']:g}"
        r=grouped.setdefault(key,{"mass":0.0,"d_times_mass":0.0})
        m=cohort_mass(c)
        r["mass"]+=m
        r["d_times_mass"]+=c["d"]*m
    diam={"Наработка, ч":hours}
    mass={"Наработка, ч":hours}
    for key,v in grouped.items():
        diam[key]=v["d_times_mass"]/v["mass"] if v["mass"]>0 else 0.
        mass[key]=v["mass"]/1000
    return diam,mass


def coefficient_at(cfg:dict, cohorts:list[dict], W_ref:float, hours:float)->dict:
    """Расчётная удельная потеря каждой фракции, г/т продукта на текущем шаге."""
    infos=chamber_info(cfg,cohorts)
    weights=make_weights(cfg,cohorts,infos)
    out={"Наработка, ч":hours}
    for c,w in zip(cohorts,weights):
        key=f"Б{c['drum']}К{c['chamber']} · {c['type']} · {c['material']} · Ø{c['d0']:g}"
        out[key]=out.get(key,0)+cfg["wear_g_t"]*w/W_ref
    out["Вся загрузка, г/т"]=sum(cfg["wear_g_t"]*w/W_ref for w in weights)
    return out


def snapshot(cohorts:list[dict], cfg:dict, t:float, cumulative_prod:float, cumulative_wear:float) -> dict:
    cinfo=chamber_info(cfg,cohorts)
    d={"hours":float(t),"production_t":float(cumulative_prod),
       "loss_t":float(cumulative_wear/1000),"total_media_t":sum(cohort_mass(c) for c in cohorts)/1000}
    for info in cinfo:
        key=f"Б{info['drum']}К{info['chamber']}"
        d[key+" масса, т"]=info["mass_t"]
        d[key+" J, %"]=info["fill_j"]*100
        d[key+" Dср, мм"]=info["mean_d_mm"]
    return d


def simulate_wear(cfg:dict) -> dict:
    validate(cfg)
    Q=throughput(cfg)["product_tph"]
    cohorts=initial_cohorts(cfg)
    if not cohorts:raise ValueError("Нужно добавить хотя бы одну фракцию мелющих тел")
    baseline=chamber_info(cfg,cohorts)
    # Поверхность ЗДОРОВОЙ стартовой загрузки — опорная для GMCR (г/т).
    ref_weights=make_weights(cfg,cohorts,baseline,use_factors=False)
    w_ref=sum(ref_weights)
    if w_ref<=0: raise ValueError("Нет мелющих тел выше диаметра выбраковки")
    initial_mass=sum(cohort_mass(c) for c in cohorts)
    hist=[snapshot(cohorts,cfg,0,0,0)]
    d0,m0=fractions_at(cohorts,0)
    diam_history=[d0]
    fraction_mass_history=[m0]
    coefficient_history=[coefficient_at(cfg,cohorts,w_ref,0)]
    events=[]
    scheduled=sorted(cfg.get("manual_reloads",[]),key=lambda v:v.get("hour",0))
    scheduled_index=0
    loss_sum=0.0
    horizon=float(cfg["horizon_h"])
    steps=max(1,math.ceil(horizon/max(cfg["step_h"],horizon/400 if horizon else .01)))
    dt=horizon/steps if steps else 0
    for step in range(steps):
        t0=step*dt; t1=(step+1)*dt
        # Добавленные тела — новая партия с НАЧАЛЬНЫМ диаметром
        while scheduled_index<len(scheduled) and scheduled[scheduled_index].get("hour",0)<=t0+1e-9:
            rr=scheduled[scheduled_index];scheduled_index+=1
            if rr.get("tons",0)<=0:continue
            row=media_row(int(rr["drum"]),int(rr["chamber"]),float(rr["diameter_mm"]),float(rr["tons"]),rr["type"],rr["material"],float(rr.get("aspect",1)))
            cohorts.append({**row,"id":len(cohorts),"batch":scheduled_index,"n":row["initial_t"]*1000/mass_kg(row,row["diameter_mm"]),"d":row["diameter_mm"],"d0":row["diameter_mm"],"initial_kg":row["initial_t"]*1000,"cumulative_loss_kg":0})
            events.append({"hour":t0,**row})
        infos=chamber_info(cfg,cohorts)
        wts=make_weights(cfg,cohorts,infos)
        # dM = Q*dt * GMCR_ref [g/t] /1000 [g/kg] * relative contact area, kg
        loss_total=Q*dt*cfg["wear_g_t"]/1000*(sum(wts)/w_ref)
        sum_w=sum(wts)
        for i,c in enumerate(cohorts):
            if sum_w<=0 or wts[i]<=0:continue
            old=cohort_mass(c)
            loss=min(old,loss_total*wts[i]/sum_w)
            new=max(0.0,old-loss)
            c["cumulative_loss_kg"]+=loss
            loss_sum+=loss
            c["d"]=c["d0"]*(new/max(c["initial_kg"],1e-12))**(1/3)
            if c["d"]<cfg["retention_mm"]:
                # Учтём остаток выбракованной партии отдельно от истирания.
                rem=cohort_mass(c)
                c["removed_kg"]=c.get("removed_kg",0)+rem
                c["n"]=0.0
        hist.append(snapshot(cohorts,cfg,t1,Q*t1,loss_sum))
        dh,mh=fractions_at(cohorts,t1)
        diam_history.append(dh)
        fraction_mass_history.append(mh)
        coefficient_history.append(coefficient_at(cfg,cohorts,w_ref,t1))
    for rr in scheduled[scheduled_index:]:
        if rr.get("hour",0)<=horizon:
            events.append({"hour":rr["hour"],**rr})
    # строка на каждую исходную фракцию: накопленные массы, а не только первый cohort
    result=[]
    for c in cohorts:
        initial=c["initial_kg"];final=cohort_mass(c)
        result.append({"Барабан":c["drum"],"Камера":c["chamber"],"Тип":c["type"],
                       "Материал":c["material"],"Ø ном., мм":c["d0"],"Ø текущ., мм":c["d"],
                       "Начальная масса, т":initial/1000,"Текущая масса, т":final/1000,
                       "Истирание, т":c["cumulative_loss_kg"]/1000,"Выбраковано, т":c.get("removed_kg",0)/1000,
                       "Износ, %":(1-final/max(initial,1e-9))*100,
                       "Партия":c.get("batch",0),"Количество, шт":c["n"]})
    return {"config":cfg,"rows":hist,"cohorts":cohorts,"cohort_results":result,
            "initial_media_t":initial_mass/1000,"total_wear_t":loss_sum/1000,"reload_events":events,
            "diameter_history":diam_history,"fraction_mass_history":fraction_mass_history,
            "coefficient_history":coefficient_history,
            "throughput":throughput(cfg)}


def recommends(cfg:dict, run:dict) -> list[dict]:
    by_group={}
    for c in run["cohorts"]:
        key=(c["drum"],c["chamber"],c["type"],c["material"],c["d0"],c.get("aspect",1))
        agg=by_group.setdefault(key,{"nominal_kg":0,"live_kg":0})
        agg["nominal_kg"]+=c["initial_kg"]
        agg["live_kg"]+=cohort_mass(c)
    out=[]
    for key, d in by_group.items():
        deficit=d["nominal_kg"]-d["live_kg"]
        pct=100*deficit/max(d["nominal_kg"],1e-9)
        if pct < cfg["reload_threshold_pct"] or deficit<=0:continue
        dr,ch,typ,mat,diam,asp=key
        piece_kg=mass_kg(dict(type=typ,material=mat,aspect=asp),diam)
        num=math.ceil(deficit/piece_kg)
        out.append({"Барабан":dr,"Камера":ch,"Тип":typ,"Материал":mat,
                    "Ø, мм":diam,"Потеря массы, т":deficit/1000,"Износ, %":pct,
                    "Догрузить, шт":num,"Догрузить, т":num*piece_kg/1000,
                    "Рекомендация":"Восстановить исходную массу фракции; сверить с J и технологом"})
    return sorted(out,key=lambda x:(x["Барабан"],x["Камера"],-x["Ø, мм"]))


def cumulative_residue(comp:list[float], sieve:float) -> float:
    ret=0
    for i,c in enumerate(comp):
        if sieve<=LO[i]:ret+=c
        elif sieve<HI[i]:
            ret+=c*(math.log(HI[i])-math.log(sieve))/(math.log(HI[i])-math.log(LO[i]))
    return ret


def fragmentation(i:int)->list[float]:
    b=[0.] * 10
    for j in range(i+1,10): b[j]=0.55**(j-i-1)+(0.05 if j==9 else 0.0)
    s=sum(b)
    return [v/s if s else 0 for v in b]


def gauss(x:float,y:float,sd:float)->float:
    return math.exp(-((x-y)/max(sd,1e-9))**2)


def media_impact(cohorts:list[dict], grain_mm:float)->float:
    total=sum(cohort_mass(c) for c in cohorts)
    if total<=0:return 0.0
    dopt=min(26*math.sqrt(grain_mm),100)
    s=0.0
    for c in cohorts:
        if c["d"]<=0:continue
        sig=(.9 if c["d"]>dopt else .35)*dopt
        s+=cohort_mass(c)*MATERIALS[c["material"]]["grind"]*gauss(c["d"],dopt,sig)
    return s/total


def size_at_pass_percent(comp:list[float], passing_pct:float=80.0) -> float:
    """Размер в мкм из модельных интервальных фракций, с лог-интерполяцией."""
    if not 0 < passing_pct < 100: raise ValueError("Доля прохода должна быть от 0 до 100%")
    total=sum(comp)
    if total<=0: raise ValueError("Пустой гранулометрический состав")
    threshold=100.0-passing_pct
    lo,hi=0.01,80.0
    for _ in range(80):
        mid=math.sqrt(lo*hi)
        ret=100*cumulative_residue(comp,mid)/total
        if ret>threshold:lo=mid
        else:hi=mid
    return math.sqrt(lo*hi)*1000.0


def operating_bond_index(power_kw:float,product_tph:float,f80_um:float,p80_um:float) -> float|None:
    """Эксплуатационный Wi, НЕ лабораторный Bond Ball Mill Work Index."""
    if min(power_kw,product_tph,f80_um,p80_um)<=0 or p80_um>=f80_um:return None
    denom=10*(1/math.sqrt(p80_um)-1/math.sqrt(f80_um))
    return (power_kw/product_tph)/denom if denom>0 else None

def quality_at(cfg:dict, cohorts:list[dict], samples:int=14) -> dict:
    """Демонстрационная кинетическая схема; не выдаёт лабораторный результат без калибровки."""
    infos=chamber_info(cfg,cohorts)
    Q=throughput(cfg)["mill_feed_tph"]
    residence_min=60*cfg["material_hold_t"]/Q
    total_v=sum(z["volume_m3"] for z in infos)
    total_L=sum(z["length_m"] for z in infos)
    comps=[100*x/sum(cfg["feed_fraction"]) for x in cfg["feed_fraction"]]
    pts=[dict(position_m=0.0,comp=comps.copy())]
    x=0.0
    grain_dist=[fragmentation(i) for i in range(10)]
    for z_index,z in enumerate(infos):
        if z_index:
            x+=cfg["mills"][0]["diaphragm_m"]
            pts.append(dict(position_m=x,comp=comps.copy(),drum=1,chamber=z["chamber"]))
        fraction=z["volume_m3"]/total_v
        steps=max(30,math.ceil(samples*z["length_m"]/total_L)*5)
        tm=residence_min*fraction
        sub=z["cohorts"]
        crit=42.3/math.sqrt(z["diameter_m"])
        speed=gauss(z["rpm"]/crit,0.76,0.21)
        loading=gauss(z["fill_j"],0.30,0.20)
        attr_mass=sum(cohort_mass(c)*gauss(c["d"],22,12) for c in sub)/max(sum(cohort_mass(c) for c in sub),1e-9)
        for j in range(steps):
            timestep=tm/steps
            for i in range(9):
                eff=media_impact(sub,MID[i])
                rate=cfg["breakage_k"]*eff*speed*loading*cfg["grindability"]*(.65 if MID[i]<.63 else 1.0)
                if MID[i]<.08:
                    rate+=cfg.get("fines_attrition_k",0.0)*attr_mass*speed*loading*cfg["grindability"]
                br=min(comps[i],comps[i]*(1-math.exp(-max(0,rate)*timestep)))
                comps[i]-=br
                for k in range(i+1,10):comps[k]+=br*grain_dist[i][k]
            x+=z["length_m"]/steps
            pts.append(dict(position_m=x,comp=comps.copy(),drum=z["drum"],chamber=z["chamber"]))
    sample_pts=[]
    for i in range(samples):
        pos=0.25+i*(max(0.3,cfg["mills"][0]["length_m"]-0.5))/(samples-1)
        p=min(pts,key=lambda r:abs(r["position_m"]-pos))
        sample_pts.append({"Точка":i+1,"Расстояние по камерам, м":round(pos,3),
                           "Барабан":p.get("drum",1),"Камера":p.get("chamber",1),
                           **{f"R{s:g}, %":round(cumulative_residue(p["comp"],s),3) for s in sorted(cfg.get("sieves_mm",SIEVES),reverse=True)}})
    final=pts[-1]["comp"]
    f80=size_at_pass_percent(cfg["feed_fraction"])
    p80=size_at_pass_percent(final)
    op_wi=operating_bond_index(cfg["mills"][0]["power_kw"],throughput(cfg)["product_tph"],f80,p80)
    return {"samples":sample_pts,"product_fractions":final,"f80_um":f80,"p80_um":p80,"operating_wi_kwh_t":op_wi,"r008":cumulative_residue(final,.08),
            "r0045":cumulative_residue(final,.045),
            "blaine_proxy":cfg["lab_blaine_base"]+cfg["lab_blaine_scale"]*final[-1],
            "residence_min":residence_min,"chambers":infos}


def quality_over_time(cfg:dict, run:dict, max_points:int=16)->list[dict]:
    """Состояние между начал./кон. моделируем без догрузок в промежуточных точках.

    Для точек с догрузками требуется прогон симуляции до нужного часа — в demo по умолчанию
    используются только начальный и конечный составы, чтобы избежать ложной точности.
    """
    data=[]
    q=quality_at(cfg,initial_cohorts(cfg))
    data.append({"Наработка, ч":0.,"R0.08, %":q["r008"],"R0.045, %":q["r0045"],
                 "Блейн-прокси, см²/г":q["blaine_proxy"]})
    h=run["rows"][-1]["hours"]
    q=quality_at(cfg,run["cohorts"])
    data.append({"Наработка, ч":h,"R0.08, %":q["r008"],"R0.045, %":q["r0045"],
                 "Блейн-прокси, см²/г":q["blaine_proxy"]})
    return data
