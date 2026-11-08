"""Сменный сценарий: ручной/CSV грансостав -> барабан -> цемент и часы -> прогноз.

Применяется поверх production_ui.install() без изменения расчётного ядра.
Планировщик работает в Qt-потоке задач; элементы GUI обновляются только главной
нитью. Затраты тяжелого перебора не блокируют перемещение бегунков.
"""
from __future__ import annotations

from copy import deepcopy
from html import escape as html_escape
import math

from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, QTimer, Signal, QSignalBlocker
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QTableWidget,
    QVBoxLayout, QWidget, QMessageBox, QScrollArea, QTableWidgetItem)

from model import CLASSES, mass_kg
from production_planning import PROFILES, profile_name, QUALITY_NAMES
from shift_simulation import METRIC_KEYS, simulate_shifts, operation_day
from production_ui import _attach_slider, _attach_help, _fmt

PRESETS = {
    'Мельница №3 (HTML)': [0, 8.37, 21.99, 29.08, 18.32, 14.15, 5.48, 1.70, .50, .45],
    'Крупный клинкер (HTML)': [2,12,26,30,16,9,3.5,1.0,.3,.2],
    'Мелкий клинкер (HTML)': [0,4,14,24,22,18,10,5,1.5,1.5],
    'Свой грансостав': None,
}
DESCRIPTION = ('Выбор названия цемента задаёт технологическую карту из исходного HTML. '
               'R0,08 и R0,045 рассчитываются по модельному выходу; Блейн — '
               'не измерение, а расчётный прокси. ГОСТ 31108-2020 не задаёт '
               'указанные здесь диапазоны для всех видов цемента.')

class SimSignals(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str)

class SimJob(QRunnable):
    def __init__(self, number, cfg, signals):
        super().__init__()
        self.number = number
        self.cfg = cfg
        self.signals = signals

    def run(self):
        try:
            result = simulate_shifts(self.cfg, optimize=True, observations=90)
        except Exception as exc:
            self.signals.failed.emit(self.number, str(exc))
        else:
            self.signals.completed.emit(self.number, result)


def _clickable_label(form, field, help_text):
    label=form.labelForField(field)
    if isinstance(label,QLabel):
        orig=label.text()
        label.setText(f'<a href="help" style="color:#84ddef;text-decoration:none">{html_escape(orig)} ⓘ</a>')
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        label.linkActivated.connect(lambda _=None,t=orig,msg=help_text:
                                    QMessageBox.information(field.window(),t,msg))


def _make_slider(spin: QDoubleSpinBox, lower=0., upper=100.) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 1000)
    def from_spin(value):
        with QSignalBlocker(slider):
            slider.setValue(round(1000 * (value-lower) / max(upper-lower,1e-8)))
    def from_slider(value):
        spin.setValue(round(lower + (upper-lower)*value/1000., 2))
    spin.valueChanged.connect(from_spin)
    slider.valueChanged.connect(from_slider)
    from_spin(spin.value())
    return slider


