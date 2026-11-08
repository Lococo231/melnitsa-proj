"""Дополнение PySide6 для истории изменений и панелей мельницы.

Подключается ПОСЛЕ production_ui.install и workflow_ui.install.
Сохраняет старые вкладки и базовые сценарии, добавляя рабочую хронологию.
"""
from __future__ import annotations

from copy import deepcopy
import math

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter,
    QTableWidget, QTabWidget, QVBoxLayout, QWidget,
)
from matplotlib.lines import Line2D

from model import MATERIALS, mass_kg, piece_count
from production_planning import PROFILES
from operation_timeline import (PARAMETERS, METRICS, simulate_operation_timeline,
                                operation_day)
from production_ui import show_help_dialog
import workflow_ui

COLORS = ['#66cbe1','#e9ad73','#95d6ad','#d4a4ef','#e5d46f',
          '#9bbbef','#e2a2b8','#8de0d6','#a5cad9']


def _format_x(value):
    if isinstance(value, float):
        return f'{value:.5g}'
    return str(value)


def _fill(window, table: QTableWidget, rows: list[dict], empty_text='Изменений нет'):
    if rows:
        window._populate_result(table, rows, list(rows[0]))
    else:
        window._populate_result(table, [{'Состояние':empty_text}], ['Состояние'])
    table.resizeColumnsToContents()


def _timeline_sim_plot(window, result: dict) -> None:
    """Показываем ограничения, состояние цемента и вес во время операций."""
    panel = window.sim_plot
    fig = panel.figure
    fig.clear()
    axes = fig.subplots(4, 1, sharex=True)
    baseline = result['baseline']
    optimized = result.get('optimized')
    if not baseline:
        return
    rowspec = [ ('r008', 'R0,08', '%'), ('r0045', 'R0,045', '%'),
                ('blaine_proxy', 'Блейн (расчётный)', 'см²/г'),
                ('media_mass_t', 'Масса мелющих тел', 'т')]
    times = [row['hour'] for row in baseline]
    for i, (key, title, unit) in enumerate(rowspec):
        ax = axes[i]
        panel.axis(ax, title, ylabel=unit)
        y = [row[key] for row in baseline]
        ax.plot(times, y, color=COLORS[1], linewidth=2, label='Без доп. коррекции')
        if optimized:
            ax.plot([row['hour'] for row in optimized],
                    [row[key] for row in optimized], color=COLORS[0], lw=1.9,
                    label='С доп. коррекцией')
        if i < 3:
            # У разных марок цемента разные пределы: границы зависят от часа.
            lo = [row.get(key+'_minimum') for row in baseline]
            hi = [row.get(key+'_maximum') for row in baseline]
            lo_line = [float('nan') if v is None else v for v in lo]
            hi_line = [float('nan') if v is None else v for v in hi]
            ax.step(times,lo_line,where='post',color='#ef737a',ls='--',lw=1.2,label='Минимум')
            ax.step(times,hi_line,where='post',color='#ef737a',ls='--',lw=1.2,label='Максимум')
            violations = [row for row in baseline if not row['ok'] and
                          ((row.get(key+'_minimum') is not None and row[key]<row[key+'_minimum']) or
                           (row.get(key+'_maximum') is not None and row[key]>row[key+'_maximum']))]
            if violations:
                ax.scatter([row['hour'] for row in violations],
                           [row[key] for row in violations], s=17, color='#ff6175',zorder=5)
            envelope = y + [v for v in lo_line+hi_line if math.isfinite(v)]
        else:
            envelope = y
        if result.get('action'):
            ax.axvline(result['action']['hour'],color='#d4a4ef',ls=':',lw=1.4,label='_nolegend_')
        # Не заполняем весь экран пустым пространством, но не обрезаем границы.
        if envelope:
            ymin,ymax=min(envelope),max(envelope)
            padding=max((ymax-ymin)*.15, 0.09 if i<2 else (8 if i==2 else .04))
            ax.set_ylim(ymin-padding,ymax+padding)
        ax.set_xlim(0,max(times[-1],.01))
        ax.ticklabel_format(axis='y',useOffset=False)
        for event in result.get('cement_changes',[]):
            if event.get('Показатель / сито')=='R0,08':
                ax.axvline(event['Час наработки'],color='#9a90f7',ls=':',lw=.8,alpha=.7)
    # Легенда одна, над графиками, поэтому линии не перекрываются текстом.
    fig.legend(handles=[
        Line2D([0],[0],color=COLORS[1],lw=2,label='С запланированными изменениями'),
        Line2D([0],[0],color=COLORS[0],lw=2,label='После доп. коррекции'),
        Line2D([0],[0],color='#ef737a',lw=1.5,ls='--',label='Целевые границы'),
        Line2D([0],[0],color='#9a90f7',lw=1.2,ls=':',label='Смена цемента'),
    ],loc='upper center',bbox_to_anchor=(.52,.996),ncol=4,
    fontsize=7,frameon=False,labelcolor='#ebf5fc')
    axes[-1].set_xlabel('Наработка, ч',color='#aec0ce')
    fig.subplots_adjust(hspace=.76,left=.11,right=.97,top=.93,bottom=.07)
    panel.set_time_range(result['hours'])


