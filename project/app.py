"""Streamlit UI для промышленного прототипа Black Box по помолу и износу."""
from __future__ import annotations
import json
import math
from copy import deepcopy

import plotly.graph_objects as go
import streamlit as st

from model import (default_config, validate, simulate_wear, quality_at, quality_over_time,
                   initial_cohorts, chamber_info, recommends, MATERIALS, CLASSES,
                   SIEVES, throughput, factors)
from excel_export import export_excel

st.set_page_config(page_title="Black Box — цементная мельница",layout="wide",page_icon="⚙️")
st.markdown("""<style>
.block-container{max-width:1540px;padding-top:1.3rem}.metric-label{font-weight:600}
.smallwarn{color:#9d6616;font-size:.91rem} div[data-testid="stDataFrame"]{font-size:13px}
</style>""",unsafe_allow_html=True)

if "cfg" not in st.session_state:
    st.session_state.cfg=default_config()
if "result" not in st.session_state:
    st.session_state.result=simulate_wear(st.session_state.cfg)

st.title("Black Box · Моделирование цементной мельницы")
st.caption("Инженерный прототип — геометрия, кинетика помола, износ мелющих тел, догрузки, экспорт Excel. ")
st.warning("Это **расчётный прогноз**, а не обученная на заводских данных модель. Базовый расход мелющих тел, коэффициенты материала и помола необходимо откалибровать по фактическим замерам. Показатель Блейна пока является эмпирическим прокси.",icon="⚠️")

with st.sidebar:
    st.subheader("Конфигурация проекта")
    raw=st.file_uploader("Загрузить параметры JSON",type="json",help="JSON, ранее выгруженный из приложения")
    if raw and st.button("Применить JSON"):
        try:
            incoming=json.load(raw)
            if not isinstance(incoming,dict):raise ValueError("Неверный формат")
            validate(incoming)
            st.session_state.cfg=incoming
            st.session_state.result=simulate_wear(incoming)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    st.download_button("Скачать конфигурацию JSON",json.dumps(st.session_state.cfg,ensure_ascii=False,indent=2).encode("utf-8"),"cement_config.json","application/json")
    st.divider()
    st.caption("Параметры по умолчанию — демонстрация на основе ранее созданного HTML для мельницы №3. Данные из АСУ ТП пока не подключены.")

base=deepcopy(st.session_state.cfg)

