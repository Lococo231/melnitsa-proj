"""PySide6 workspace: unified inputs, one timeline, automatic journal, recommendations.

Install AFTER production_ui, workflow_ui, timeline_ui and multicore_ui.
Qt widgets are created / drawn only from the GUI thread; the existing
multicore worker prepares six independent PNG charts with Matplotlib Agg.
"""
from __future__ import annotations

from copy import deepcopy
import math

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QTableWidget, QToolButton, QVBoxLayout,
    QWidget,
)

import workflow_ui
import timeline_ui
from multicore_ui import HourPlotImage
from workspace_logic import (analysis_hours, initial_conditions, journal_tables,
                             overview_series, recommendation, recommendation_rows)

PALETTE = ['#66cbe1', '#e9ad73', '#95d6ad', '#d4a4ef', '#e5d46f', '#9bbbef']
CHARTS = [
    ('sim0', 'R0,08 — контроль крупного остатка'),
    ('sim1', 'R0,045 — тонкость помола'),
    ('sim2', 'Блейн — расчётная поверхность'),
    ('sim3', 'Масса мелющей загрузки'),
    ('sim4', 'Прогноз износа — накопленная потеря'),
    ('sim5', 'Прогноз износа — средний диаметр камер'),
]


def _visible_page(adaptive, index: int, visible: bool):
    # Keeping the original indices preserves older callbacks (3=recommendations,
    # 2=fractions). The compact combo uses the same indices as QTabWidget.
    adaptive.tabs.setTabVisible(index, visible)
    try:
        view = adaptive.picker.view()
        view.setRowHidden(index, not visible)
    except (AttributeError, RuntimeError):
        # Fallback for platform-specific QAbstractItemView implementations.
        adaptive.picker.setItemData(index, None if visible else 0,
                                    Qt.ItemDataRole.UserRole - 1)


def _heading(title: str, note: str = '') -> QLabel:
    label = QLabel(f'<b>{title}</b>' + (f'<div style="font-size:11px; color:#a9bece">{note}</div>' if note else ''))
    label.setWordWrap(True)
    label.setStyleSheet('background:#203e52; color:#f2e39a; padding:11px 12px; '
                        'border-radius:6px; border-left:3px solid #e8c96d;')
    return label


def _group_section(layout: QVBoxLayout, title: str, subtitle: str, content: QWidget):
    group = QFrame()
    group.setObjectName('workspace-input-section')
    group.setStyleSheet('QFrame#workspace-input-section {border:1px solid #335a70; '
                        'border-radius:8px; background:#14283a;}')
    outer = QVBoxLayout(group)
    outer.setContentsMargins(10, 10, 10, 12)
    outer.setSpacing(8)
    toggle = QToolButton()
    toggle.setCheckable(True)
    toggle.setChecked(True)
    toggle.setText('▾  ' + title)
    toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    toggle.setStyleSheet('QToolButton {text-align:left; font-weight:700; color:#f5de83; '
                         'background:#223f53; padding:10px; border-radius:5px;} '
                         'QToolButton:hover {background:#2c526b;}')
    outer.addWidget(toggle)
    if subtitle:
        hint = QLabel(subtitle)
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#a9bbca; padding:2px 4px;')
        outer.addWidget(hint)
        toggle.toggled.connect(hint.setVisible)
    content.setMinimumHeight(0)
    content.setSizePolicy(content.sizePolicy().horizontalPolicy(),
                          content.sizePolicy().verticalPolicy())
    outer.addWidget(content)
    toggle.toggled.connect(content.setVisible)
    toggle.toggled.connect(lambda enabled,button=toggle,title=title:
                           button.setText(('▾  ' if enabled else '▸  ')+title))
    layout.addWidget(group)
    return group


def _take_scroll_body(area: QWidget) -> QWidget:
    if isinstance(area, QScrollArea):
        body = area.takeWidget()
        if body is not None:
            body.setMinimumHeight(0)
            return body
    return area


def _populate(window, table: QTableWidget, rows: list[dict], placeholder='Изменений нет'):
    if not rows:
        rows = [{'Состояние': placeholder}]
    window._populate_result(table, rows, list(rows[0]))
    table.horizontalHeader().setStretchLastSection(True)