def _timeline_history_plot(window, result: dict) -> None:
    panel = window.history_plot
    fig = panel.figure
    fig.clear()
    axes = fig.subplots(3,1,sharex=True)
    rows = result['baseline']
    if not rows: return
    t = [r['hour'] for r in rows]
    # 1. Состав загрузки: масса каждой номинальной фракции в каждый момент.
    ax = axes[0]
    panel.axis(ax,'Мелющие тела — масса фракций','Наработка, ч','т')
    names = sorted({name for row in rows for name in row['media_by_fraction_t']})
    for i,name in enumerate(names):
        ax.plot(t,[r['media_by_fraction_t'].get(name,0.) for r in rows],
                color=COLORS[i%len(COLORS)],lw=1.35,label=name)
    if names:
        fig.legend(ax.get_lines(),names,loc='center left',bbox_to_anchor=(.70,.76),
                   fontsize=6.9,frameon=False,labelcolor='#ebf5fc')
    # 2. Изменение марки цемента как ступенчатая функция во времени.
    ax = axes[1]
    panel.axis(ax,'Вид цемента — активная технологическая карта','Наработка, ч','')
    profiles = list(dict.fromkeys(r['profile'] for r in rows))
    ids = [profiles.index(r['profile']) for r in rows]
    ax.step(t,ids,where='post',lw=2.1,color=COLORS[4],label='Марка цемента')
    ax.set_yticks(list(range(len(profiles))))
    ax.set_yticklabels(profiles,fontsize=7)
    ax.set_ylim(-.5,max(.5,len(profiles)-.5))
    # 3. Несоизмеримые единицы сводим к относительной шкале от первой точки.
    ax = axes[2]
    panel.axis(ax,'Изменение параметров — % от стартового значения','Наработка, ч','%')
    for i,(key,label) in enumerate([('rpm','Обороты'),('diameter_m','Диаметр'),
                                    ('power_kw','Мощность'),('fresh_feed_tph','Выпуск')]):
        ref = float(rows[0][key])
        if abs(ref)<1e-12: continue
        ax.step(t,[100*(float(row[key])/ref-1) for row in rows],where='post',
                color=COLORS[(i+2)%len(COLORS)],lw=1.5,label=label)
    ax.legend(fontsize=7,ncol=2,frameon=False,labelcolor='#ebf5fc',loc='upper right')
    for a in axes:
        a.ticklabel_format(axis='x',useOffset=False)
    axes[-1].set_xlabel('Наработка, ч',color='#aec0ce')
    fig.subplots_adjust(hspace=.85,left=.18,right=.69,top=.95,bottom=.09)
    panel.set_time_range(result['hours'])