with st.form("main_form"):
    tabs=st.tabs(["Геометрия и привод","Подача и сырьё","Мелющие тела","Износ и калибровка"])
    with tabs[0]:
        st.markdown("**Две камеры одного барабана имеют общий диаметр. Два отдельных барабана задаются независимо.**")
        mill_count=st.radio("Количество самостоятельных барабанов",[1,2],index=0 if len(base["mills"])==1 else 1,horizontal=True)
        mills=[]
        for mi in range(mill_count):
            original=base["mills"][mi] if mi<len(base["mills"]) else dict(name="Барабан 2",diameter_m=3.8,
                 rpm=15.5,power_kw=1800.,diaphragm_m=.5,chambers=[{"length_m":5.0},{"length_m":5.8}])
            with st.expander(f"Барабан {mi+1}: размеры, привод и камеры",expanded=True):
                a,b,c=st.columns(3)
                name=a.text_input("Наименование",value=original.get("name",f"Барабан {mi+1}"),key=f"name{mi}")
                dm=b.number_input("Диаметр барабана, м",1.,10.,float(original["diameter_m"]),.1,key=f"dm{mi}")
                rpm=c.number_input("Обороты, об/мин",.1,40.,float(original["rpm"]),.1,key=f"rpm{mi}")
                a,b,c=st.columns(3)
                power=a.number_input("Мощность привода, кВт",0.,30000.,float(original["power_kw"]),50.,key=f"power{mi}")
                ncols=b.selectbox("Число камер в этом барабане",[1,2],index=0 if len(original["chambers"])==1 else 1,key=f"chcount{mi}")
                diaphragm=c.number_input("Толщина межкамерной перегородки, м",0.,2.,float(original.get("diaphragm_m",.5)),.05,key=f"diaphragm{mi}",disabled=ncols==1)
                ca,cb=st.columns(2)
                ch1=ca.number_input("Длина камеры I, м",.5,40.,float(original["chambers"][0]["length_m"]),.05,key=f"l1{mi}")
                chs=[dict(length_m=ch1)]
                if ncols==2:
                    length2=float(original["chambers"][1]["length_m"]) if len(original["chambers"])>1 else 6.
                    ch2=cb.number_input("Длина камеры II, м",.5,40.,length2,.05,key=f"l2{mi}")
                    chs.append(dict(length_m=ch2))
                total_l=sum(ch["length_m"] for ch in chs)+(ncols-1)*diaphragm
                st.caption(f"Общая длина барабана = **{total_l:.3f} м**; nкр ≈ **{42.3/math.sqrt(dm):.1f} об/мин**; n/nкр = **{rpm/(42.3/math.sqrt(dm))*100:.1f} %**")
                mills.append(dict(name=name,diameter_m=dm,length_m=total_l,rpm=rpm,power_kw=power,
                                  diaphragm_m=diaphragm,chambers=chs))
    with tabs[1]:
        st.markdown("**Производительность — это измеренный либо оценённый поток.** При замкнутой схеме свежая подача и внутренний поток через мельницу различаются.")
        modes=["Измеренная подача, т/ч","Масса / время","По мощности и удельной энергии","По мощности и Бонду (оценка)"]
        mode=st.selectbox("Способ определения производительности готового продукта",modes,index=modes.index(base.get("throughput_mode",modes[0])))
        a,b,c=st.columns(3)
        fresh=a.number_input("Измеренная свежая подача, т/ч",1.,20000.,float(base["fresh_feed_tph"]),1.)
        mass=b.number_input("Произведено за период, т",.01,1000000.,float(base["measured_total_t"]),10.)
        hours=c.number_input("Часы работы за период",.01,100000.,float(base["measured_hours"]),1.)
        a,b,c=st.columns(3)
        energy=a.number_input("Удельная энергия, кВт·ч/т",.01,200.,float(base["specific_energy_kwh_t"]),1.)
        wi=b.number_input("Индекс работы Бонда Wi, кВт·ч/т",.01,80.,float(base["work_index_kwh_t"]),1.)
        f80=c.number_input("F80 на входе, мкм",1.,1000000.,float(base["f80_um"]),100.)
        a,b,c=st.columns(3)
        p80=a.number_input("Целевой P80, мкм",1.,50000.,float(base["p80_um"]),5.)
        recycle=b.number_input("Возврат сепаратора / продукт, т/т",0.,20.,float(base["recycle_ratio"]),.1)
        hold=c.number_input("Запас измельчаемого материала, т",.1,1000.,float(base["material_hold_t"]),1.)
        st.divider()
        a,b,c=st.columns(3)
        abr=a.number_input("Коэфф. абразивности относительно эталона",.1,10.,float(base["abrasion_factor"]),.1)
        grind=b.number_input("Относительная размолоспособность",.1,3.,float(base["grindability"]),.05)
        moisture=c.number_input("Влажность сырья, %",0.,20.,float(base["moisture_pct"]),.1)
        a,b,c=st.columns(3)
        temperature=a.number_input("Температура на входе, °C",0.,250.,float(base["temperature_c"]),5.)
        bulk=b.number_input("Насыпная плотность сырья, кг/м³",200.,3500.,float(base["feed_bulk_density"]),50.)
        bk=c.number_input("Коэфф. кинетики помола, 1/мин",.001,5.,float(base["breakage_k"]),.05)
        attrk=st.number_input("Коэффициент истирания тонкой фракции, 1/мин",0.,3.,float(base.get("fines_attrition_k",.12)),.01)
        st.caption("Входной грансостав можно изменить таблицей. Сумма автоматически нормируется до 100 %.")
        feed_rows=[{"Фракция":label,"Массовая доля, %":value} for label,value in zip(CLASSES,base["feed_fraction"])]
        feed_edit=st.data_editor(feed_rows,num_rows="fixed",hide_index=True,
            disabled=["Фракция"],column_config={"Массовая доля, %":st.column_config.NumberColumn(min_value=0.,max_value=100.,step=.1)},key="feed_editor")
    with tabs[2]:
        st.markdown("**Каждая строка — одна фракция в конкретной камере, отдельный диаметр/материал/форма.** Можно добавлять фракции. Масса указывается на начало расчётного периода.")
        rows=base["media"]
        editor_rows=[{"Барабан":r["drum"],"Камера":r["chamber"],"Тип":r["type"],"Материал":r["material"],
                      "Ø, мм":r["diameter_mm"],"Масса, т":r["initial_t"],"L/D (цильпебс)":r.get("aspect",1.)} for r in rows]
        edited=st.data_editor(editor_rows,num_rows="dynamic",hide_index=True,
             column_config={
                 "Барабан":st.column_config.NumberColumn(min_value=1,max_value=2,step=1),
                 "Камера":st.column_config.NumberColumn(min_value=1,max_value=2,step=1),
                 "Тип":st.column_config.SelectboxColumn(options=["Шары","Цильпебс"]),
                 "Материал":st.column_config.SelectboxColumn(options=list(MATERIALS)),
                 "Ø, мм":st.column_config.NumberColumn(min_value=5.,max_value=150.,step=1.),
                 "Масса, т":st.column_config.NumberColumn(min_value=0.,max_value=500.,step=.5),
                 "L/D (цильпебс)":st.column_config.NumberColumn(min_value=.1,max_value=5.,step=.1),
             },key="media_editor",use_container_width=True)
        st.info("Плотности и начальные относительные коэффициенты: сталь 7850 кг/м³ (1,00); высокохромистый чугун 7600 (0,67); серый чугун 7100 (1,33). Это демонстрационные коэффициенты, замените их заводскими измерениями.")
    with tabs[3]:
        a,b,c=st.columns(3)
        horizon=a.number_input("Горизонт моделирования, ч",1.,100000.,float(base["horizon_h"]),100.)
        step=b.number_input("Шаг интегрирования, ч",.1,1000.,float(base["step_h"]),1.)
        gmcr=c.number_input("Базовый удельный износ, г/т цемента",0.,10000.,float(base["wear_g_t"]),5.)
        a,b,c=st.columns(3)
        delta=a.slider("Степень закона износа Δ",-1.,3.,float(base["delta"]),.1,
                       help="dMшара/dt ∝ d^(2+Δ). Δ=0: площадь поверхности; Δ=1: пример объёмно-подобной зависимости")
        retention=b.number_input("Минимальный диаметр/выбраковка, мм",0.,50.,float(base["retention_mm"]),1.)
        threshold=c.number_input("Порог рекомендаций по догрузке, %",.1,50.,float(base["reload_threshold_pct"]),1.)
        a,b,c=st.columns(3)
        speed_exp=a.number_input("Показатель влияния скорости",0.,3.,float(base["speed_exponent"]),.05)
        load_exp=b.number_input("Показатель влияния заполнения",0.,3.,float(base["loading_exponent"]),.05)
        power_exp=c.number_input("Показатель влияния мощности",0.,3.,float(base["power_exponent"]),.05)
        a,b,c=st.columns(3)
        ref_speed=a.number_input("Опорная доля критических оборотов",.2,1.5,float(base["wear_ref_rpm_fraction"]),.02)
        ref_fill=b.number_input("Опорное заполнение J",.05,.70,float(base["wear_reference_fill"]),.01)
        blaine0=c.number_input("Блейн: свободный член ПРОКСИ",0.,10000.,float(base["lab_blaine_base"]),100.)
        a,b=st.columns(2)
        feed_exp=a.number_input("Показатель влияния крупности сырья",0.,3.,float(base.get("feed_coarseness_exponent",.2)),.05)
        hard_exp=b.number_input("Показатель влияния размолоспособности",0.,3.,float(base.get("hardness_exponent",.25)),.05)
        blainek=st.number_input("Блейн: множитель доли класса <0.045 мм (ПРОКСИ)",0.,300.,float(base["lab_blaine_scale"]),1.)
        st.caption("Дополнительно возможен сценарий с зафиксированной догрузкой (час внесения и масса). Для первого расчёта он пуст.")
        prev=base.get("manual_reloads",[])
        prev_rows=[{"Наработка, ч":r["hour"],"Барабан":r["drum"],"Камера":r["chamber"],
                    "Тип":r["type"],"Материал":r["material"],"Ø, мм":r["diameter_mm"],
                    "Догрузить, т":r["tons"]} for r in prev]
        if not prev_rows:
            prev_rows=[{"Наработка, ч":0.0,"Барабан":1,"Камера":1,"Тип":"Шары","Материал":"Сталь","Ø, мм":80.0,"Догрузить, т":0.0}]
        re_edit=st.data_editor(prev_rows,num_rows="dynamic",hide_index=True,key="reload_editor",
            column_config={"Тип":st.column_config.SelectboxColumn(options=["Шары","Цильпебс"]),
                          "Материал":st.column_config.SelectboxColumn(options=list(MATERIALS))})
        st.markdown("**Быстрая калибровка удельного расхода по журналу производства**")
        a,b,c=st.columns(3)
        produced=a.number_input("Произведено цемента, т",0.,10000000.,0.,100.)
        replacement=b.number_input("Фактическая потеря загрузки, кг (не просто масса догрузки)",0.,1000000.,0.,10.)
        if produced>0:
            st.caption(f"Наблюдаемый расход: **{replacement*1000/produced:.2f} г/т**. Для строгой оценки скорректируйте догрузки, выбраковку и начальную/конечную массу загрузки.")
            if c.checkbox("Использовать наблюдаемый расход как базовый коэффициент"):
                gmcr=replacement*1000/produced

    go_clicked=st.form_submit_button("▶ Рассчитать модель",type="primary",use_container_width=True)