def _one_sim_chart(window, result):
    """Show one of six cached process-rendered PNG plots, not six stacked plots."""
    panel = window.sim_plot
    images = result.get('_plot_images') or {}
    key = window._workspace_chart_picker.currentData()
    if not hasattr(panel, '_workspace_image'):
        pane = HourPlotImage(panel, panel)
        pane.setMinimumHeight(220)
        panel._plot_layers.addWidget(pane)
        panel._workspace_image = pane
        panel.hour_spin.valueChanged.connect(pane.set_hour)
    panel.canvas.hide()
    if hasattr(panel, '_multicore_container'):
        panel._multicore_container.hide()
    if hasattr(panel, '_pending_chart_label'):
        panel._pending_chart_label.hide()
    if key not in images:
        panel._plot_placeholder.setText('Подготавливается диаграмма…')
        panel._plot_layers.setCurrentWidget(panel._plot_placeholder)
        window._workspace_chart_hint.hide()
    else:
        window._workspace_chart_hint.hide()
        panel._plot_layers.setCurrentWidget(panel._workspace_image)
        panel._workspace_image.left_fraction = .105
        panel._workspace_image.set_image(images[key], analysis_hours(result))
    panel.set_time_range(analysis_hours(result))
    if hasattr(panel,'_workspace_image'):
        panel._workspace_image.set_hour(panel.hour_spin.value())