def _dynamic_fraction_plot(window, result: dict) -> None:
    """Полные кривые износа, включая плановые догрузки/выгрузки и режим."""
    panel=window.fraction_plot
    fig=panel.figure
    fig.clear()
    axes=fig.subplots(3,1,sharex=True)
    rows=result['baseline']
    if not rows:return
    hours=[row['hour'] for row in rows]
    selected=window.fraction_combo.currentText()
    metrics=[('diameter_by_fraction_mm','Диаметр фракций','мм'),
             ('media_by_fraction_t','Масса фракций','т'),
             ('wear_by_fraction_g_t','Удельный износ фракций','г/т')]
    for ax,(key,title,unit) in zip(axes,metrics):
        panel.axis(ax,title,ylabel=unit)
        names=sorted({name for row in rows for name in row.get(key,{})
                      if selected=='Все камеры' or name.startswith('К' + selected.split('К')[-1] + ' ')})
        for i,name in enumerate(names):
            ax.plot(hours,[row.get(key,{}).get(name,float('nan')) for row in rows],
                    lw=1.5,color=COLORS[i%len(COLORS)],label=name)
        if ax==axes[0] and names:
            fig.legend(ax.get_lines(),names,loc='center left',bbox_to_anchor=(.68,.52),
                       fontsize=7,frameon=False,labelcolor='#ebf5fc')
    axes[-1].set_xlabel('Наработка, ч',color='#aec0ce')
    fig.subplots_adjust(hspace=.80,left=.11,right=.64,top=.96,bottom=.09)
    panel.set_time_range(result['hours'])


def _dynamic_forecast_plot(window, result: dict) -> None:
    """Масса и диаметры фактических целочисленных фракций по всем сменам."""
    panel=window.forecast_plot
    fig=panel.figure
    fig.clear()
    axes=fig.subplots(2,1,sharex=True)
    rows=result['baseline']
    if not rows:return
    t=[r['hour'] for r in rows]
    ax=axes[0]
    panel.axis(ax,'Масса загрузки с учётом событий',ylabel='т')
    ax.plot(t,[r['media_mass_t'] for r in rows],color=COLORS[0],lw=2,label='Масса загрузки, т')
    secondary=ax.twinx()
    secondary.set_ylabel('Истирание, т',color=COLORS[1],fontsize=8)
    secondary.tick_params(axis='y',colors=COLORS[1],labelsize=8)
    secondary.set_facecolor('none')
    secondary.plot(t,[r['wear_cumulative_t'] for r in rows],color=COLORS[1],lw=1.8,
                   label='Накопленный износ, т')
    axes[1].set_facecolor('#162a3d')
    for i,name in enumerate(sorted({name for r in rows for name in r['chamber_diameters_mm']})):
        axes[1].plot(t,[row['chamber_diameters_mm'].get(name,float('nan')) for row in rows],
                     lw=1.8,color=COLORS[(i+3)%len(COLORS)],label=name)
    panel.axis(axes[1],'Средний диаметр тел по камерам',ylabel='мм')
    axes[1].legend(fontsize=7,frameon=False,labelcolor='#ebf5fc')
    axes[1].set_xlabel('Наработка, ч',color='#aec0ce')
    ax.legend(fontsize=7,frameon=False,labelcolor='#ebf5fc',loc='upper left')
    secondary.legend(fontsize=7,frameon=False,labelcolor='#ebf5fc',loc='upper right')
    fig.subplots_adjust(hspace=.60,left=.11,right=.86,top=.96,bottom=.10)
    panel.set_time_range(result['hours'])
    window.forecast_summary.setText(
        'Прогноз учитывает смены цемента, операции над телами и изменения режима. '
        f'Начальная масса {rows[0]["media_mass_t"]:.4f} т; '
        f'в конце {rows[-1]["media_mass_t"]:.4f} т; '
        f'суммарное истирание {rows[-1]["wear_cumulative_t"]:.4f} т. '
        'Выгрузка и истирание учитываются отдельно.')
    initial=rows[0]['media_by_fraction_t']
    ending=rows[-1]['media_by_fraction_t']
    names=sorted(set(initial)|set(ending))
    table=[{'Фракция':name,'В начале, т':initial.get(name,0.),
            'В конце, т':ending.get(name,0.),
            'Изменение, т':ending.get(name,0.)-initial.get(name,0.)} for name in names]
    _fill(window,window.forecast_table,table)