if go_clicked:
    try:
        cfg=deepcopy(base)
        cfg["mills"]=mills
        cfg.update(throughput_mode=mode,fresh_feed_tph=fresh,measured_total_t=mass,measured_hours=hours,
            specific_energy_kwh_t=energy,recycle_ratio=recycle,material_hold_t=hold,
            work_index_kwh_t=wi,f80_um=f80,p80_um=p80,abrasion_factor=abr,
            grindability=grind,moisture_pct=moisture,temperature_c=temperature,
            feed_bulk_density=bulk,breakage_k=bk,fines_attrition_k=attrk,
            horizon_h=horizon,step_h=step,wear_g_t=gmcr,delta=delta,retention_mm=retention,
            reload_threshold_pct=threshold,speed_exponent=speed_exp,loading_exponent=load_exp,
            power_exponent=power_exp,wear_ref_rpm_fraction=ref_speed,wear_reference_fill=ref_fill,
            lab_blaine_base=blaine0,lab_blaine_scale=blainek,
            feed_coarseness_exponent=feed_exp,hardness_exponent=hard_exp)
        cfg["feed_fraction"]=[float(r.get("Массовая доля, %",0) or 0) for r in feed_edit]
        cfg["media"]=[]
        for row in edited:
            if not row or not row.get("Масса, т"):continue
            cfg["media"].append(dict(drum=int(row["Барабан"]),chamber=int(row["Камера"]),
                type=row["Тип"],material=row["Материал"],diameter_mm=float(row["Ø, мм"]),
                initial_t=float(row["Масса, т"]),aspect=float(row.get("L/D (цильпебс)") or 1)))
        cfg["manual_reloads"]=[]
        for rr in re_edit:
            if not rr or not rr.get("Догрузить, т"):continue
            cfg["manual_reloads"].append(dict(hour=float(rr["Наработка, ч"]),drum=int(rr["Барабан"]),chamber=int(rr["Камера"]),
                  type=rr["Тип"],material=rr["Материал"],diameter_mm=float(rr["Ø, мм"]),tons=float(rr["Догрузить, т"])))
        with st.spinner("Расчёт износа по временным шагам…"):
            res=simulate_wear(cfg)
        st.session_state.cfg=cfg
        st.session_state.result=res
        st.session_state.excel_bytes=None
    except Exception as exc:
        st.error(f"Ошибка входных данных: {exc}")