def _overview_plot(window, result):
    """The entire Overview is from the SAME baseline as Simulation, not simulate_wear()."""
    series = overview_series(result)
    panel = window.overview_plot
    panel.figure.clear()
    axes = panel.figure.subplots(2, 3)
    for i, dataset in enumerate(series):
        ax = axes[i//3, i%3]
        panel.axis(ax, dataset['name'], ylabel=dataset['unit'])
        ax.plot(dataset['hours'], dataset['values'], lw=1.75,
                color=PALETTE[i % len(PALETTE)])
        ax.set_xlim(0, max(.01, result['hours']))
        ax.ticklabel_format(axis='y', useOffset=False)
    panel.figure.subplots_adjust(left=.085, right=.98, top=.93,
                                 bottom=.12, hspace=.68, wspace=.36)
    panel.set_time_range(analysis_hours(result))
    panel.canvas.draw_idle()
    end = result['baseline'][-1]
    values = (end['throughput'], end['wear_cumulative_t'], end['media_mass_t'],
              end['r008'], end['blaine_proxy'], end['r0045'])
    for label,value in zip(window.metrics, values):
        label.setText(f'{float(value):.3f}'.rstrip('0').rstrip('.'))
    window._workspace_overview_hint.setText(
        f'Данные общей симуляции: {result["days"]} дней × {result["hours_per_day"]:g} ч '
        f'= {result["hours"]:g} ч. Догрузки, выгрузки, смена марки и режима учтены.')


def _journal_view(window, result):
    entries=journal_tables(result)
    _populate(window,window._workspace_initial,initial_conditions(result),
              'Нет исходного состояния')
    for key,table in window._workspace_log_tables.items():
        _populate(window,table,entries[key])
    count=sum(map(len,entries.values()))
    window._workspace_log_status.setText(
        f'Автоматически сформировано записей: {count}. '
        'Источник — конфигурация, плановые операции и модельный расчёт. '
        'Рекомендации до подтверждения в журнал не попадают.')


def _recommendation_view(window, result):
    cfg=window.collect_config()
    item=recommendation(result,cfg)
    window._workspace_recommendation_title.setText(item['headline'])
    window._workspace_recommendation_reason.setText(item['reason'])
    actions=recommendation_rows(result)
    _populate(window,window.reco_table,actions,
              'Нет подтверждённого допустимого плана: см. причину выше')
    window._workspace_recommendation_apply.setEnabled(bool(actions))
    window.sim_apply.setEnabled(bool(actions))
    window.sim_apply.setText('Применить план догрузки/выгрузки')


def install(MillWindow):
    """Attach last, after multicore_ui.install(MillWindow)."""
    if getattr(MillWindow,'_workspace_installed',False):
        return
    MillWindow._workspace_installed=True
    original_build=MillWindow._build
    original_done=MillWindow._sim_done
    original_render=MillWindow._render_active
    original_schedule=MillWindow.schedule
    original_apply=MillWindow._apply_shift_action

    # Both old Qt routes dynamically look up this function when the worker ends.
    workflow_ui._sim_plot=_one_sim_chart
    timeline_ui._timeline_sim_plot=_one_sim_chart

    def build(self):
        # Nested tab widgets emit currentChanged before all workspace fields exist.
        # Suppress those premature callbacks until the composite UI is ready.
        self._workspace_ui_built = False
        original_build(self)
        self._workspace_cursor_updating=False
        self._workspace_ready=False
        self._workspace_last_result=None
        self._workspace_panels=[self.sim_plot,self.overview_plot,
                                self.fraction_plot,self.history_plot]
        # 1) Merge the first four input tabs without losing signal connections.
        categories=(
            ('Грансостав клинкера','Размерные фракции исходного материала'),
            ('Барабан и камеры','Геометрия, вращение и мощность'),
            ('Подача и режим','Фактический выпуск, влажность и температура'),
            ('Сита','Сита для диаграммы и точек контроля'),
        )
        combined=QScrollArea()
        combined.setObjectName('workspace-inputs')
        combined.setWidgetResizable(True)
        combined.setFrameShape(QFrame.Shape.NoFrame)
        body=QWidget()
        form=QVBoxLayout(body)
        form.setContentsMargins(8,8,8,8)
        form.setSpacing(12)
        form.addWidget(_heading('Исходные параметры мельницы',
                    'Заполните разделы сверху вниз; прогноз построится для всей наработки.'))
        sources=[]
        for title,note in categories:
            ix=next((i for i in range(self.left.tabs.count())
                     if self.left.tabs.tabText(i)==title),-1)
            if ix<0:
                raise RuntimeError('Не найдена исходная вкладка: '+title)
            page=self.left.tabs.widget(ix)
            content=_take_scroll_body(page)
            sources.append((ix,page,title,note,content))
        # Forecast's settings were accidentally buried in a fixed-height nested
        # QScrollArea. Take the actual form and show it in the inputs instead.
        forecast_page=self.right.tabs.widget(6)
        wear_groups=[g for g in forecast_page.findChildren(QGroupBox)
                     if g.title()=='Настройки прогноза износа']
        wear_content=None
        if wear_groups:
            areas=wear_groups[0].findChildren(QScrollArea)
            if areas:
                wear_content=_take_scroll_body(areas[0])
            wear_groups[0].hide()
        for _,_,title,note,content in sources:
            _group_section(form,title,note,content)
        if wear_content is not None:
            _group_section(form,'Параметры износа',
                           'Шаг численного расчёта, порог догрузки и горизонт '
                           'работы; горизонт синхронизирован с симуляцией.',wear_content)
        else:
            form.addWidget(QLabel('Поля износа отсутствуют в этой версии исходного файла.'))
        form.addStretch(1)
        combined.setWidget(body)
        self._workspace_old_inputs=[]
        with QSignalBlocker(self.left.tabs), QSignalBlocker(self.left.picker):
            for ix,page,*_ in sorted(sources,key=lambda row:row[0],reverse=True):
                self.left.tabs.removeTab(ix)
                self.left.picker.removeItem(ix)
                self._workspace_old_inputs.append(page)
            self.left.tabs.insertTab(0,combined,'Исходные данные')
            self.left.picker.insertItem(0,'Исходные данные')
            self.left.tabs.setCurrentIndex(0)
            self.left.picker.setCurrentIndex(0)
        # 2) Keep obsolete indices stable for legacy signals, hide those pages.
        for ix in (5,6,self.history_index):
            _visible_page(self.right,ix,False)
        for action in list(self.file_menu.actions()):
            if 'журнала производства' in action.text().lower():
                self.file_menu.removeAction(action)
        # 3) Simulation: a single selectable graph instead of a 4-plot wall.
        sim_page=self.right.tabs.widget(self.sim_tab_index)
        # The simulation tab is a QScrollArea. Its layout belongs to its
        # content QWidget, not to the QScrollArea itself.
        sim_content = (sim_page.widget() if isinstance(sim_page, QScrollArea)
                       else sim_page)
        sim_layout = sim_content.layout() if sim_content is not None else None
        if sim_layout is None or sim_layout.indexOf(self.sim_plot) < 0:
            raise RuntimeError('Не найдена компоновка графиков симуляции работы')
        self.sim_plot.setMinimumHeight(330)
        self.sim_plot.setMaximumHeight(610)
        choice=QHBoxLayout()
        choice.addWidget(QLabel('Показать график:'))
        self._workspace_chart_picker=QComboBox()
        for key,label in CHARTS:
            self._workspace_chart_picker.addItem(label,key)
        choice.addWidget(self._workspace_chart_picker,1)
        self._workspace_chart_hint=QLabel('')
        self._workspace_chart_hint.setWordWrap(True)
        self._workspace_chart_hint.hide()
        self._workspace_chart_picker.currentIndexChanged.connect(
            lambda *_: self._workspace_change_chart())
        slot=sim_layout.indexOf(self.sim_plot)
        sim_layout.insertLayout(slot,choice)
        sim_layout.insertWidget(slot+1,self._workspace_chart_hint)
        # 4) Move PLANNING controls out of journal. Journal becomes read-only.
        journal_scroll=self.right.tabs.widget(self.timeline_editor_index)
        planner_body=_take_scroll_body(journal_scroll)
        self._workspace_planner_scroll=QScrollArea()
        self._workspace_planner_scroll.setWidgetResizable(True)
        self._workspace_planner_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._workspace_planner_scroll.setWidget(planner_body)
        self._workspace_planner_scroll.setMaximumHeight(320)
        self._workspace_planner_scroll.hide()
        toggle=QToolButton()
        toggle.setText('▸  Планирование изменений (цемент, мелющие тела, режим)')
        toggle.setCheckable(True)
        toggle.setStyleSheet('QToolButton {text-align:left; padding:10px; '
                             'background:#294b60; color:#f0e1a3; font-weight:700; '
                             'border-radius:5px;}')
        toggle.toggled.connect(self._workspace_planner_scroll.setVisible)
        toggle.toggled.connect(lambda shown:
            toggle.setText(('▾' if shown else '▸')+
                           '  Планирование изменений (цемент, мелющие тела, режим)'))
        top=sim_layout.indexOf(self.sim_status)
        sim_layout.insertWidget(top,toggle)
        sim_layout.insertWidget(top+1,self._workspace_planner_scroll)
        self._workspace_plan_toggle=toggle
        # The historical editor remains available as a scheduler in Simulation.
        # It is no longer presented as an editable journal.
        for button in planner_body.findChildren(QPushButton):
            if button.text().startswith('Записать '):
                button.setText(button.text().replace('Записать ', 'Запланировать ', 1))
        content=QWidget()
        jl=QVBoxLayout(content)
        jl.setContentsMargins(10,10,10,10)
        jl.setSpacing(10)
        jl.addWidget(_heading('Автоматический журнал работы',
                             'Записи формируются по изменениям параметров и подтверждённым операциям.'))
        self._workspace_log_status=QLabel('Журнал появится после первого расчёта.')
        self._workspace_log_status.setWordWrap(True)
        jl.addWidget(self._workspace_log_status)
        jl.addWidget(QLabel('Начальные условия'))
        self._workspace_initial=QTableWidget()
        self._read_only_table(self._workspace_initial)
        self._workspace_initial.setMinimumHeight(90)
        self._workspace_initial.setMaximumHeight(140)
        jl.addWidget(self._workspace_initial)
        self._workspace_log_tables={}
        for key,title in (('cement','Смена цемента и целевых диапазонов'),
                          ('media','Догрузки и выгрузки мелющих тел'),
                          ('parameter','Изменение режима мельницы')):
            card=QGroupBox(title)
            inner=QVBoxLayout(card)
            table=QTableWidget()
            self._read_only_table(table)
            table.setMinimumHeight(140)
            inner.addWidget(table)
            jl.addWidget(card)
            self._workspace_log_tables[key]=table
        jl.addWidget(_heading('Графики истории изменений'))
        self.history_plot.setMinimumHeight(435)
        self.history_plot.setMaximumHeight(620)
        jl.addWidget(self.history_plot)
        jl.addStretch(1)
        journal_scroll.setWidget(content)
        self.right.tabs.setTabText(self.timeline_editor_index,'Журнал и история')
        self.right.picker.setItemText(self.timeline_editor_index,'Журнал и история')
        self.history_index=self.timeline_editor_index
        # 5) Recommendations are the actual full-period optimized plan.
        recommendation_tab=self.right.tabs.widget(3)
        recommendation_layout=recommendation_tab.layout()
        if hasattr(self,'optimization_note'):
            self.optimization_note.hide()  # old end-of-period 1D reload predictor
        self._workspace_recommendation_title=_heading('Результат оптимизации')
        self._workspace_recommendation_reason=QLabel(
            'Для поиска плана запустите «Симуляцию работы».')
        self._workspace_recommendation_reason.setWordWrap(True)
        self._workspace_recommendation_apply=QPushButton(
            'Применить рекомендованные операции')
        self._workspace_recommendation_apply.setObjectName('accent')
        self._workspace_recommendation_apply.setEnabled(False)
        self._workspace_recommendation_apply.clicked.connect(self._apply_shift_action)
        recommendation_layout.insertWidget(0,self._workspace_recommendation_title)
        recommendation_layout.insertWidget(1,self._workspace_recommendation_reason)
        recommendation_layout.insertWidget(2,self._workspace_recommendation_apply)
        overview_tab=self.right.tabs.widget(0)
        self._workspace_overview_hint=QLabel('Обзор ожидает результат симуляции работы.')
        self._workspace_overview_hint.setWordWrap(True)
        overview_tab.layout().insertWidget(0,self._workspace_overview_hint)
        # Show manually scheduled unloading in the same sidebar as reloading.
        self._workspace_removal_table=QTableWidget()
        self._read_only_table(self._workspace_removal_table)
        self._workspace_removal_table.setMaximumHeight(210)
        self._workspace_removal_table.setMinimumHeight(110)
        for i in range(self.left.tabs.count()):
            if self.left.tabs.tabText(i)=='Догрузки':
                side=self.left.tabs.widget(i)
                layout=side.layout()
                layout.addWidget(_heading('Плановые выгрузки (из симуляции)',
                                        'Догрузки находятся в таблице выше.'))
                layout.addWidget(self._workspace_removal_table)
                break
        _populate(self,self._workspace_removal_table,[])
        # Link the time cursor across views, not just their common horizon.
        for panel in self._workspace_panels:
            panel.hour_spin.valueChanged.connect(
                lambda hour,panel=panel:self._workspace_sync_hour(panel,hour))
        self.right.tabs.currentChanged.connect(
            lambda _index:self._workspace_on_tab_changed())
        self._workspace_ui_built = True
        self.right.tabs.setCurrentIndex(self.sim_tab_index)

    def change_chart(self):
        result=getattr(self,'_timeline_outcome',None)
        if result is not None and not self._sim_dirty:
            _one_sim_chart(self,result)

    def sync_hour(self,from_panel,hour):
        if self._workspace_cursor_updating:
            return
        self._workspace_cursor_updating=True
        try:
            for panel in self._workspace_panels:
                if panel is from_panel:
                    continue
                if hour > panel.hour_spin.maximum():
                    continue  # inactive plot has an older/smaller horizon
                with QSignalBlocker(panel.hour_spin):
                    panel.hour_spin.setValue(hour)
                panel._hour_from_spin(hour)
                if hasattr(panel,'_multicore_images'):
                    for image in panel._multicore_images:
                        image.set_hour(hour)
                if hasattr(panel,'_workspace_image'):
                    panel._workspace_image.set_hour(hour)
        finally:
            self._workspace_cursor_updating=False

    def show_removals(self):
        planned=[]
        for event in getattr(self,'_media_events',[]):
            if event['direction']=='remove':
                planned.append({
                    'Наработка, ч':event['hour'],
                    'Операция':'Выгрузка', 'Камера':event['target']['chamber'],
                    'Фракция':f"{event['target']['type']} Ø{event['target']['diameter_mm']:g}",
                    'Количество, шт':event.get('pieces','—'),
                    'Масса, т':event.get('tons','—')})
        _populate(self,self._workspace_removal_table,planned)

    def sim_done(self,n,result):
        original_done(self,n,result)
        if n != self._sim_generation:
            return
        self._workspace_ready=True
        self._workspace_last_result=result
        _journal_view(self,result)
        _recommendation_view(self,result)
        self._workspace_show_removals()
        if self.right.tabs.currentIndex()==0:
            _overview_plot(self,result)
        if self.right.tabs.currentIndex()==self.sim_tab_index:
            _one_sim_chart(self,result)

    def render_active(self):
        # During original_build(), production_ui currentChanged signals can fire
        # before timeline_editor_index and journal widgets have been created.
        if not getattr(self, '_workspace_ui_built', False):
            return
        index=self.right.tabs.currentIndex()
        result=getattr(self,'_timeline_outcome',None)
        ready=result is not None and not getattr(self,'_sim_dirty',True)
        if index==0:
            if ready:
                _overview_plot(self,result)
            else:
                self._workspace_overview_hint.setText(
                    'Изменены исходные данные. Пересчитывается общая хронология работы…')
                if not getattr(self,'_loading',False) and not self._sim_timer.isActive():
                    self._sim_timer.start()
            return
        if index==3:
            if ready:
                _recommendation_view(self,result)
            elif not getattr(self,'_loading',False) and not self._sim_timer.isActive():
                self._sim_timer.start()
            return
        if index==self.timeline_editor_index:
            if ready:
                _journal_view(self,result)
                # The previous multicore deferred chart callback uses history_index;
                # it now points to the same read-only journal tab.
                timeline_ui._timeline_history_plot(self,result)
            elif not getattr(self,'_loading',False) and not self._sim_timer.isActive():
                self._sim_timer.start()
            return
        if index==2 and not ready:
            if not getattr(self,'_loading',False) and not self._sim_timer.isActive():
                self._sim_timer.start()
            return
        return original_render(self)

    def on_tab_changed(self):
        # setTabVisible on legacy pages leaves their indexes intact; they
        # must never become the current editor's visible destination.
        if self.right.tabs.currentIndex()==5 or self.right.tabs.currentIndex()==6:
            self.right.tabs.setCurrentIndex(self.sim_tab_index)

    def schedule(self,*args):
        if hasattr(self,'_workspace_ready'):
            self._workspace_ready=False
            if hasattr(self,'_workspace_recommendation_apply'):
                self._workspace_recommendation_apply.setEnabled(False)
        return original_schedule(self,*args)

    def apply_actions(self):
        result=getattr(self,'_timeline_outcome',None)
        if result is None or self._sim_dirty:
            return
        actions=result.get('actions') or ([] if not result.get('action') else [result['action']])
        if not actions:
            return
        answer=QMessageBox.question(
            self,'Применить расчётные операции?',
            f'Запланировать {len(actions)} операций с {actions[0]["hour"]:g}-го часа? '
            'Догрузки появятся в таблице «Догрузки», выгрузки — рядом, '
            'а подтверждённые события — в автоматическом журнале после пересчёта. '
            'Это не команда оборудованию.')
        if answer!=QMessageBox.StandardButton.Yes:
            return
        old_media=deepcopy(self._media_events)
        old_reload=self._table_rows('manual_reloads')
        new_reloads=deepcopy(old_reload)
        new_events=deepcopy(old_media)
        for action in actions:
            a=action['target']
            if action['direction']=='add':
                row={'drum':1, 'hour':float(action['hour']),
                     'chamber':int(a['chamber']),'type':a['type'],
                     'material':a['material'],'diameter_mm':float(a['diameter_mm']),
                     'aspect':float(a.get('aspect',1.)), 'tons':float(action['tons'])}
                key=('hour','chamber','type','material','diameter_mm','aspect','tons')
                if not any(all(x.get(k)==row.get(k) for k in key) for x in new_reloads):
                    new_reloads.append(row)
            else:
                row={'hour':float(action['hour']), 'direction':'remove',
                     'pieces':int(action['pieces']), 'tons':float(action['tons']),
                     'target':deepcopy(a)}
                if row not in new_events:
                    new_events.append(row)
        try:
            self._fill_table('manual_reloads',new_reloads)
            self._media_events=new_events
            self.collect_config()  # validate while change is still reversible
        except Exception as exc:
            self._fill_table('manual_reloads',old_reload)
            self._media_events=old_media
            QMessageBox.warning(self,'Ошибка применения',str(exc))
            return
        self._refresh_timeline()
        self._workspace_show_removals()
        self._workspace_recommendation_apply.setEnabled(False)
        self.sim_apply.setEnabled(False)
        self.schedule()
        self.right.tabs.setCurrentIndex(self.sim_tab_index)

    MillWindow._build=build
    MillWindow._sim_done=sim_done
    MillWindow._render_active=render_active
    MillWindow._workspace_change_chart=change_chart
    MillWindow._workspace_sync_hour=sync_hour
    MillWindow._workspace_on_tab_changed=on_tab_changed
    MillWindow._workspace_show_removals=show_removals
    MillWindow.schedule=schedule
    MillWindow._apply_shift_action=apply_actions
