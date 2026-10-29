"""Самостоятельное настольное приложение для расчёта помола и износа.

Запуск: python main.py (или project/app.py). GUI требует Tkinter,
графики — Matplotlib, Excel — XlsxWriter. Streamlit не нужен.
"""
from __future__ import annotations

import json
import csv
import math
from copy import deepcopy
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from model import (CLASSES, MATERIALS, SIEVES, default_config, validate, throughput,
                   simulate_wear, quality_at, initial_cohorts, recommends, size_at_pass_percent, lab_bond_from_config)
from excel_export import export_excel
from calibration import parse_history_csv, summarize_history

ROOT = Path(__file__).resolve().parents[1]
DARK = '#0e1b29'
PANEL = '#142436'
LIGHT = '#eff5fb'
ACCENT = '#43b6c8'
MUTED = '#a7bccc'
FONT = 'DejaVu Sans'

# Входные параметры сохранены без упрощений, предусмотренных только сайтом.
# В форме редактируются режимные параметры и период прогноза.
# Трудноизменяемые характеристики клинкера и коэффициенты модели импортируются
# с протоколом лаборатории / истории, а F80, P80 и Wi_экспл. выводятся расчётом.
FIELDS = {
    'Подача и сырьё': [
        ('throughput_mode','Как задан выпуск','mode'),
        ('fresh_feed_tph','Измеренная подача продукта, т/ч','float'),
        ('measured_total_t','Произведено за период, т','float'),
        ('measured_hours','Длительность измерения, ч','float'),
        ('recycle_ratio','Измеренный возврат сепаратора, т/т','float'),
        ('material_hold_t','Оценка запаса материала в мельнице, т','float'),
        ('moisture_pct','Измеренная влажность, %','float'),
        ('temperature_c','Измеренная температура, °C','float'),
    ],
    'Прогноз износа': [
        ('horizon_h','Период прогноза, ч','float'),
        ('step_h','Расчётный шаг, ч','float'),
        ('reload_threshold_pct','Порог рекомендации догрузки, %','float'),
    ],
}
MODES = ['Измеренная подача, т/ч','Масса / время']
MEDIA_FIELDS = [('chamber','Камера'),('type','Тип'),('material','Материал'),
                ('diameter_mm','Диаметр, мм'),('initial_t','Масса, т'),('aspect','L/D цильпебса')]
RELOAD_FIELDS = [('hour','Час догрузки'),('chamber','Камера'),('type','Тип'),
                 ('material','Материал'),('diameter_mm','Диаметр, мм'),
                 ('tons','Добавить, т'),('aspect','L/D цильпебса')]


def is_valid_input(data: dict) -> bool:
    """Проверка файла импорта; не допускает внешнего кода или неизвестного формата."""
    if not isinstance(data,dict):
        raise ValueError('Ожидается JSON-объект конфигурации')
    validate(data)
    return True


def fmt(value, precision=3):
    if isinstance(value,float):
        return f'{value:.{precision}f}'.rstrip('0').rstrip('.')
    return str(value)


class ScrolledFrame(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,background=PANEL,highlightthickness=0)
        self.scroll=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.inner=ttk.Frame(self.canvas)
        self.inner.bind('<Configure>',lambda event:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.window=self.canvas.create_window((0,0),window=self.inner,anchor='nw')
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width))
        self.canvas.pack(side='left',fill='both',expand=True)
        self.scroll.pack(side='right',fill='y')


class RecordDialog(tk.Toplevel):
    def __init__(self,master,title,fields,initial,callback,mill_count):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.grab_set()
        self.resizable(False,False)
        self.configure(bg=PANEL)
        self.vars={}
        self.callback=callback
        self.fields=fields
        self.mill_count=mill_count
        wrap=ttk.Frame(self,padding=18)
        wrap.pack(fill='both',expand=True)
        for row,(key,label) in enumerate(fields):
            ttk.Label(wrap,text=label).grid(row=row,column=0,sticky='w',pady=5,padx=(0,15))
            var=tk.StringVar(value=str(initial.get(key,'')))
            self.vars[key]=var
            if key=='type':
                widget=ttk.Combobox(wrap,textvariable=var,values=['Шары','Цильпебс'],state='readonly',width=28)
            elif key=='material':
                widget=ttk.Combobox(wrap,textvariable=var,values=list(MATERIALS),state='readonly',width=28)
            elif key=='chamber':
                widget=ttk.Combobox(wrap,textvariable=var,values=[str(i+1) for i in range(mill_count)],state='readonly',width=28)
            else:
                widget=ttk.Entry(wrap,textvariable=var,width=31)
            widget.grid(row=row,column=1,sticky='ew',pady=5)
        controls=ttk.Frame(wrap)
        controls.grid(row=len(fields),column=0,columnspan=2,sticky='e',pady=(18,0))
        ttk.Button(controls,text='Отмена',command=self.destroy).pack(side='right',padx=5)
        ttk.Button(controls,text='Сохранить',style='Accent.TButton',command=self.submit).pack(side='right',padx=5)
        self.bind('<Escape>',lambda _:self.destroy())
        self.protocol('WM_DELETE_WINDOW',self.destroy)
        self.wait_visibility()
        self.focus_force()

    def submit(self):
        row={}
        try:
            for key,_ in self.fields:
                v=self.vars[key].get().strip().replace(',','.')
                row[key]=v if key in ('type','material') else int(float(v)) if key in ('drum','chamber') else float(v)
            if row.get('initial_t',row.get('tons',1)) <= 0 or row.get('diameter_mm',1) <= 0:
                raise ValueError('Масса и диаметр должны быть положительными')
            if row.get('hour',0)<0:
                raise ValueError('Час догрузки должен быть неотрицательным')
            self.callback(row)
            self.destroy()
        except (ValueError,TypeError) as e:
            messagebox.showerror('Проверьте значения',str(e),parent=self)


class DesktopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Цементная мельница')
        self.geometry('1350x850')
        self.minsize(780,590)
        self.configure(bg=DARK)
        self._setup_style()
        self.config_data=default_config()
        self.run_data=None
        self.quality=None
        self.history_rows=[]
        self.fields_vars={}
        self.feed_vars=[]
        self.lab_vars={}
        self.calibration_label=None
        self.sieve_vars={}
        self.mill_forms=[]
        self.metric_vars=[tk.StringVar(value='—') for _ in range(5)]
        self.status_var=tk.StringVar(value='Демонстрационные данные — не результаты измерений предприятия')
        self._make_layout()
        self.load_config(self.config_data,calculate=True)

    def _setup_style(self):
        s=ttk.Style(self)
        s.theme_use('clam')
        s.configure('.',background=PANEL,foreground=LIGHT,font=(FONT,10))
        s.configure('TFrame',background=PANEL)
        s.configure('TLabel',background=PANEL,foreground=LIGHT)
        s.configure('TButton',background='#253f55',foreground=LIGHT,padding=(10,7),borderwidth=0)
        s.map('TButton',background=[('active','#325777')])
        s.configure('Accent.TButton',background=ACCENT,foreground='#08202c',font=(FONT,10,'bold'))
        s.map('Accent.TButton',background=[('active','#69d3e4')])
        s.configure('TEntry',fieldbackground='#20364a',foreground='white',insertcolor='white',padding=5)
        s.configure('TCombobox',fieldbackground='#20364a',foreground=LIGHT,background='#20364a',padding=5)
        s.map('TCombobox',fieldbackground=[('readonly','#20364a')],foreground=[('readonly',LIGHT)])
        s.configure('TNotebook',background=DARK,borderwidth=0)
        # Компактная версия показывает полный заголовок раздела в списке выбора.
        # В Tk/ttk длинные заголовки вкладок НЕ переносятся автоматически.
        s.configure('Tabless.TNotebook',background=DARK,borderwidth=0)
        s.layout('Tabless.TNotebook.Tab', [])
        s.configure('TNotebook.Tab',background='#20364a',foreground=LIGHT,padding=(12,10))
        s.map('TNotebook.Tab',background=[('selected',PANEL)],foreground=[('selected',ACCENT)])
        s.configure('Treeview',background='#172d41',fieldbackground='#172d41',foreground=LIGHT,rowheight=26,borderwidth=0)
        s.configure('Treeview.Heading',background='#2d485d',foreground=LIGHT,font=(FONT,9,'bold'))
        s.map('Treeview',background=[('selected','#267d98')])
        s.configure('TLabelframe',background=PANEL,foreground=ACCENT)
        s.configure('TLabelframe.Label',background=PANEL,foreground=ACCENT,font=(FONT,10,'bold'))

    def _make_layout(self):
        # В верхней панели только частые действия; импорт и остальные команды в меню.
        menu=tk.Menu(self)
        files=tk.Menu(menu,tearoff=False)
        for label,cmd in [('Импорт конфигурации JSON…',self.open_json),
                          ('Импорт грансостава CSV…',self.open_psd),
                          ('Импорт лабораторного теста JSON…',self.open_lab_test),
                          ('Импорт истории работы CSV…',self.open_history),
                          ('Сохранить конфигурацию JSON…',self.save_json),
                          ('Экспорт Excel…',self.save_excel)]:
            files.add_command(label=label,command=cmd)
        files.add_separator()
        files.add_command(label='Выход',command=self.destroy)
        menu.add_cascade(label='Файл',menu=files)
        actions=tk.Menu(menu,tearoff=False)
        actions.add_command(label='Рассчитать',command=self.calculate)
        actions.add_command(label='Сбросить параметры',command=self.reset)
        menu.add_cascade(label='Модель',menu=actions)
        self.configure(menu=menu)
        header=tk.Frame(self,bg=DARK,padx=16,pady=10)
        header.pack(fill='x')
        tk.Label(header,text='Цементная мельница',bg=DARK,fg=LIGHT,
                 font=(FONT,18,'bold')).pack(side='left',padx=(0,14))
        ttk.Button(header,text='Экспорт Excel',command=self.save_excel).pack(side='right',padx=5)
        ttk.Button(header,text='Рассчитать',style='Accent.TButton',command=self.calculate).pack(side='right',padx=5)
        body=ttk.Panedwindow(self,orient='horizontal')
        body.pack(fill='both',expand=True,padx=9,pady=(0,8))
        left=ttk.Frame(body,width=470)
        right=ttk.Frame(body)
        body.add(left,weight=2)
        body.add(right,weight=4)
        self.lefttabs=ttk.Notebook(left)
        self.lefttabs_names=[]
        self.left_picker=self._create_tab_picker(left,self.lefttabs)
        self.lefttabs.pack(fill='both',expand=True)
        self.geometry_page=ScrolledFrame(self.lefttabs)
        self._add_page(self.lefttabs,self.lefttabs_names,self.geometry_page,'Барабан и камеры')
        self._make_geometry()
        for name in ('Подача и сырьё','Прогноз износа'):
            scroll=ScrolledFrame(self.lefttabs)
            self._add_page(self.lefttabs,self.lefttabs_names,scroll,
                           {'Подача и сырьё':'Подача и клинкер', 'Прогноз износа':'Прогноз износа'}[name])
            self._make_fields(scroll.inner,name)
        self.sieves_page=ScrolledFrame(self.lefttabs)
        self._add_page(self.lefttabs,self.lefttabs_names,self.sieves_page,'Сита')
        self._make_sieves()
        self.media_page=ttk.Frame(self.lefttabs,padding=8)
        self._add_page(self.lefttabs,self.lefttabs_names,self.media_page,'Мелющие тела')
        self._make_records(self.media_page,'media',MEDIA_FIELDS)
        self.reload_page=ttk.Frame(self.lefttabs,padding=8)
        self._add_page(self.lefttabs,self.lefttabs_names,self.reload_page,'Догрузки')
        self._make_records(self.reload_page,'manual_reloads',RELOAD_FIELDS)
        self.righttabs=ttk.Notebook(right)
        self.righttabs_names=[]
        self.right_picker=self._create_tab_picker(right,self.righttabs)
        self.righttabs.pack(fill='both',expand=True)
        self.overview_frame=ttk.Frame(self.righttabs)
        self.quality_frame=ttk.Frame(self.righttabs)
        self.fraction_frame=ttk.Frame(self.righttabs)
        self.reco_frame=ttk.Frame(self.righttabs)
        self.sample_frame=ttk.Frame(self.righttabs)
        self.history_frame=ttk.Frame(self.righttabs)
        for name,frame in [('Обзор',self.overview_frame),('Диаграмма помола',self.quality_frame),
                           ('Износ фракций',self.fraction_frame),('Рекомендации',self.reco_frame),
                           ('Таблица проб',self.sample_frame),('Заводская история',self.history_frame)]:
            self._add_page(self.righttabs,self.righttabs_names,frame,name)
        self._init_tab_picker(self.lefttabs,self.lefttabs_names,self.left_picker,left,680)
        self._init_tab_picker(self.righttabs,self.righttabs_names,self.right_picker,right,790)
        self._make_overview()
        self.fig_quality,self.canvas_quality=self._graph(self.quality_frame,(9.1,6.5))
        filterbar=ttk.Frame(self.fraction_frame,padding=(12,6))
        filterbar.pack(fill='x')
        ttk.Label(filterbar,text='Показать фракции:').pack(side='left',padx=5)
        self.fraction_filter=tk.StringVar(value='Все камеры')
        self.fraction_select=ttk.Combobox(filterbar,textvariable=self.fraction_filter,
                                         values=['Все камеры'],state='readonly',width=18)
        self.fraction_select.pack(side='left')
        self.fraction_select.bind('<<ComboboxSelected>>',lambda _:self._draw_fractions())
        self.fig_fractions,self.canvas_fractions=self._graph(self.fraction_frame,(9.1,6.5))
        self.reco_tree=self._tree(self.reco_frame,['Камера','Тип','Материал','Ø, мм','Потеря массы, т','Износ, %','Догрузить, шт','Догрузить, т'])
        self.sample_tree=self._tree(self.sample_frame,['Точка','Расстояние по камерам, м','Камера','R0.08, %','R0.045, %'])
        ttk.Label(self.history_frame,text='Импортируйте журнал работы из CSV для оценки фактического расхода мелющих тел.').pack(anchor='w',padx=12,pady=12)
        self.history_summary=ttk.Label(self.history_frame,text='История пока не загружена')
        self.history_summary.pack(anchor='w',padx=12)
        self.history_tree=self._tree(self.history_frame,['period','production_t','start_media_t','reload_t','end_media_t','removed_media_t','gmcr_g_t'])
        status=tk.Label(self,textvariable=self.status_var,anchor='w',padx=12,pady=6,bg='#21374a',fg=MUTED,font=(FONT,9))
        status.pack(fill='x',side='bottom')
        status.bind('<Configure>',lambda e:status.configure(wraplength=max(250,e.width-34)))

    def _add_page(self,notebook,names,frame,title):
        notebook.add(frame,text=title)
        names.append(title)

    @staticmethod
    def _create_tab_picker(parent,notebook):
        picker=ttk.Combobox(parent,values=[],state='readonly',font=(FONT,11))
        return picker

    def _init_tab_picker(self,notebook,names,picker,parent,limit):
        picker.configure(values=names)
        picker.current(0)
        picker.bind('<<ComboboxSelected>>',lambda _e: notebook.select(picker.current()))
        def on_tab(_e=None):
            index=notebook.index(notebook.select())
            if picker.current()!=index:picker.current(index)
        notebook.bind('<<NotebookTabChanged>>',on_tab)
        def layout(e):
            compact=e.width<limit
            notebook.configure(style='Tabless.TNotebook' if compact else 'TNotebook')
            if compact:
                if not picker.winfo_manager():picker.pack(fill='x',padx=8,pady=(5,7),before=notebook)
            elif picker.winfo_manager():
                picker.pack_forget()
        parent.bind('<Configure>',layout,add='+')

    def _make_overview(self):
        strip=ttk.Frame(self.overview_frame,padding=12)
        strip.pack(fill='x')
        captions=['Поток, т/ч','Износ за период, т','Масса загрузки, т','R0,08 в конце, %','Блейн-прокси, см²/г']
        cards=[]
        for label,var in zip(captions,self.metric_vars):
            card=ttk.Frame(strip)
            ttk.Label(card,text=label,foreground=MUTED,wraplength=175).pack(anchor='w')
            ttk.Label(card,textvariable=var,font=(FONT,14,'bold'),foreground=ACCENT).pack(anchor='w')
            cards.append(card)
        self._cards_columns=None
        def arrange_metrics(e):
            columns=5 if e.width>=930 else 3 if e.width>=570 else 2
            if columns==self._cards_columns:return
            self._cards_columns=columns
            for col in range(5):strip.columnconfigure(col,weight=1 if col<columns else 0)
            for i,card in enumerate(cards):card.grid(row=i//columns,column=i%columns,padx=7,pady=4,sticky='w')
        strip.bind('<Configure>',arrange_metrics)
        # Начальный вариант до первого события Configure.
        for i,card in enumerate(cards):card.grid(row=i//3,column=i%3,padx=7,pady=4,sticky='w')
        self.fig_overview,self.canvas_overview=self._graph(self.overview_frame,(9,6))
        self.derived_var=tk.StringVar(value='F80: —  |  P80: —  |  Wi эксплуатации: —')
        ttk.Label(self.overview_frame,textvariable=self.derived_var,foreground=ACCENT,wraplength=1050).pack(anchor='w',padx=14,pady=6)
        ttk.Label(self.overview_frame,text='Wi эксплуатации — оценка по мощности, потоку и F80/P80; лабораторный Wi отображается на вкладке «Подача и клинкер».',foreground=MUTED,wraplength=850).pack(anchor='w',padx=14,pady=6)
        ttk.Label(self.overview_frame,text='Модель исследовательская: коэффициенты и Блейн-прокси требуют проверки по измерениям предприятия.',foreground=MUTED).pack(anchor='w',padx=14,pady=6)

    def _graph(self,parent,figsize):
        rcParams['font.family']=FONT
        fig=Figure(figsize=figsize,dpi=94,facecolor=PANEL)
        canvas=FigureCanvasTkAgg(fig,master=parent)
        canvas.get_tk_widget().pack(fill='both',expand=True,padx=6,pady=5)
        return fig,canvas

    def _style_axes(self,ax,title,xlabel='Наработка, ч',ylabel=''):
        ax.set_facecolor('#192e42')
        ax.tick_params(colors=LIGHT,labelsize=8)
        ax.set_title(title,color=LIGHT,fontsize=11,pad=12)
        ax.set_xlabel(xlabel,color=MUTED,fontsize=9)
        ax.set_ylabel(ylabel,color=MUTED,fontsize=9)
        ax.grid(alpha=.19,color='white')
        for spine in ax.spines.values():spine.set_color('#3c586b')

    def _tree(self,parent,columns):
        group=ttk.Frame(parent)
        group.pack(fill='both',expand=True,padx=7,pady=7)
        t=ttk.Treeview(group,columns=columns,show='headings',selectmode='browse')
        for col in columns:
            t.heading(col,text=col)
            t.column(col,width=108 if len(col)<14 else 145,minwidth=75,anchor='center',stretch=False)
        vs=ttk.Scrollbar(group,orient='vertical',command=t.yview)
        hs=ttk.Scrollbar(group,orient='horizontal',command=t.xview)
        t.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        t.grid(row=0,column=0,sticky='nsew')
        vs.grid(row=0,column=1,sticky='ns')
        hs.grid(row=1,column=0,sticky='ew')
        group.rowconfigure(0,weight=1)
        group.columnconfigure(0,weight=1)
        return t

    def _make_records(self,frame,kind,fields):
        ttk.Label(frame,text='Одна строка — отдельная фракция или операция; данные редактируются до расчёта.',foreground=MUTED).pack(anchor='w',pady=(0,8))
        buttons=ttk.Frame(frame)
        buttons.pack(fill='x',pady=(0,5))
        ttk.Button(buttons,text='+ Добавить',command=lambda:self.edit_record(kind)).pack(side='left',padx=3)
        ttk.Button(buttons,text='Изменить',command=lambda:self.edit_record(kind,True)).pack(side='left',padx=3)
        ttk.Button(buttons,text='Удалить',command=lambda:self.delete_record(kind)).pack(side='left',padx=3)
        tree=self._tree(frame,[label for _,label in fields])
        tree.bind('<Double-1>',lambda _:self.edit_record(kind,True))
        if kind=='media':self.media_tree=tree
        else:self.reload_tree=tree

    def _make_sieves(self):
        root=self.sieves_page.inner
        ttk.Label(root,text='Выбор сит для графика и таблицы проб (как в веб-версии)',
                  foreground=ACCENT,font=(FONT,11,'bold')).pack(anchor='w',padx=12,pady=12)
        ttk.Label(root,text='Остатки вычисляются по грансоставу. Контрольные R0,08 и R0,045 считаются всегда, независимо от выбранных галочек.',
                  wraplength=430,foreground=MUTED).pack(anchor='w',padx=12)
        self.sieve_list=ttk.Frame(root,padding=8)
        self.sieve_list.pack(fill='x')
        inline=ttk.Frame(root,padding=10)
        inline.pack(fill='x')
        ttk.Label(inline,text='Новое сито, мм:').pack(side='left')
        self.custom_sieve=tk.StringVar(value='0.1')
        ttk.Entry(inline,textvariable=self.custom_sieve,width=10).pack(side='left',padx=5)
        ttk.Button(inline,text='+ Добавить',command=self.add_sieve).pack(side='left')
        self._load_sieves([.08,.045,.63])

    def _load_sieves(self,selected):
        for w in self.sieve_list.winfo_children():w.destroy()
        all_sizes=sorted(set(SIEVES)|set(selected),reverse=True)
        self.sieve_vars={}
        for x in all_sizes:
            v=tk.BooleanVar(value=x in selected)
            self.sieve_vars[x]=v
            ttk.Checkbutton(self.sieve_list,text=f'Сито №{x:g} мм',variable=v).pack(anchor='w',pady=3)

    def add_sieve(self):
        try:
            value=float(self.custom_sieve.get().strip().replace(',','.'))
            if not math.isfinite(value) or not .01<=value<=80:raise ValueError('Диаметр сита 0,01–80 мм')
            selected=[x for x,v in self.sieve_vars.items() if v.get()]
            if value not in selected:selected.append(value)
            self._load_sieves(selected)
        except ValueError as exc:messagebox.showerror('Некорректное сито',str(exc),parent=self)

    @staticmethod
    def _reset_tree_columns(tree,columns):
        tree.configure(columns=columns)
        for col in columns:
            tree.heading(col,text=col)
            tree.column(col,width=118,minwidth=75,stretch=False,anchor='center')

    def open_psd(self):
        """Импорт лабораторного грансостава: class,percent (10 строк, CLASSES)."""
        path=filedialog.askopenfilename(parent=self,title='Импорт анализа клинкера',
                                        initialdir=str(ROOT/'examples'),filetypes=[('CSV','*.csv')])
        if not path:return
        try:
            import io
            raw=Path(path).read_text(encoding='utf-8-sig')
            dialect=csv.Sniffer().sniff(raw[:2048],delimiters=',;\t')
            rows=list(csv.DictReader(io.StringIO(raw),dialect=dialect))
            measured={}
            for row in rows:
                label=row['class'].strip()
                measured[label]=float(row['percent'].replace(',','.'))
            if set(measured)!=set(CLASSES):raise ValueError('Нужно ровно 10 классов из примера: class,percent')
            vals=[measured[c] for c in CLASSES]
            if any(v<0 for v in vals) or not 99<=sum(vals)<=101:raise ValueError('Сумма долей должна быть около 100%')
            cfg=self.collect_config()
            cfg['feed_fraction']=vals
            self.load_config(cfg,calculate=True)
            self.status_var.set('Импортирован лабораторный грансостав: '+Path(path).name)
        except Exception as exc:messagebox.showerror('Импорт грансостава',str(exc),parent=self)

    def _make_geometry(self):
        root=self.geometry_page.inner
        ttk.Label(root,text='Один барабан; 1 или 2 камеры. Длины обеих камер задаются отдельно, общая длина рассчитывается.',
                  foreground=MUTED,wraplength=440).pack(anchor='w',padx=12,pady=12)
        ttk.Label(root,text='Внутренние диаметры камер могут отличаться из-за футеровки. Наружный/номинальный диаметр — верхняя граница.',
                  foreground=MUTED,wraplength=440).pack(anchor='w',padx=12,pady=(0,8))
        self.mill_box=ttk.Frame(root,padding=8)
        self.mill_box.pack(fill='both',expand=True)

    def _mill_field(self,parent,label,value,row):
        var=tk.StringVar(value=str(value))
        ttk.Label(parent,text=label).grid(row=row,column=0,sticky='w',padx=(5,10),pady=4)
        entry=ttk.Entry(parent,textvariable=var,width=17)
        entry.grid(row=row,column=1,sticky='ew',pady=4)
        return var,entry

    def _render_mills(self,mills):
        for w in self.mill_box.winfo_children():w.destroy()
        self.mill_forms=[]
        m=mills[0]
        box=ttk.LabelFrame(self.mill_box,text='Барабан',padding=(10,12))
        box.pack(fill='x',padx=4,pady=8)
        fields={}
        specs=[('name','Название',m.get('name','Мельница')),
               ('diameter_m','Диаметр барабана, м',m['diameter_m']),
               ('rpm','Обороты, об/мин',m['rpm']),
               ('power_kw','Измеренная мощность привода, кВт',m['power_kw']),
               ('diaphragm_m','Толщина перегородки, м',m['diaphragm_m']),
               ('ch1','Длина I камеры, м',m['chambers'][0]['length_m']),
               ('ch1d','Внутренний Ø I камеры, м',m['chambers'][0].get('diameter_m',m['diameter_m'])),
               ('ch2','Длина II камеры, м',m['chambers'][1]['length_m'] if len(m['chambers'])==2 else 5.0),
               ('ch2d','Внутренний Ø II камеры, м',m['chambers'][1].get('diameter_m',m['diameter_m']) if len(m['chambers'])==2 else m['diameter_m'])]
        for ix,(key,label,value) in enumerate(specs):
            fields[key],entry=self._mill_field(box,label,value,ix)
            if key in ('ch2','ch2d'):fields[key+'entry']=entry
        count=tk.StringVar(value=str(len(m['chambers'])))
        ttk.Label(box,text='Количество камер').grid(row=len(specs),column=0,sticky='w',pady=5)
        combo=ttk.Combobox(box,textvariable=count,values=['1','2'],state='readonly',width=14)
        combo.grid(row=len(specs),column=1,sticky='w')
        def toggle(_=None):
            for key in ('ch2','ch2d'):
                fields[key+'entry'].configure(state='normal' if count.get()=='2' else 'disabled')
        def on_change(event=None):
            toggle(event)
            if count.get()=='1':
                removed=sum(r['chamber']>1 for r in self.config_data['media'])
                self.config_data['media']=[r for r in self.config_data['media'] if r['chamber']==1]
                self.config_data['manual_reloads']=[r for r in self.config_data.get('manual_reloads',[]) if r['chamber']==1]
                self._refresh_records()
                if removed:
                    self.status_var.set(f'При переходе на одну камеру удалены {removed} фракций II камеры. Сохраните JSON при необходимости.')
        combo.bind('<<ComboboxSelected>>',on_change)
        toggle()
        fields['chcount']=count
        self.mill_forms.append(fields)
        box.columnconfigure(1,weight=1)

    def _make_fields(self,frame,name):
        box=ttk.Frame(frame,padding=(13,14))
        box.pack(fill='both',expand=True)
        for row,(key,label,typ) in enumerate(FIELDS[name]):
            ttk.Label(box,text=label,wraplength=260).grid(row=row,column=0,sticky='w',padx=(0,10),pady=7)
            var=tk.StringVar()
            self.fields_vars[key]=var
            if typ=='mode':
                e=ttk.Combobox(box,textvariable=var,values=MODES,state='readonly',width=25)
            else:
                e=ttk.Entry(box,textvariable=var,width=19)
            e.grid(row=row,column=1,sticky='ew',pady=7)
        if name=='Подача и сырьё':
            ttk.Separator(box,orient='horizontal').grid(row=100,columnspan=2,sticky='ew',pady=12)
            ttk.Label(box,text='Клинкер: лабораторный грансостав, % (импорт JSON/CSV)',foreground=ACCENT,font=(FONT,11,'bold')).grid(row=101,columnspan=2,sticky='w',pady=7)
            for i,label in enumerate(CLASSES):
                ttk.Label(box,text=label).grid(row=102+i,column=0,sticky='w',pady=4)
                v=tk.StringVar()
                self.feed_vars.append(v)
                ttk.Entry(box,textvariable=v,width=19,state='readonly').grid(row=102+i,column=1,sticky='ew',pady=4)
        if name=='Подача и сырьё':
            ttk.Separator(box,orient='horizontal').grid(row=125,columnspan=2,sticky='ew',pady=12)
            ttk.Label(box,text='Лабораторные свойства клинкера',foreground=ACCENT,
                      font=(FONT,11,'bold')).grid(row=126,columnspan=2,sticky='w',pady=6)
            for j,(key,label) in enumerate([
                ('lab_wi','Индекс Бонда лабораторный, кВт·ч/т'),
                ('lab_origin','Как определён Wi'),
                ('f80','F80 подачи, мкм (расчёт)'),
                ('grind','Размолоспособность (протокол)'),
                ('abrasion','Абразивность (протокол)'),
                ('density','Насыпная плотность, кг/м³')]):
                ttk.Label(box,text=label,wraplength=260).grid(row=127+j,column=0,sticky='w',pady=5)
                var=tk.StringVar(value='нет данных')
                self.lab_vars[key]=var
                ttk.Label(box,textvariable=var,foreground=ACCENT,wraplength=180).grid(row=127+j,column=1,sticky='w',pady=5)
            ttk.Label(box,text='Wi рассчитывается до эксплуатации только по импортированному лабораторному протоколу Бонда (P1, Gpr, F80, P80), а не по размерам барабана.',
                      wraplength=450,foreground=MUTED).grid(row=134,column=0,columnspan=2,sticky='w',pady=6)
            ttk.Button(box,text='Импорт лаборатории JSON…',command=self.open_lab_test).grid(row=135,column=0,columnspan=2,sticky='ew',pady=8)
        else:
            ttk.Separator(box,orient='horizontal').grid(row=30,columnspan=2,sticky='ew',pady=12)
            ttk.Label(box,text='Калибровка износа (из импортированных данных)',foreground=ACCENT,
                      font=(FONT,11,'bold')).grid(row=31,column=0,columnspan=2,sticky='w',pady=6)
            self.calibration_label=tk.StringVar(value='нет данных')
            ttk.Label(box,textvariable=self.calibration_label,foreground=MUTED,
                      wraplength=430,justify='left').grid(row=32,column=0,columnspan=2,sticky='w',pady=5)
            ttk.Label(box,text='Коэффициенты модели не являются рычагами управления мельницей: их оценивают по замерам и истории. Импорт: Файл → Импорт истории работы CSV.',
                      wraplength=430,foreground=MUTED).grid(row=33,column=0,columnspan=2,sticky='w',pady=5)
        box.columnconfigure(1,weight=1)

    def _update_lab_labels(self,cfg):
        wi,origin=lab_bond_from_config(cfg)
        vals={
            'lab_wi': 'нет протокола' if wi is None else f'{wi:.2f}',
            'lab_origin': origin,
            'f80': f'{size_at_pass_percent(cfg["feed_fraction"]):.0f}',
            'grind':f'{cfg["grindability"]:.3g} (из входных данных)',
            'abrasion':f'{cfg["abrasion_factor"]:.3g} (из входных данных)',
            'density':f'{cfg["feed_bulk_density"]:,.0f}'.replace(',',' '),
        }
        for key,value in vals.items():self.lab_vars[key].set(value)
        if self.calibration_label is not None:
            label=('калиброван по истории' if cfg.get('wear_calibrated',False)
                   else 'демонстрационная оценка — не заводское измерение')
            self.calibration_label.set(f"Базовый удельный износ: {cfg['wear_g_t']:.2f} г/т ({label})\n"
                                       f"Показатель закона размера Δ: {cfg['delta']:.2f}\n"
                                       f"Диаметр выбраковки: {cfg['retention_mm']:.1f} мм")

    def open_lab_test(self):
        path=filedialog.askopenfilename(parent=self,title='Импорт лабораторного протокола Бонда',
                                        initialdir=str(ROOT/'examples'),filetypes=[('JSON','*.json')])
        if not path:return
        try:
            incoming=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if not isinstance(incoming,dict):raise ValueError('Ожидается JSON-объект')
            allowed={'bond_test','work_index_kwh_t','grindability','abrasion_factor','feed_bulk_density'}
            if not any(k in incoming for k in allowed):
                raise ValueError('Нет лабораторных параметров в JSON')
            cfg=self.collect_config()
            # Протокол с исходными данными имеет приоритет над готовым Wi.
            for k in allowed:
                if k in incoming:cfg[k]=incoming[k]
            if 'bond_test' in incoming:cfg['work_index_kwh_t']=None
            is_valid_input(cfg)
            self.load_config(cfg,calculate=True)
            self.status_var.set('Лабораторные данные импортированы: '+Path(path).name)
        except Exception as exc:messagebox.showerror('Лабораторный протокол',str(exc),parent=self)

    def _collect_mills(self):
        form=self.mill_forms[0]
        def n(key):
            try:return float(form[key].get().strip().replace(',','.'))
            except ValueError as e:raise ValueError(f'Проверьте геометрию: {key}') from e
        chapters=[{'length_m':n('ch1'),'diameter_m':n('ch1d')}]
        if form['chcount'].get()=='2':chapters.append({'length_m':n('ch2'),'diameter_m':n('ch2d')})
        dph=n('diaphragm_m')
        return [dict(name=form['name'].get(),diameter_m=n('diameter_m'),rpm=n('rpm'),
                     power_kw=n('power_kw'),diaphragm_m=dph,chambers=chapters,
                     length_m=sum(ch['length_m'] for ch in chapters)+(len(chapters)-1)*dph)]

    def collect_config(self):
        cfg=deepcopy(self.config_data)
        cfg['mills']=self._collect_mills()
        for key,var in self.fields_vars.items():
            try:cfg[key]=var.get() if key=='throughput_mode' else float(var.get().strip().replace(',','.'))
            except ValueError as e:raise ValueError(f'Некорректное значение параметра {key}') from e
        try:cfg['feed_fraction']=[float(v.get().strip().replace(',','.')) for v in self.feed_vars]
        except ValueError as e:raise ValueError('Проверьте фракционный состав сырья') from e
        cfg['sieves_mm']=sorted((float(x) for x,v in self.sieve_vars.items() if v.get()),reverse=True)
        cfg['media']=deepcopy(self.config_data['media'])
        cfg['manual_reloads']=deepcopy(self.config_data.get('manual_reloads',[]))
        is_valid_input(cfg)
        return cfg

    def load_config(self,cfg,calculate=False):
        is_valid_input(cfg)
        self.config_data=deepcopy(cfg)
        self._render_mills(cfg['mills'])
        for key,var in self.fields_vars.items():var.set(str(cfg.get(key,'')))
        for var,value in zip(self.feed_vars,cfg['feed_fraction']):var.set(str(value))
        self._load_sieves(cfg.get('sieves_mm',SIEVES))
        self._refresh_records()
        self._update_lab_labels(cfg)
        self.run_data=None
        self.quality=None
        if calculate:self.calculate()

    def _refresh_records(self):
        for tree,kind,fields in [(self.media_tree,'media',MEDIA_FIELDS),
                                 (self.reload_tree,'manual_reloads',RELOAD_FIELDS)]:
            tree.delete(*tree.get_children())
            for index,r in enumerate(self.config_data.get(kind,[])):
                tree.insert('', 'end',iid=str(index),values=[fmt(r.get(key,'')) for key,_ in fields])

    def edit_record(self,kind,existing=False):
        tree=self.media_tree if kind=='media' else self.reload_tree
        fields=MEDIA_FIELDS if kind=='media' else RELOAD_FIELDS
        selected=tree.selection()
        if existing and not selected:return
        index=int(selected[0]) if existing else None
        defaults=dict(drum=1,chamber=1,type='Шары',material='Сталь',diameter_mm=40.,
                      initial_t=1.,hour=0,tons=.5,aspect=1.0)
        if index is not None:defaults.update(self.config_data[kind][index])
        def save(row):
            try:
                trial=deepcopy(self.config_data)
                row['drum']=1
                if index is None:trial[kind].append(row)
                else:trial[kind][index]=row
                is_valid_input(self.collect_config()|{kind:trial[kind]})
                self.config_data[kind]=trial[kind]
                self._refresh_records()
                self.status_var.set('Данные изменены. Нажмите «Рассчитать» для обновления прогноза.')
            except Exception as exc:
                raise ValueError(str(exc)) from exc
        RecordDialog(self,'Изменить строку' if existing else 'Добавить строку',fields,defaults,save,len(self._collect_mills()[0]['chambers']))

    def delete_record(self,kind):
        tree=self.media_tree if kind=='media' else self.reload_tree
        selected=tree.selection()
        if not selected:return
        self.config_data[kind].pop(int(selected[0]))
        self._refresh_records()
        self.status_var.set('Строка удалена. Пересчитайте прогноз.')

    def open_json(self):
        path=filedialog.askopenfilename(parent=self,title='Импорт параметров мельницы',
                                        initialdir=str(ROOT/'examples'),filetypes=[('JSON','*.json')])
        if not path:return
        try:
            with open(path,'r',encoding='utf-8-sig') as f:incoming=json.load(f)
            self.load_config(incoming,calculate=True)
            self.status_var.set(f'Загружена конфигурация: {Path(path).name}')
        except Exception as e:messagebox.showerror('Ошибка импорта',str(e),parent=self)

    def save_json(self):
        try:cfg=self.collect_config()
        except Exception as e:messagebox.showerror('Ошибка данных',str(e),parent=self);return
        path=filedialog.asksaveasfilename(parent=self,title='Сохранить параметры',defaultextension='.json',
                                         initialfile='mill_config.json',filetypes=[('JSON','*.json')])
        if not path:return
        try:
            with open(path,'w',encoding='utf-8') as f:json.dump(cfg,f,ensure_ascii=False,indent=2)
            self.status_var.set(f'Конфигурация сохранена: {path}')
        except OSError as e:messagebox.showerror('Ошибка сохранения',str(e),parent=self)

    def open_history(self):
        path=filedialog.askopenfilename(parent=self,title='Загрузить заводской журнал',
                                        initialdir=str(ROOT/'examples'),filetypes=[('CSV','*.csv')])
        if not path:return
        try:
            rows=parse_history_csv(Path(path).read_bytes())
            self.history_rows=rows
            self.history_tree.delete(*self.history_tree.get_children())
            for r in rows:
                self.history_tree.insert('', 'end',values=[fmt(r.get(key,'')) for key in ['period','production_t','start_media_t','reload_t','end_media_t','removed_media_t','gmcr_g_t']])
            summary=summarize_history(rows)
            self.history_summary.config(text=f"Периодов: {summary['periods']}  •  Износ: {summary['wear_t']:.3f} т  •  Фактический расход: {summary['gmcr_g_t']:.2f} г/т")
            self.righttabs.select(self.history_frame)
            if messagebox.askyesno('Калибровка',f"Установить фактический расход {summary['gmcr_g_t']:.2f} г/т как базовый коэффициент модели?\n\nЭто оценка по массовому балансу, не полная калибровка факторов.",parent=self):
                cfg=self.collect_config()
                cfg['wear_g_t']=summary['gmcr_g_t']
                cfg['wear_calibrated']=True
                self.load_config(cfg,calculate=True)
        except Exception as e:messagebox.showerror('Ошибка CSV',str(e),parent=self)

    def reset(self):
        if messagebox.askyesno('Сброс', 'Вернуть демонстрационную конфигурацию мельницы №3?',parent=self):
            self.load_config(default_config(),calculate=True)
            self.status_var.set('Демонстрационная конфигурация восстановлена')

    def calculate(self):
        try:
            cfg=self.collect_config()
            run=simulate_wear(cfg)
            quality=quality_at(cfg,run['cohorts'])
            recommendation=recommends(cfg,run)
            self.config_data=deepcopy(cfg)
            self.run_data=run
            self.quality=quality
            self._render_results(cfg,run,quality,recommendation)
            self._update_lab_labels(cfg)
            self.status_var.set(f"Расчёт завершён: {len(run['rows'])} шагов, {len(recommendation)} предложений догрузки. Износ и Блейн — расчётный прогноз.")
        except Exception as e:
            messagebox.showerror('Ошибка расчёта',str(e),parent=self)
            self.status_var.set('Не удалось выполнить расчёт: проверьте входные параметры')

    def _render_results(self,cfg,run,quality,recommendation):
        end=run['rows'][-1]
        for var,text in zip(self.metric_vars,[fmt(run['throughput']['product_tph'],1),
                                              fmt(run['total_wear_t'],3),
                                              fmt(end['total_media_t'],2),
                                              fmt(quality['r008'],2),
                                              fmt(quality['blaine_proxy'],0)]):var.set(text)
        self._populate(self.reco_tree,recommendation,['Камера','Тип','Материал','Ø, мм','Потеря массы, т','Износ, %','Догрузить, шт','Догрузить, т'])
        # Сита и набор колонок таблицы обновляются от выбранных размеров.
        probe_cols=['Точка','Расстояние по камерам, м','Камера']+[f'R{x:g}, %' for x in cfg['sieves_mm']]
        self._reset_tree_columns(self.sample_tree,probe_cols)
        self._populate(self.sample_tree,quality['samples'],probe_cols)
        x=[r['hours'] for r in run['rows']]
        self.fig_overview.clear()
        a=self.fig_overview.subplots(2,2)
        self._style_axes(a[0,0],'Накопленный износ, т',ylabel='т')
        a[0,0].plot(x,[r['loss_t'] for r in run['rows']],color='#61c7dc',lw=2)
        self._style_axes(a[0,1],'Масса загрузки, т',ylabel='т')
        a[0,1].plot(x,[r['total_media_t'] for r in run['rows']],color='#e8af63',lw=2)
        self._style_axes(a[1,0],'Удельный расход всей загрузки, г/т',ylabel='г/т')
        a[1,0].plot(x,[r['Вся загрузка, г/т'] for r in run['coefficient_history']],color='#89c992',lw=2)
        self._style_axes(a[1,1],'Средний диаметр камеры I, мм',ylabel='мм')
        a[1,1].plot(x,[r['Б1К1 Dср, мм'] for r in run['rows']],color='#d5a6ee',lw=2)
        self.fig_overview.subplots_adjust(hspace=.55,wspace=.3,left=.10,right=.96,bottom=.12,top=.92)
        self.canvas_overview.draw_idle()
        self.fig_quality.clear()
        qax=self.fig_quality.add_subplot(111)
        self._style_axes(qax,'Диаграмма помола по длине камер','Расстояние, м','Полный остаток, %')
        pos=[p['Расстояние по камерам, м'] for p in quality['samples']]
        labels=[(f'R{x:g}, %',c) for x,c in zip(cfg['sieves_mm'],['#6fc8df','#dfb36c','#9bd89c','#e8af63','#d5a6ee','#c8d98d','#df9fbd'])]
        for label,color in labels:
            if label in quality['samples'][0]:
                qax.plot(pos,[p[label] for p in quality['samples']],label=label,marker='o',markersize=3,color=color,lw=2)
        qax.legend(facecolor=PANEL,labelcolor=LIGHT,framealpha=.7,loc='upper right')
        self.fig_quality.tight_layout(pad=2.2)
        self.canvas_quality.draw_idle()
        names=['Все камеры']+[f'Б1К{j}' for j,_ in enumerate(cfg['mills'][0]['chambers'],1)]
        self.fraction_select.configure(values=names)
        if self.fraction_filter.get() not in names:self.fraction_filter.set(names[0])
        wi=quality.get('operating_wi_kwh_t')
        label='не определён' if wi is None else f'{wi:.2f} кВт·ч/т'
        self.derived_var.set(f"F80 входа: {quality['f80_um']:.0f} мкм (из лабораторного грансостава)  |  "
                             f"P80 выхода: {quality['p80_um']:.0f} мкм (модель)  |  "
                             f"Wi эксплуатационный: {label} (оценка, не лабораторный Бонд)")
        self._draw_fractions()

    def _draw_fractions(self):
        if self.run_data is None:return
        run=self.run_data
        self.fig_fractions.clear()
        axs=self.fig_fractions.subplots(3,1)
        specs=[('diameter_history','Диаметр фракции, мм','мм'),
               ('fraction_mass_history','Масса фракции, т','т'),
               ('coefficient_history','Удельный износ фракции, г/т','г/т')]
        selected=self.fraction_filter.get()
        palette=['#72bddf','#d3a56b','#a9d6a2','#d58bc6','#e9dc7e','#a7a8e9','#e0a79a','#91d3cc']
        for ax,(key,title,unit) in zip(axs,specs):
            self._style_axes(ax,title,ylabel=unit)
            rows=run[key]
            names=[n for n in rows[0] if n not in ('Наработка, ч','Вся загрузка, г/т')
                   and (selected=='Все камеры' or n.startswith(selected+' '))]
            for i,n in enumerate(names):
                ax.plot([r['Наработка, ч'] for r in rows],
                        [r.get(n,math.nan) for r in rows],lw=1.6,
                        label=n.replace(' · ', ' '),color=palette[i%len(palette)])
            if not names:ax.text(.5,.5,'Нет данных по выбранной камере',transform=ax.transAxes,color=LIGHT,ha='center')
        axs[0].legend(loc='upper left',fontsize=6,facecolor=PANEL,labelcolor=LIGHT,
                      framealpha=.85,ncol=2)
        self.fig_fractions.subplots_adjust(left=.12,right=.96,top=.94,bottom=.10,hspace=.65)
        self.canvas_fractions.draw_idle()

    @staticmethod
    def _populate(tree,rows,columns):
        tree.delete(*tree.get_children())
        for r in rows:tree.insert('', 'end',values=[fmt(r.get(c,'')) for c in columns])

    def save_excel(self):
        try:
            cfg=self.collect_config()
            # Не экспортируем предыдущий расчёт после изменения параметров.
            run=simulate_wear(cfg)
            output=export_excel(cfg,run)
            name=filedialog.asksaveasfilename(parent=self,title='Экспорт отчёта Excel',
                                              defaultextension='.xlsx',initialfile='cement_wear_report.xlsx',
                                              filetypes=[('Excel','*.xlsx')])
            if not name:return
            Path(name).write_bytes(output)
            self.status_var.set(f'Excel сохранён: {name}')
            messagebox.showinfo('Excel',f'Отчёт с таблицами и графиками сохранён:\n{name}',parent=self)
        except Exception as e:
            messagebox.showerror('Ошибка экспорта',str(e),parent=self)


def main():
    app=DesktopApp()
    app.mainloop()


if __name__=='__main__':
    main()