res=st.session_state.result
if res:
    cfg=res["config"]
    q0=quality_at(cfg,initial_cohorts(cfg))
    q=quality_at(cfg,res["cohorts"])
    R=recommends(cfg,res)
    st.divider()
    tput=res["throughput"]
    cols=st.columns(6)
    for cell,(title,val) in zip(cols,[
        ("Продукт, т/ч",f"{tput['product_tph']:.1f}"),
        ("Внутренний поток, т/ч",f"{tput['mill_feed_tph']:.1f}"),
        ("Потеря загрузки, т",f"{res['total_wear_t']:.2f}"),
        ("R0.08, % (модель)",f"{q['r008']:.2f}"),
        ("R0.045, % (модель)",f"{q['r0045']:.2f}"),
        ("Блейн-прокси",f"{q['blaine_proxy']:.0f}")]):
        cell.metric(title,val)
    plot1,plot2,plot3,plot4,plot5=st.tabs(["Износ во времени","Диаграмма помола","Мелющие тела и камеры","Догрузки","Экспорт Excel / Black Box"])
    with plot1:
        H=res["rows"]
        x=[h["hours"] for h in H]
        c1,c2=st.columns(2)
        with c1:
            f=go.Figure()
            f.add_trace(go.Scatter(x=x,y=[h["loss_t"] for h in H],mode="lines",name="Износ",line=dict(color="#D97706",width=3)))
            f.update_layout(title="Накопленная потеря массы",xaxis_title="Наработка, ч",yaxis_title="т",height=400)
            st.plotly_chart(f,use_container_width=True)
        with c2:
            f=go.Figure()
            f.add_trace(go.Scatter(x=x,y=[h["total_media_t"] for h in H],mode="lines",name="Масса загрузки",line=dict(color="#15803D",width=3)))
            f.update_layout(title="Текущая масса мелющих тел",xaxis_title="Наработка, ч",yaxis_title="т",height=400)
            st.plotly_chart(f,use_container_width=True)
        c1,c2=st.columns(2)
        with c1:
            f=go.Figure()
            for ch in chamber_info(cfg,res["cohorts"]):
                label=f"Б{ch['drum']}, К{ch['chamber']}"
                f.add_trace(go.Scatter(x=x,y=[s.get(label.replace('Б', 'Б').replace(', ', '')+' J, %') for s in H],name=label,mode="lines"))
            f.update_layout(title="Заполнение камер J",xaxis_title="ч",yaxis_title="%",height=380)
            st.plotly_chart(f,use_container_width=True)
        with c2:
            incremental=[]
            for i in range(1,len(H)):
                dp=H[i]["production_t"]-H[i-1]["production_t"]
                dl=H[i]["loss_t"]-H[i-1]["loss_t"]
                incremental.append(1e6*dl/dp if dp else 0)
            f=go.Figure(go.Scatter(x=x[1:],y=incremental,mode="lines",line=dict(color="#2563EB",width=2)))
            f.update_layout(title="Фактический расчётный износ, г/т",xaxis_title="ч",yaxis_title="г/т",height=380)
            st.plotly_chart(f,use_container_width=True)
        gh=res.get("coefficient_history",[])
        if gh:
            st.subheader("Коэффициент износа выбранных фракций, г/т цемента")
            cnames=[name for name in gh[0] if name not in ("Наработка, ч","Вся загрузка, г/т")]
            chosen=st.multiselect("Показать коэффициент износа фракций",cnames,default=cnames[:min(4,len(cnames))])
            f=go.Figure()
            for name in chosen:
                f.add_trace(go.Scatter(x=[r["Наработка, ч"] for r in gh],y=[r.get(name) for r in gh],name=name,mode="lines"))
            f.add_trace(go.Scatter(x=[r["Наработка, ч"] for r in gh],y=[r["Вся загрузка, г/т"] for r in gh],name="ВСЕ тела, г/т",mode="lines",line=dict(width=3,dash="dash")))
            f.update_layout(xaxis_title="Наработка, ч",yaxis_title="г/т",height=410)
            st.plotly_chart(f,use_container_width=True)
        st.subheader("Изменение диаметра выбранных фракций")
        dh=res.get("diameter_history",[])
        if dh:
            names=list(dh[0].keys())[1:]
            selected=st.multiselect("Фракции (диаметр во времени)",names,default=names[:min(4,len(names))])
            f=go.Figure()
            for name in selected:
                f.add_trace(go.Scatter(x=[r["Наработка, ч"] for r in dh],y=[r.get(name) for r in dh],name=name,mode="lines"))
            f.update_layout(xaxis_title="Наработка, ч",yaxis_title="Фактический диаметр, мм",height=410)
            st.plotly_chart(f,use_container_width=True)
    with plot2:
        st.caption("Это расчётный грансостав на позициях **вдоль последовательности камер**. Для двух самостоятельных барабанов ось X — суммарная длина камер без межбарабанных переходов.")
        samples=q["samples"]
        fig=go.Figure()
        for s in [0.63,0.08,0.045]:
            key=f"R{s:g}, %"
            fig.add_trace(go.Scatter(x=[v["Расстояние по камерам, м"] for v in samples],y=[v[key] for v in samples],
                                     mode="lines+markers",name=f"R{s:g}"))
        fig.update_layout(title="Диаграмма помола: полный остаток",xaxis_title="Положение вдоль камер, м",yaxis_title="Остаток, %",height=480)
        st.plotly_chart(fig,use_container_width=True)
        st.dataframe(samples,use_container_width=True,hide_index=True)
        st.caption(f"Расчётное среднее время пребывания: {q['residence_min']:.1f} мин. Блейн здесь — индикатор, НЕ лабораторно валидированная величина.")
    with plot3:
        info=chamber_info(cfg,res["cohorts"])
        st.dataframe([{k:v for k,v in x.items() if k!='cohorts'} for x in info],use_container_width=True,hide_index=True)
        fig=go.Figure()
        for r in res["cohort_results"]:
            label=f"Б{r['Барабан']}К{r['Камера']} {r['Тип']} Ø{r['Ø ном., мм']:g} {r['Материал']}"
            fig.add_trace(go.Bar(name=label,x=[label],y=[r["Истирание, т"]]))
        fig.update_layout(title="Потеря массы по фракциям",xaxis_title="Фракция",yaxis_title="Истирание, т",height=490,showlegend=False)
        st.plotly_chart(fig,use_container_width=True)
        st.dataframe(res["cohort_results"],use_container_width=True,hide_index=True)
    with plot4:
        st.markdown("**Рекомендация:** восстановление дефицита по исходной массе конкретной фракции, округление до целого числа полноразмерных тел. Это не автоматическое решение для реального оборудования.")
        if R:st.dataframe(R,use_container_width=True,hide_index=True)
        else:st.success("Порог износа не достигнут — догрузка не предлагается")
        if res["reload_events"]:
            st.markdown("**История смоделированных фактических догрузок**")
            st.dataframe(res["reload_events"],use_container_width=True,hide_index=True)
    with plot5:
        st.markdown("**Excel:** исходные измерения и прогнозные ряды, график износа по времени, остатки на ситах вдоль камер, состояние фракций, догрузка и источники.")
        st.code("Входные параметры JSON → validate() → throughput() → simulate_wear() → quality_at() → recommends() → export_excel()",language="text")
        if st.button("Сформировать Excel",type="primary"):
            try:
                with st.spinner("Формирование Excel с графиками…"):
                    st.session_state.excel_bytes=export_excel(cfg,res)
                st.success("Excel сформирован")
            except Exception as exc:
                st.error(f"Ошибка экспорта: {exc}")
        if st.session_state.get("excel_bytes"):
            st.download_button("⬇ Скачать результат .xlsx",st.session_state.excel_bytes,"cement_blackbox_report.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("⬇ Скачать полный результат Black Box (JSON)",json.dumps(res,ensure_ascii=False,indent=2).encode("utf-8"),"cement_blackbox_results.json","application/json")
        st.download_button("⬇ Скачать входной JSON",json.dumps(cfg,ensure_ascii=False,indent=2).encode("utf-8"),"cement_blackbox_config.json","application/json")
else:
    st.info("Задайте исходные параметры и нажмите **«Рассчитать модель»**. Данные мельницы №3 уже заполнены демонстрационным пресетом.")

with st.expander("Математическая основа и ограничения"):
    st.latex(r"\frac{dm_i}{dt}=-\frac{Q_{prod}\,G_0}{1000}\;\frac{\sum_j w_j}{W_{ref}}\;\frac{w_i}{\sum_j w_j},\quad w_i=N_i A_i(d_i)\left(\frac{d_i}{50\,\mathrm{mm}}\right)^\Delta F_i")
    st.latex(r"F_i=F_{material}\,F_{shape}\,F_{abrasive}\,F_{rpm}\,F_J\,F_{power}\,F_{chamber}\,F_{environment}")
    st.latex(r"d_i(t)=d_{i,0}\left(\frac{m_i(t)}{m_{i,0}}\right)^{1/3},\quad Q_{measured}=\frac{\Delta M}{\Delta t},\quad E_{specific}=\frac{P}{Q_{product}}")
    st.markdown("Износ интегрируется дискретно по времени. **Шары и цильпебс** имеют разную площадь поверхности и объём; для цильпебса учитывается отношение длины к диаметру. Степень Δ берётся из семейства поверхностных законов износа. **Коэффициент G₀** и множители пока представляют гипотезу, которую следует подбирать по наблюдениям разных периодов, а не только одной точке.")
    st.markdown("Ограничения: схема кинетики помола является упрощённым population-balance-приближением без полноценной модели сепаратора; для 2 отдельных барабанов использована последовательная передача материала. Мощность задаётся измеряемым входом, а не выводится из геометрии. Износ футеровки не рассматривается. Определение Блейна, как в предыдущем HTML, пока прокси по доле тонкой фракции.")

with st.expander("Калибровка по историческим данным предприятия (CSV)"):
    from calibration import parse_history_csv, summarize_history, DEMO_CSV
    st.markdown("Массовый баланс за каждый период: **истёрто = масса в начале + внесённая догрузка − масса в конце − масса выбракованных тел**. Отношение суммарного истирания к производству даёт наблюдаемый расход г/т.")
    st.download_button("Скачать шаблон CSV журнала", DEMO_CSV.encode("utf-8-sig"),"journal_template.csv","text/csv")
    journal=st.file_uploader("Загрузить журнал периодов CSV",type="csv",key="journal_upload")
    if journal:
        try:
            observation=parse_history_csv(journal.getvalue())
            st.dataframe(observation,hide_index=True,use_container_width=True)
            agg=summarize_history(observation)
            st.metric("Усреднённый наблюдаемый расход",f"{agg['gmcr_g_t']:.1f} г/т")
            st.caption("Это оценка по массе загрузки, не универсальный коэффициент. Для подбора степеней влияния скорости, мощности, диаметра и материала нужны замеры в нескольких существенно различающихся режимах, желательно по отдельным фракциям.")
        except Exception as e:
            st.error(f"Ошибка журнала: {e}")