def _render_timeline_status(window, result: dict) -> None:
    bad = result.get('first_bad')
    text=(f"Работа {result['days']} дней × {result['hours_per_day']:g} ч = "
          f"{result['hours']:g} ч наработки.\n")
    if bad:
        text += (f"Первое отклонение: {operation_day(bad['hour'],result['hours_per_day'])}, "
                 + ', '.join(bad['violations']) + '.\n')
    text += result['status']
    action = result.get('action')
    if action:
        verb='Догрузить' if action['direction']=='add' else 'Выгрузить'
        text += (f"\n{verb} {action['pieces']} шт ({action['tons']:.5g} т) "
                 f"на часу {action['hour']:g}, кам. {action['target']['chamber']}, "
                 f"Ø{action['target']['diameter_mm']:g} мм; "
                 f"расчётное удержание до {action['valid_to']:g} ч.")
    text += ('\nПлановые изменения учтены на всём периоде. Блейн расчётный; '
             'производительность при изменении загрузки не прогнозируется физически. '
             'Изменение диаметра барабана — сценарий реконструкции, не регулятор на работающей мельнице.')
    window.sim_status.setText(text)
    window.sim_status.setStyleSheet('color:#ff8585' if bad and not action else 'color:#8ddfc5')
    window.sim_apply.setEnabled(bool(action and action['direction']=='add'))
    if action:
        target = action['target']
        data=[{'Операция':'Догрузка' if action['direction']=='add' else 'Выгрузка',
               'Час':action['hour'],'День / час':operation_day(action['hour'],result['hours_per_day']),
               'Камера':target['chamber'],'Ø, мм':target['diameter_mm'],
               'Количество, шт':action['pieces'],'Масса, т':action['tons'],
               'В норме после, ч':action['valid_hours']}]
    else:
        data=[{'Состояние':'Коррекция не требуется' if not bad else 'Подходящей одиночной коррекции нет'}]
    _fill(window,window.sim_table,data)


def _join_horizontal(parent, label, widget):
    h=QHBoxLayout()
    h.addWidget(QLabel(label))
    h.addWidget(widget,1)
    parent.addLayout(h)
    return h