def _sim_plot(window, result):
    panel = window.sim_plot
    panel.figure.clear()
    axes = panel.figure.subplots(3, 1, sharex=True)
    baseline = result['baseline']
    improved = result.get('optimized')
    threshold = PROFILES[result['profile']]
    specs = [('r008','R0,08','%'), ('r0045','R0,045','%'),
             ('blaine_proxy','Блейн (модельный)','см²/г')]
    for i,(key,label,unit) in enumerate(specs):
        ax = axes[i]
        panel.axis(ax, label, ylabel=unit)
        ax.plot([r['hour'] for r in baseline], [r[key] for r in baseline],
                color='#e9ad73', linewidth=1.8, label='Без вмешательства')
        if improved:
            ax.plot([r['hour'] for r in improved], [r[key] for r in improved],
                    color='#66cbe1', linewidth=1.9, label='После коррекции')
        bounds = threshold.get(key)
        if bounds:
            outliers = [r for r in baseline if ((bounds.get('min') is not None and r[key] < bounds['min'])
                                                    or (bounds.get('max') is not None and r[key] > bounds['max']))]
            if outliers:
                ax.scatter([r['hour'] for r in outliers], [r[key] for r in outliers],
                           color='#ff5d69', s=13, zorder=4, label='Вне допуска')
            mn,mx = bounds.get('min'),bounds.get('max')
            if mn is not None:
                ax.axhline(mn, color='#f26d76', lw=1.2, linestyle='--', label=f'Мин. {mn:g}')
            if mx is not None:
                ax.axhline(mx, color='#f26d76', lw=1.2, linestyle='--', label=f'Макс. {mx:g}')
            if mn is not None and mx is not None:
                ax.axhspan(mn, mx, color='#7fbf9d', alpha=.08)
        else:
            ax.text(.02,.85,'Для этого показателя в карте нет отдельной границы',
                    transform=ax.transAxes, color='#aec0ce',fontsize=8)
        # Вспомогательная разметка смен (не более 12 вертикалей).
        shift_step=max(1,math.ceil(result['days']/12))
        for day in range(shift_step,result['days']+1,shift_step):
            ax.axvline(day*result['hours_per_day'],color='#446076',lw=.55,alpha=.55)
        if result.get('action'):
            ax.axvline(result['action']['hour'], color='#cba3ff', linestyle=':', lw=1.2)
        ax.legend(loc='best', fontsize=7, ncol=2, frameon=False, labelcolor='#ebf5fc')
    axes[-1].set_xlabel(f'Наработка, ч  ·  {result["hours_per_day"]:g} ч работы в день', color='#aec0ce')
    panel.figure.subplots_adjust(hspace=.55, left=.10, right=.97, top=.96, bottom=.12)
    panel.canvas.draw_idle()


def _render_summary(window, result):
    bad = result.get('first_bad')
    msg = (f'Цемент: {result["profile"]}; {result["days"]} дней × '
           f'{result["hours_per_day"]:g} ч = {result["hours"]:g} ч наработки.\n')
    if bad:
        msg += ('Первое отклонение: ' + operation_day(bad['hour'],result['hours_per_day'])
                + ' (' + f'{bad["hour"]:g} ч работы); ' + ', '.join(bad['violations']) + '.\n')
    else:
        msg += 'На расчётных контрольных точках нарушений не обнаружено.\n'
    msg += result['status']
    act = result.get('action')
    if act:
        unit = 'догрузить' if act['direction']=='add' else 'выгрузить'
        r = act['target']
        msg += (f'\n{unit.capitalize()} {act["tons"]:.3f} т: камера {r["chamber"]}, '
                f'{r["type"]}, {r["material"]}, Ø{r["diameter_mm"]:g} мм; '
                f'в момент {operation_day(act["hour"],result["hours_per_day"])}. '
                f'В пределах целей до ≈ {act["valid_to"]:g} ч работы.')
    msg += ('\nВнимание: прогноз дискретный; между контрольными точками возможны нарушения. '
            'Q задано из фактической подачи, а не прогнозируется при изменении загрузки. '
            'Перед выполнением требуется проверка заполнения камер и согласование с технологом.')
    window.sim_status.setText(msg)
    window.sim_status.setStyleSheet('color:#ff8585' if bad and not act else 'color:#8ddfc5')
    window.sim_apply.setEnabled(bool(act and act['direction']=='add'))
    if act:
        r = act['target']
        n = act['tons']*1000/mass_kg(r,r['diameter_mm'])
        rows = [{'Операция': 'Догрузка' if act['direction']=='add' else 'Выгрузка',
                 'Час':act['hour'], 'Камера':r['chamber'], 'Тип':r['type'],
                 'Материал':r['material'], 'Ø, мм':r['diameter_mm'],
                 'Масса, т':act['tons'], 'Расч. шт':math.ceil(n),
                 'В норме после, ч':act['valid_hours']}]
    else:
        rows = [{'Состояние':'Не требуется' if bad is None else 'Допустимой одиночной операции не найдено'}]
    window._populate_result(window.sim_table, rows, list(rows[0]))