def install(MillWindow):
    if getattr(MillWindow,'_timeline_installed',False): return
    MillWindow._timeline_installed=True
    old_build=MillWindow._build
    old_collect=MillWindow.collect_config
    old_load=MillWindow.load_config
    old_done=MillWindow._sim_done
    old_render=MillWindow._render_active
    old_schedule=MillWindow.schedule

    # SimJob и список сценариев используют глобальное имя при запуске функции.
    # Таким образом не переписываем жизненный цикл QThreadPool и сигналов.
    workflow_ui.simulate_shifts = lambda cfg,optimize=True,observations=90: simulate_operation_timeline(
        cfg,optimize=optimize,observations=observations)
    workflow_ui._sim_plot = _timeline_sim_plot
    workflow_ui._render_summary = _render_timeline_status

    def build(self):
        old_build(self)
        self._cement_events=[]
        self._media_events=[]
        self._parameter_events=[]
        # Окна изменяют горизонтальную компоновку, не выбрасывая её данные.
        self._master_splitter=self.centralWidget().findChild(QSplitter)
        top=self.centralWidget().layout().itemAt(0).layout()
        self._left_toggle=QPushButton('Скрыть левую панель')
        self._right_toggle=QPushButton('Скрыть правую панель')
        self._left_toggle.clicked.connect(lambda: self._toggle_side('left'))
        self._right_toggle.clicked.connect(lambda: self._toggle_side('right'))
        top.insertWidget(0,self._left_toggle)
        top.insertWidget(1,self._right_toggle)
        # Износ слева переезжает на уже существующую вкладку справа.
        for i in range(self.left.tabs.count()):
            if self.left.tabs.tabText(i)=='Прогноз износа':
                wear=self.left.tabs.widget(i)
                with QSignalBlocker(self.left.tabs),QSignalBlocker(self.left.picker):
                    self.left.tabs.removeTab(i)
                    self.left.picker.removeItem(i)
                plot_tab=next(self.right.tabs.widget(j) for j in range(self.right.tabs.count())
                              if self.right.tabs.tabText(j)=='Прогноз износа')
                group=QGroupBox('Настройки прогноза износа')
                gr=QVBoxLayout(group)
                gr.addWidget(wear)
                wear.setMinimumHeight(170)
                group.setMaximumHeight(270)
                plot_tab.layout().insertWidget(0,group)
                break
        # Справка по форме цильпебса (открывается без системного звука).
        media_table=self.tables['media']
        header=media_table.horizontalHeader()
        def show_media_help(column):
            title=media_table.horizontalHeaderItem(column)
            if title and 'L/D' in title.text():
                show_help_dialog(self,'L/D цильпебса',
                    'L/D — отношение длины цилиндрического мелющего тела к его диаметру. '
                    'Например, диаметр 30 мм и L/D=1,2 означает длину 36 мм. '
                    'Для шаров L/D не используется. Коэффициент влияет на массу одной штуки '
                    'и контактную поверхность, но не бывает количеством тел.')
        header.sectionClicked.connect(show_media_help)
        media_page=media_table.parentWidget()
        while media_page is not None and media_page.layout() is None:
            media_page=media_page.parentWidget()
        if media_page and isinstance(media_page.layout(),QVBoxLayout):
            label=QLabel('<a href="help" style="color:#ffdb66">ⓘ L/D цильпебса — длина / диаметр</a>')
            label.setTextFormat(Qt.TextFormat.RichText)
            label.linkActivated.connect(lambda *_:show_help_dialog(self,'L/D цильпебса',
                'L/D = длина цильпебса / диаметр. Например: 30 мм × 1,2 = 36 мм. '
                'Используется для расчёта объёма, массы и контакта одной штуки.'))
            media_page.layout().insertWidget(0,label)
        # Переименование без сброса текущих параметров и сигналов.
        self.right.tabs.setTabText(self.sim_tab_index,'Симуляция работы')
        self.right.picker.setItemText(self.sim_tab_index,'Симуляция работы')
        # Четыре графика требуют достаточной высоты и прокрутки.
        self.sim_plot.setMinimumHeight(860)
        # Отдельная вкладка для редактирования и просмотра истории.
        self._build_timeline_editor()
        self.history_page=QWidget()
        history_layout=QVBoxLayout(self.history_page)
        header_text=QLabel('История меняется только в часы наработки. Масса фракций — фактическая после износа и операций; '
                           'марка цемента задаёт действующие пределы, параметры показаны в % от исходного значения.')
        header_text.setWordWrap(True)
        history_layout.addWidget(header_text)
        PlotPanel=type(self.sim_plot)
        self.history_plot=PlotPanel()
        self.history_plot.setMinimumHeight(680)
        history_layout.addWidget(self.history_plot,1)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.history_page)
        self.history_index=self.right.tabs.count()
        self.right.addTab(scroll,'История изменений')
        self._timeline_outcome=None
        self.right.tabs.currentChanged.connect(lambda _:self._show_timeline_history())

    def toggle_side(self, which):
        side=self.left if which=='left' else self.right
        other=self.right if which=='left' else self.left
        if side.isVisible():
            if not other.isVisible(): other.show()
            side.hide()
        else:
            side.show()
        self._left_toggle.setText('Показать левую панель' if self.left.isHidden() else 'Скрыть левую панель')
        self._right_toggle.setText('Показать правую панель' if self.right.isHidden() else 'Скрыть правую панель')
        if self._master_splitter:
            if self.left.isHidden(): self._master_splitter.setSizes([0,1000])
            elif self.right.isHidden(): self._master_splitter.setSizes([1000,0])
            else:self._master_splitter.setSizes([490,920])

    def make_event_hour(self, lay):
        h=QHBoxLayout()
        h.addWidget(QLabel('День'))
        self.change_day=QSpinBox()
        self.change_day.setRange(1,365)
        self.change_day.setValue(1)
        h.addWidget(self.change_day)
        h.addWidget(QLabel('Час рабочего дня'))
        self.change_hour_in_day=QDoubleSpinBox()
        self.change_hour_in_day.setDecimals(2)
        self.change_hour_in_day.setRange(0,24)
        self.change_hour_in_day.setValue(0)
        h.addWidget(self.change_hour_in_day)
        self.change_hour_total=QLabel('Наработка: 0 ч')
        h.addWidget(self.change_hour_total)
        h.addStretch(1)
        lay.addLayout(h)
        def sync(*_):
            duration=self.sim_hours.value()
            self.change_day.setMaximum(self.sim_days.value())
            self.change_hour_in_day.setMaximum(duration)
            now=(self.change_day.value()-1)*duration+self.change_hour_in_day.value()
            self.change_hour_total.setText(f'Наработка: {now:.2f} ч')
        self.sim_days.valueChanged.connect(sync)
        self.sim_hours.valueChanged.connect(sync)
        self.change_day.valueChanged.connect(sync)
        self.change_hour_in_day.valueChanged.connect(sync)
        sync()

    def current_event_hour(self):
        return round((self.change_day.value()-1)*self.sim_hours.value()+
                     self.change_hour_in_day.value(),6)

    def build_timeline_editor(self):
        tab=QWidget()
        whole=QVBoxLayout(tab)
        banner=QLabel('Добавляйте события по рабочему дню и часу. Все изменения учитываются '
                      'с этого момента до следующего изменения. Для проверки нажмите «Пуск» на вкладке «Симуляция работы».')
        banner.setWordWrap(True)
        whole.addWidget(banner)
        self._make_event_hour(whole)
        sub=QTabWidget()
        whole.addWidget(sub,1)
        self._change_tables={}
        # Цемент — смена технологических пределов, а не химический состав.
        page=QWidget();lay=QVBoxLayout(page)
        self.change_profile=QComboBox();self.change_profile.addItems(list(PROFILES))
        _join_horizontal(lay,'Марка цемента после смены',self.change_profile)
        self.add_cement=QPushButton('Записать смену цемента')
        self.add_cement.clicked.connect(lambda:self._add_timeline('cement'))
        lay.addWidget(self.add_cement)
        self._build_change_tables(lay,'cement')
        sub.addTab(page,'Цемент и сита')
        # Изменение массы: задаются тонны, но движок переводит в целые штуки.
        page=QWidget();lay=QVBoxLayout(page)
        form=QFormLayout()
        self.media_direction=QComboBox();self.media_direction.addItems(['Догрузка','Выгрузка'])
        form.addRow('Действие',self.media_direction)
        self.media_chamber=QComboBox();self.media_chamber.addItems(['1','2'])
        form.addRow('Камера',self.media_chamber)
        self.media_kind=QComboBox();self.media_kind.addItems(['Шары','Цильпебс'])
        form.addRow('Тип',self.media_kind)
        self.media_material=QComboBox();self.media_material.addItems(list(MATERIALS))
        form.addRow('Материал',self.media_material)
        self.media_diameter=QDoubleSpinBox();self.media_diameter.setRange(7,150);self.media_diameter.setValue(70)
        form.addRow('Диаметр, мм',self.media_diameter)
        self.media_aspect=QDoubleSpinBox();self.media_aspect.setRange(.1,10);self.media_aspect.setDecimals(2);self.media_aspect.setValue(1)
        form.addRow('L/D цильпебса',self.media_aspect)
        self.media_tons=QDoubleSpinBox();self.media_tons.setRange(.00001,300);self.media_tons.setDecimals(5);self.media_tons.setValue(7.)
        form.addRow('Запрашиваемое изменение, т',self.media_tons)
        lay.addLayout(form)
        self.media_preview=QLabel()
        lay.addWidget(self.media_preview)
        def update_preview(*_):
            target={'type':self.media_kind.currentText(),'material':self.media_material.currentText(),
                    'diameter_mm':self.media_diameter.value(),'aspect':self.media_aspect.value()}
            count=piece_count(target,self.media_tons.value())
            self.media_preview.setText(f'Для новых тел: {count} шт ≈ {count*mass_kg(target,target["diameter_mm"])/1000:.5f} т. '
                                       'При выгрузке число определяется по фактическому текущему диаметру.')
        for widget in [self.media_kind,self.media_material]:widget.currentIndexChanged.connect(update_preview)
        for widget in [self.media_diameter,self.media_aspect,self.media_tons]:widget.valueChanged.connect(update_preview)
        def switch_aspect(*_):
            cylpebs=self.media_kind.currentText()=='Цильпебс'
            self.media_aspect.setEnabled(cylpebs)
            if not cylpebs:self.media_aspect.setValue(1.0)
        self.media_kind.currentIndexChanged.connect(switch_aspect)
        switch_aspect()
        update_preview()
        explain=QLabel('<a href="help" style="color:#ffdb66">ⓘ Что такое L/D и почему число тел целое?</a>')
        explain.linkActivated.connect(lambda *_:show_help_dialog(self,'Мелющие тела',
            'L/D — отношение длины цильпебса к диаметру. Масса всегда пересчитывается '
            'из целого количества штук. Точное число выгружаемых тел зависит от их текущего размера после износа.'))
        lay.addWidget(explain)
        button=QPushButton('Записать догрузку / выгрузку')
        button.clicked.connect(lambda:self._add_timeline('media'))
        lay.addWidget(button)
        self._build_change_tables(lay,'media')
        sub.addTab(page,'Мелющие тела')
        # Режим работы; паспортные изменения допускаются, но подписаны.
        page=QWidget();lay=QVBoxLayout(page)
        self.parameter_key=QComboBox()
        for key,(label,unit,*_) in PARAMETERS.items():
            self.parameter_key.addItem(f'{label}, {unit}',key)
        self.parameter_value=QDoubleSpinBox();self.parameter_value.setDecimals(3)
        def update_range(*_):
            key=self.parameter_key.currentData()
            _,_,lo,hi=PARAMETERS[key]
            self.parameter_value.setRange(lo,hi)
            try:
                cfg=self.collect_config()
                val=(cfg['mills'][0][key] if key in ('rpm','power_kw','diameter_m') else cfg[key])
            except Exception:
                val=lo
            self.parameter_value.setValue(max(lo,min(hi,float(val))))
        _join_horizontal(lay,'Параметр',self.parameter_key)
        _join_horizontal(lay,'Новое значение',self.parameter_value)
        self.parameter_key.currentIndexChanged.connect(update_range)
        update_range()
        warn=QLabel('Диаметр барабана — паспортная геометрия. Его изменение в календаре означает '
                    'замену/реконструкцию конфигурации, а не регулировку вращающейся мельницы.')
        warn.setWordWrap(True);lay.addWidget(warn)
        button=QPushButton('Записать изменение параметра')
        button.clicked.connect(lambda:self._add_timeline('parameter'))
        lay.addWidget(button)
        self._build_change_tables(lay,'parameter')
        sub.addTab(page,'Параметры')
        whole.addWidget(QLabel('Точные «было / стало» рассчитываются после запуска, поскольку масса тел меняется из-за износа.'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(tab)
        self.timeline_editor_index=self.right.tabs.count()
        self.right.addTab(scroll,'Журнал изменений')
        self._refresh_timeline()

    def build_change_tables(self,layout,key):
        layout.addWidget(QLabel('Запланированные события'))
        table=QTableWidget();self._read_only_table(table)
        table.setMinimumHeight(140)
        layout.addWidget(table)
        remove=QPushButton('Удалить выбранное событие')
        remove.clicked.connect(lambda:self._remove_timeline(key))
        layout.addWidget(remove)
        layout.addWidget(QLabel('Фактические изменения — до / после расчёта'))
        result=QTableWidget();self._read_only_table(result)
        result.setMinimumHeight(180)
        layout.addWidget(result)
        self._change_tables[key]=(table,result)

    def add_event(self,kind):
        h=self._current_event_hour()
        if kind=='cement':
            row={'hour':h,'profile':self.change_profile.currentText()}
            self._cement_events.append(row)
        elif kind=='media':
            if int(self.media_chamber.currentText()) > len(self.collect_config()['mills'][0]['chambers']):
                show_help_dialog(self,'Камера не найдена','Нельзя менять загрузку несуществующей камеры.')
                return
            row={'hour':h,'direction':'add' if self.media_direction.currentIndex()==0 else 'remove',
                 'tons':self.media_tons.value(),
                 'target':{'chamber':int(self.media_chamber.currentText()),
                           'type':self.media_kind.currentText(),
                           'material':self.media_material.currentText(),
                           'diameter_mm':self.media_diameter.value(),
                           'aspect':self.media_aspect.value()}}
            self._media_events.append(row)
        else:
            row={'hour':h,'parameter':self.parameter_key.currentData(),'value':self.parameter_value.value()}
            self._parameter_events.append(row)
        self._refresh_timeline()
        self.schedule()

    def remove_event(self,kind):
        table,_=self._change_tables[kind]
        index=table.currentRow()
        source=getattr(self,'_'+kind+'_events')
        if 0<=index<len(source):
            del source[index]
            self._refresh_timeline()
            self.schedule()

    def refresh_timeline(self):
        hours=self.sim_hours.value()
        for kind in ('cement','media','parameter'):
            source=getattr(self,'_'+kind+'_events')
            table,result=self._change_tables[kind]
            if kind=='cement':
                data=[{'Час наработки':r['hour'],'День / час':operation_day(r['hour'],hours),
                       'Новая марка':r['profile']} for r in source]
            elif kind=='media':
                data=[{'Час наработки':r['hour'],'День / час':operation_day(r['hour'],hours),
                       'Операция':r['direction'],'Камера':r['target']['chamber'],
                       'Фракция':f"{r['target']['type']} Ø{r['target']['diameter_mm']:g}",
                       'Запрошено, т':r['tons']} for r in source]
            else:
                data=[{'Час наработки':r['hour'],'День / час':operation_day(r['hour'],hours),
                       'Переменная':PARAMETERS[r['parameter']][0],
                       'Стало':r['value']} for r in source]
            _fill(self,table,data)
        self._timeline_outcome=None

    def collect(self):
        cfg=old_collect(self)
        cfg['cement_events']=deepcopy(self._cement_events)
        cfg['media_events']=deepcopy(self._media_events)
        cfg['parameter_events']=deepcopy(self._parameter_events)
        return cfg

    def load(self,cfg,calculate=False):
        self._cement_events=deepcopy(cfg.get('cement_events',[]))
        self._media_events=deepcopy(cfg.get('media_events',[]))
        self._parameter_events=deepcopy(cfg.get('parameter_events',[]))
        old_load(self,cfg,calculate=calculate)
        self._refresh_timeline()

    def sim_done(self,n,result):
        old_done(self,n,result)
        if n != self._sim_generation:
            return
        self._timeline_outcome=result
        for kind,label in (('cement','cement_changes'),('media','media_changes'),
                           ('parameter','parameter_changes')):
            _,table=self._change_tables[kind]
            _fill(self,table,result.get(label,[]),'За период изменений нет')
        if self.right.tabs.currentIndex()==self.history_index:
            _timeline_history_plot(self,result)
        elif self.right.tabs.currentIndex() in (2,6):
            self._render_active()

    def show_history(self):
        if getattr(self,'_timeline_outcome',None) is not None and self.right.tabs.currentIndex()==self.history_index:
            _timeline_history_plot(self,self._timeline_outcome)

    def render_active(self):
        result=getattr(self,'_timeline_outcome',None)
        current=self.right.tabs.currentIndex()
        if result is not None and not getattr(self,'_sim_dirty',False):
            if current==2:
                cfg=self.collect_config()
                with QSignalBlocker(self.fraction_combo):
                    selected=self.fraction_combo.currentText()
                    self.fraction_combo.clear()
                    self.fraction_combo.addItem('Все камеры')
                    for number in range(1,len(cfg['mills'][0]['chambers'])+1):
                        self.fraction_combo.addItem(f'Б1К{number}')
                    self.fraction_combo.setCurrentText(selected)
                _dynamic_fraction_plot(self,result)
                return
            if current==6:
                _dynamic_forecast_plot(self,result)
                return
        old_render(self)

    def schedule(self,*args):
        self._timeline_outcome=None
        old_schedule(self,*args)

    MillWindow._build=build
    MillWindow._toggle_side=toggle_side
    MillWindow._make_event_hour=make_event_hour
    MillWindow._current_event_hour=current_event_hour
    MillWindow._build_timeline_editor=build_timeline_editor
    MillWindow._build_change_tables=build_change_tables
    MillWindow._add_timeline=add_event
    MillWindow._remove_timeline=remove_event
    MillWindow._refresh_timeline=refresh_timeline
    MillWindow._show_timeline_history=show_history
    MillWindow.collect_config=collect
    MillWindow.load_config=load
    MillWindow._sim_done=sim_done
    MillWindow._render_active=render_active
    MillWindow.schedule=schedule