def install(MillWindow):
    if getattr(MillWindow, '_workflow_installed', False):
        return
    MillWindow._workflow_installed = True
    previous_build = MillWindow._build
    previous_collect = MillWindow.collect_config
    previous_load = MillWindow.load_config
    previous_draw = MillWindow._draw_results
    previous_render = MillWindow._render_active
    previous_schedule = MillWindow.schedule

    def build(self):
        previous_build(self)
        self._sim_generation = 0
        self._sim_result = None
        self._sim_running = False
        self._sim_dirty = True
        self._sim_pool = QThreadPool(self)
        self._sim_pool.setMaxThreadCount(1)
        self._sim_signals = SimSignals()
        self._sim_signals.completed.connect(lambda n, r: self._sim_done(n,r))
        self._sim_signals.failed.connect(lambda n, e: self._sim_fail(n,e))
        self._sim_timer = QTimer(self)
        self._sim_timer.setSingleShot(True)
        self._sim_timer.setInterval(700)
        self._sim_timer.timeout.connect(self._run_shift_simulation)

        # 1) Оператор видит ввод грансостава, затем ввод геометрии.
        feedpage = QScrollArea()
        feedpage.setWidgetResizable(True)
        body = QWidget()
        feed_layout = QVBoxLayout(body)
        feedpage.setWidget(body)
        self.left.tabs.insertTab(0, feedpage, 'Грансостав клинкера')
        self.left.picker.insertItem(0,'Грансостав клинкера')
        self.left.tabs.setTabText(1,'Барабан и камеры')
        self.left.tabs.setTabText(2,'Подача и режим')
        self.left.picker.setItemText(1,'Барабан и камеры')
        self.left.picker.setItemText(2,'Подача и режим')
        explain = QLabel('Введите заводской гранулометрический состав по десяти размерным классам '
                         '(в сумме 100%) либо импортируйте CSV через «Файл». '
                         'Точные фракции необходимы для расчёта R0,08 / R0,045.')
        explain.setWordWrap(True)
        feed_layout.addWidget(explain)
        presets = QHBoxLayout()
        presets.addWidget(QLabel('Пример исходного клинкера:'))
        self.feed_preset = QComboBox()
        self._applying_preset = False
        self.feed_preset.addItems(list(PRESETS))
        presets.addWidget(self.feed_preset,1)
        feed_layout.addLayout(presets)
        group = QGroupBox('Фракционный состав, масс. %')
        form = QFormLayout(group)
        self.feed_spins = []
        for size in CLASSES:
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setRange(0.,100.)
            spin.setSingleStep(.1)
            box = QWidget()
            v=QVBoxLayout(box)
            v.setContentsMargins(0,0,0,0)
            v.setSpacing(2)
            v.addWidget(spin)
            v.addWidget(_make_slider(spin))
            form.addRow(f'{size} мм', box)
            _clickable_label(form,box,f'Доля материала класса {size} мм в исходном клинкере, масс. %. Сумма десяти классов должна составлять около 100%. Графики остатков на ситах рассчитываются из этих долей.')
            self.feed_spins.append(spin)
            spin.valueChanged.connect(self._feed_changed)
        feed_layout.addWidget(group)
        self.feed_total = QLabel('Сумма: 100%')
        feed_layout.addWidget(self.feed_total)
        row=QHBoxLayout()
        b=QPushButton('Нормировать до 100%')
        b.clicked.connect(self._normalize_feed)
        row.addWidget(b)
        row.addStretch(1)
        feed_layout.addLayout(row)
        feed_layout.addStretch(1)
        self.feed_preset.currentIndexChanged.connect(self._choose_feed_preset)

        # Восстановить импорт CSV из предыдущего меню.
        file_menu = next((action.menu() for action in self.menuBar().actions()
                          if action.text().replace('&','')=='Файл'),None)
        if file_menu and not any('грансостава клинкера' in a.text() for a in file_menu.actions()):
            file_menu.addAction('Импорт грансостава клинкера CSV…',self.open_clinker)

        # 3) Выбор цемента и времени находятся именно на вкладке симуляции.
        overview = self.right.tabs.widget(0)
        old_group = overview.layout().itemAt(0).widget()
        if isinstance(old_group, QGroupBox) and old_group.title()=='Контроль качества и производительности':
            old_group.hide()
        tab = QWidget()
        layout=QVBoxLayout(tab)
        self.sim_tab_index = self.right.tabs.count()
        self.right.addTab(tab,'Симуляция смен')
        options=QGroupBox('Режим и целевой цемент')
        form=QFormLayout(options)
        self.cement_profile=QComboBox()
        self.cement_profile.addItems(list(PROFILES))
        form.addRow('Вид цемента',self.cement_profile)
        _clickable_label(form,self.cement_profile,'Выбор технологических целей R0,08, R0,045 и Блейна из оригинального HTML. Это контрольная карта, а не автоматическое подтверждение ГОСТ.')
        self.sim_days=QSpinBox()
        self.sim_days.setRange(1,365)
        self.sim_days.setValue(5)
        day_box = QWidget()
        day_stack = QVBoxLayout(day_box)
        day_stack.setContentsMargins(0,0,0,0)
        day_stack.addWidget(self.sim_days)
        day_slider = QSlider(Qt.Orientation.Horizontal)
        day_slider.setRange(1,365)
        day_slider.setValue(5)
        self.sim_days.valueChanged.connect(lambda v: day_slider.setValue(v))
        day_slider.valueChanged.connect(self.sim_days.setValue)
        day_stack.addWidget(day_slider)
        form.addRow('Дней работы',day_box)
        _clickable_label(form,day_box,'Количество рабочих дней в прогнозе. Мельница изнашивается только во время работы: общая наработка = дни × часов в день.')
        self.sim_hours=QDoubleSpinBox()
        self.sim_hours.setRange(.5,24.)
        self.sim_hours.setDecimals(1)
        self.sim_hours.setSingleStep(.5)
        self.sim_hours.setValue(8.)
        form.addRow('Часов в день',self.sim_hours)
        _attach_slider(form,self.sim_hours,'simulation_hours_per_day')
        _clickable_label(form,form.itemAt(form.rowCount()-1,QFormLayout.ItemRole.FieldRole).widget(),'Продолжительность работы за одни сутки. Перерывы и остановки не учитываются как часы износа.')
        self.target_product=QDoubleSpinBox()
        self.target_product.setRange(0.,20000.)
        self.target_product.setDecimals(2)
        self.target_product.setValue(72.)
        form.addRow('Минимум выпуска, т/ч',self.target_product)
        _attach_help(form,self.target_product,'target_product_tph')
        _attach_slider(form,self.target_product,'target_product_tph')
        note = QLabel(DESCRIPTION)
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(options)
        for widget in (self.cement_profile,self.sim_days,self.sim_hours,self.target_product):
            if isinstance(widget,QComboBox):
                widget.currentIndexChanged.connect(self.schedule)
            else:
                widget.valueChanged.connect(self.schedule)
        # Часы прогнозного горизонта получают из дней * часов/день.
        # Не оставляем второй независимый регулятор того же периода слева.
        horizon=self.inputs['horizon_h']
        horizon.setReadOnly(True)
        horizon.setToolTip('Автоматически: дни × часы в день на вкладке Симуляция смен')
        for slider in horizon.parentWidget().findChildren(QSlider):
            slider.setEnabled(False)
        def sync_horizon(*_):
            with QSignalBlocker(horizon):
                horizon.setValue(self.sim_days.value()*self.sim_hours.value())
        self.sim_days.valueChanged.connect(sync_horizon)
        self.sim_hours.valueChanged.connect(sync_horizon)
        sync_horizon()
        tools = QHBoxLayout()
        self.sim_run_btn=QPushButton('Пуск · рассчитать и подобрать догрузку/выгрузку')
        self.sim_run_btn.setObjectName('accent')
        self.sim_run_btn.clicked.connect(self._run_shift_simulation)
        tools.addWidget(self.sim_run_btn)
        self.sim_apply=QPushButton('Перенести догрузку в журнал')
        self.sim_apply.setEnabled(False)
        self.sim_apply.clicked.connect(self._apply_shift_action)
        tools.addWidget(self.sim_apply)
        layout.addLayout(tools)
        self.sim_status=QLabel('Для запуска укажите грансостав, геометрию, цемент и длительность смен.')
        self.sim_status.setWordWrap(True)
        layout.addWidget(self.sim_status)
        PlotPanel=type(self.overview_plot)
        self.sim_plot=PlotPanel()
        layout.addWidget(self.sim_plot,1)
        self.sim_table=QTableWidget()
        self.sim_table.setMaximumHeight(120)
        self._read_only_table(self.sim_table)
        layout.addWidget(self.sim_table)
        self.right.tabs.setCurrentIndex(self.sim_tab_index)
        self.left.tabs.setCurrentIndex(0)

    def choose_feed(self,*_):
        preset=PRESETS.get(self.feed_preset.currentText())
        if preset is None:
            return
        self._applying_preset = True
        try:
            for spin, v in zip(self.feed_spins,preset):
                spin.setValue(v)
        finally:
            self._applying_preset = False
        self._feed_changed()

    def feed_changed(self,*_):
        total=sum(spin.value() for spin in self.feed_spins)
        valid=abs(total-100) <= 1.
        self.feed_total.setText(f'Сумма: {total:.2f}%  ' + ('✓' if valid else '✕ Нужно около 100%'))
        self.feed_total.setStyleSheet('color:#8adbb4' if valid else 'color:#ff727c')
        if not self._applying_preset and self.feed_preset.currentText()!='Свой грансостав':
            with QSignalBlocker(self.feed_preset):
                self.feed_preset.setCurrentText('Свой грансостав')
        self.schedule()

    def normalize_feed(self):
        total=sum(w.value() for w in self.feed_spins)
        if total <= 0:
            QMessageBox.warning(self,'Грансостав','Сумма всех фракций должна быть больше нуля')
            return
        remaining=100.
        for i,w in enumerate(self.feed_spins):
            with QSignalBlocker(w):
                value=round(w.value()*100/total,2) if i<9 else round(remaining,2)
                w.setValue(max(0.,value))
                remaining-=w.value()
        self._feed_changed()

    def collect(self):
        cfg=previous_collect(self)
        cfg['feed_fraction']=[spin.value() for spin in self.feed_spins]
        total=sum(cfg['feed_fraction'])
        if not 99. <= total <= 101.:
            raise ValueError('Сумма долей грансостава должна быть около 100%')
        cfg['simulation_days']=self.sim_days.value()
        cfg['simulation_hours_per_day']=self.sim_hours.value()
        cfg['horizon_h']=self.sim_days.value()*self.sim_hours.value()
        return cfg

    def load(self,cfg,calculate=False):
        cfg=deepcopy(cfg)
        days=int(cfg.get('simulation_days',5))
        hours=float(cfg.get('simulation_hours_per_day',8.))
        # Старые конфигурации могли иметь события на 100–1000-м часе.
        # Если период смен в них не был задан, сохраняем возможность импорта.
        if 'simulation_days' not in cfg:
            events=cfg.get('manual_reloads',[])+cfg.get('throughput_schedule',[])
            if events:
                days=max(days, math.ceil(max(float(e['hour']) for e in events)/hours))
        with QSignalBlocker(self.sim_days),QSignalBlocker(self.sim_hours):
            self.sim_days.setValue(days)
            self.sim_hours.setValue(hours)
        for spin,val in zip(self.feed_spins,cfg['feed_fraction']):
            with QSignalBlocker(spin):
                spin.setValue(float(val))
        self._feed_changed()
        for label,preset in PRESETS.items():
            if preset is not None and all(abs(float(a.value())-float(b))<.005 for a,b in zip(self.feed_spins,preset)):
                with QSignalBlocker(self.feed_preset):
                    self.feed_preset.setCurrentText(label)
                break
        # Должно совпадать с горизонтом, иначе calculate/collect разойдутся.
        cfg['horizon_h']=self.sim_days.value()*self.sim_hours.value()
        self._sim_dirty=True
        self._sim_result=None
        self.sim_apply.setEnabled(False)
        previous_load(self,cfg,calculate=calculate)

    def draw_results(self,cfg,run,quality,recommendation):
        previous_draw(self,cfg,run,quality,recommendation)
        self._sim_dirty=True
        if self.right.tabs.currentIndex()==self.sim_tab_index and not self._loading:
            self.sim_status.setText('Пересчёт сценариев после изменения входных параметров…')
            self._sim_timer.start()

    def render_active(self):
        if self.right.tabs.currentIndex()==self.sim_tab_index:
            if self._sim_result is not None and not self._sim_dirty:
                _sim_plot(self,self._sim_result)
                _render_summary(self,self._sim_result)
            elif not self._loading and not self._sim_timer.isActive():
                self._sim_timer.start()
            return
        previous_render(self)

    def schedule(self,*args):
        if hasattr(self,'_sim_generation') and not self._loading:
            self._sim_generation += 1
            self._sim_dirty = True
            if hasattr(self,'sim_apply'):
                self.sim_apply.setEnabled(False)
        return previous_schedule(self,*args)

    def run_simulation(self):
        self._sim_timer.stop()
        try:
            cfg=self.collect_config()
            # Базовая валидация уже выполняется collect_config.
        except Exception as exc:
            self.sim_status.setStyleSheet('color:#ff8585')
            self.sim_status.setText('Исправьте ввод: '+str(exc))
            return
        self._sim_generation += 1
        n=self._sim_generation
        self._sim_dirty=True
        self._sim_running=True
        self.sim_apply.setEnabled(False)
        self._sim_pool.clear()  # сброс устаревших задач в очереди, текущую не прерываем
        self.sim_status.setStyleSheet('color:#aec0ce')
        self.sim_status.setText(f'Симуляция {cfg["simulation_days"]} дней по {cfg["simulation_hours_per_day"]:g} ч: анализ выхода из диапазонов и поиск коррекции…')
        self._sim_pool.start(SimJob(n,deepcopy(cfg),self._sim_signals))

    def sim_done(self,n,result):
        if n != self._sim_generation:
            return  # после изменения параметров старый ответ не отображаем
        self._sim_running=False
        self._sim_dirty=False
        self._sim_result=result
        if self.right.tabs.currentIndex()==self.sim_tab_index:
            _sim_plot(self,result)
            _render_summary(self,result)

    def sim_fail(self,n,error):
        if n!=self._sim_generation:
            return
        self._sim_running=False
        self.sim_status.setText('Ошибка симуляции: '+error)
        self.sim_status.setStyleSheet('color:#ff8585')

    def apply_action(self):
        result=self._sim_result
        if not result or not result.get('action'):
            return
        act=result['action']
        if act['direction']!='add':
            QMessageBox.information(self,'Выгрузка','Базовый журнал допускает только догрузки. '
                'Выгрузку нельзя внести как отрицательную догрузку; используйте план как рекомендацию технологу.')
            return
        response=QMessageBox.question(self,'Внести догрузку в план?',
            f'Добавить событие {act["tons"]:.3f} т на {act["hour"]:g}-м часе? '
            'Это изменит модельный журнал, но не выполнит действие на производстве.')
        if response!=QMessageBox.StandardButton.Yes:
            return
        row={**act['target'], 'hour':act['hour'],'tons':act['tons'],'drum':1}
        rows=self._table_rows('manual_reloads')
        rows.append(row)
        self._fill_table('manual_reloads',rows)
        self.schedule()

    MillWindow._build=build
    MillWindow.schedule=schedule
    MillWindow.collect_config=collect
    MillWindow.load_config=load
    MillWindow._draw_results=draw_results
    MillWindow._render_active=render_active
    MillWindow._choose_feed_preset=choose_feed
    MillWindow._feed_changed=feed_changed
    MillWindow._normalize_feed=normalize_feed
    MillWindow._run_shift_simulation=run_simulation
    MillWindow._sim_done=sim_done
    MillWindow._sim_fail=sim_fail
    MillWindow._apply_shift_action=apply_action
