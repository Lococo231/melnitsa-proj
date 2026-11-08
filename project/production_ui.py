"""Дополнение PySide6: ползунки, справка, нормативы, ленивые графики,
план догрузки и начальная загрузка. Устанавливается на существующий MillWindow.
"""
from __future__ import annotations
import math

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QTableWidget,
    QVBoxLayout, QWidget, QMessageBox)

from model import CLASSES, config_at_time
from production_planning import (DEFAULT_PROFILE, PROFILES, assessments, plan_reload,
                                 profile_name, starting_media)

PALETTE = ['#66cbe1', '#e9ad73', '#95d6ad', '#d4a4ef', '#e5d46f', '#9bbbef', '#e2a2b8', '#8de0d6']

def _fmt(value, digits=3):
    if value is None or isinstance(value,float) and not math.isfinite(value):
        return '—'
    return f'{value:.{digits}f}'.rstrip('0').rstrip('.') if isinstance(value,float) else str(value)

# Пояснения для параметров, а не просто всплывающие единицы измерения.
HELP = {
    'name': 'Уникальное обозначение мельницы на производстве; на расчёт не влияет.',
    'diameter_m': 'Внутренний диаметр барабана D, м. Влияет на критическую частоту вращения и объём.',
    'rpm': 'Фактическая частота вращения n, об/мин. Влияет на скорость износа и размол.',
    'power_kw': 'Измеренная мощность привода P, кВт. Используется в оценке расхода и удельной энергии P/Q.',
    'diaphragm_m': 'Толщина межкамерной перегородки, м. Учитывается в общей длине барабана.',
    'ch1': 'Длина первой камеры L₁, м: зона преимущественно крупного помола.',
    'ch1d': 'Рабочий внутренний диаметр первой камеры D₁, м.',
    'ch2': 'Длина второй камеры L₂, м: зона тонкого помола.',
    'ch2d': 'Рабочий внутренний диаметр второй камеры D₂, м.',
    'chcount': 'Число камер одного барабана, 1 или 2.',
    'throughput_mode': 'Способ получения фактической производительности из измерений: расход либо масса/время.',
    'fresh_feed_tph': 'Фактический выпуск цемента Q, т/ч, без внутреннего возврата сепаратора.',
    'measured_total_t': 'Выпущенная за период масса продукта, т. Вместе со временем определяет Q.',
    'measured_hours': 'Длительность периода измеренного выпуска, ч: Q = масса / время.',
    'recycle_ratio': 'Отношение циркуляционной нагрузки к готовому продукту. Поток внутри мельницы = Q × (1 + r).',
    'material_hold_t': 'Оценка массы материала в мельнице, т, по производственному балансу.',
    'moisture_pct': 'Измеренная влажность материала, %, используется в эмпирическом множителе износа.',
    'temperature_c': 'Измеренная температура материала, °C, используется в эмпирическом множителе износа.',
    'horizon_h': 'Наработка до прогнозируемого состояния мелющих тел, часы.',
    'step_h': 'Интервал численного интегрирования износа Δt, часы. Меньше шаг — точнее и медленнее.',
    'reload_threshold_pct': 'Потеря массы фракции, после которой показывается рекомендация по восстановлению загрузки.',
    'target_product_tph': 'Минимально допустимый выпуск Q, т/ч. Проверяется против выбранной производственной цели.',
    'new_sieve': 'Размер отверстия нового сита, мм, для отображения полного остатка.',
}

SLIDER_RANGES = {
    'diameter_m': (1., 10.), 'rpm': (1., 40.), 'power_kw': (0., 8000.),
    'diaphragm_m': (0., 2.), 'ch1': (0.1, 25.), 'ch1d': (0.1, 10.),
    'ch2': (0.1, 25.), 'ch2d': (0.1, 10.),
    'fresh_feed_tph': (1., 400.), 'measured_total_t': (1., 10000.),
    'measured_hours': (0.1, 200.), 'recycle_ratio': (0., 3.),
    'material_hold_t': (0.001, 200.), 'moisture_pct': (0., 20.),
    'temperature_c': (-20., 250.), 'horizon_h': (0., 10000.),
    'step_h': (0.01, 100.), 'reload_threshold_pct': (0., 30.),
    'target_product_tph': (0., 400.), 'new_sieve': (0.01, 80.),
}


def _attach_help(form, widget, key):
    label = form.labelForField(widget)
    if not isinstance(label, QLabel):
        return
    original = label.text()
    hint = HELP.get(key, f'{original}: параметр технологической модели.')
    label.setText(f'<a style="color:#84ddef; text-decoration:none" href="help">{original} ⓘ</a>')
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
    label.setToolTip('Нажмите для пояснения')
    label.linkActivated.connect(lambda _=None, title=original, message=hint:
                                QMessageBox.information(widget.window(), title, message))


def _attach_slider(form, spin, key):
    if not isinstance(spin, QDoubleSpinBox):
        return
    pos = form.getWidgetPosition(spin)
    if not isinstance(pos, tuple) or pos[0] < 0:
        return
    row = pos[0]
    lo, hi = SLIDER_RANGES.get(key, (spin.minimum(), spin.maximum()))
    lo = max(spin.minimum(), lo)
    hi = min(spin.maximum(), hi)
    if spin.value() > hi:
        hi = min(spin.maximum(), spin.value() * 1.3)
    if spin.value() < lo:
        lo = spin.value()
    if hi <= lo:
        hi = lo + 1.
    box = QWidget()
    stack = QVBoxLayout(box)
    stack.setContentsMargins(0, 0, 0, 0)
    stack.setSpacing(3)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setObjectName('parameter-slider-' + key)
    slider.setRange(0, 1000)
    slider.setToolTip(HELP.get(key, key))
    stack.addWidget(spin)
    stack.addWidget(slider)
    form.removeWidget(spin)
    form.setWidget(row, QFormLayout.ItemRole.FieldRole, box)
    # При ручном вводе выше типичного масштаба расширяем диапазон ползунка.
    state = [float(lo), float(hi)]

    def update_slider(value):
        if value > state[1]:
            state[1] = min(spin.maximum(), max(value * 1.25, state[1] * 1.25))
        if value < state[0]:
            state[0] = value
        with QSignalBlocker(slider):
            ratio = (value - state[0]) / max(1e-9, state[1] - state[0])
            slider.setValue(round(1000 * max(0., min(1., ratio))))

    def update_spin(value):
        new_value = state[0] + (state[1] - state[0]) * value / 1000.0
        spin.setValue(round(new_value, spin.decimals()))

    slider.valueChanged.connect(update_spin)
    spin.valueChanged.connect(update_slider)
    update_slider(spin.value())
    return slider


def _decorate_form(container, dictionary):
    # Форма у QGroupBox -- свой QFormLayout; находить её по полю, а не по имени группы.
    for key, widget in dictionary.items():
        form = widget.parentWidget().layout() if widget.parentWidget() else None
        if not isinstance(form, QFormLayout):
            # Родитель может отличаться от формы: осматриваем виджеты-предки.
            parent = widget.parentWidget()
            while parent and not isinstance(parent.layout(), QFormLayout):
                parent = parent.parentWidget()
            form = parent.layout() if parent else None
        if not isinstance(form, QFormLayout):
            continue
        _attach_help(form, widget, key)
        _attach_slider(form, widget, key)


def _plot_overview(window, cfg, run):
    panel = window.overview_plot
    panel.figure.clear()
    axes = panel.figure.subplots(2, 3)
    x = [r['hours'] for r in run['rows']]
    plots = [
        ('Накопленный износ', 'т', [r['loss_t'] for r in run['rows']]),
        ('Масса загрузки', 'т', [r['total_media_t'] for r in run['rows']]),
        ('Удельный износ', 'г/т', [r['Вся загрузка, г/т'] for r in run['coefficient_history']]),
        ('Средний Ø мелющих тел', 'мм', None),
        ('Производительность Q(t)', 'т/ч', [r['Производительность, т/ч'] for r in run['rows']]),
        ('Накопленный выпуск', 'т', [r['production_t'] for r in run['rows']]),
    ]
    for i, (title, unit, y) in enumerate(plots):
        ax = axes[i//3, i%3]
        panel.axis(ax, title, ylabel=unit)
        if i == 3:
            for chamber in range(1, len(cfg['mills'][0]['chambers'])+1):
                key = f'Б1К{chamber} Dср, мм'
                if key in run['rows'][0]:
                    ax.plot(x, [r[key] for r in run['rows']], label=f'Камера {chamber}',
                            color=PALETTE[(chamber+2)%len(PALETTE)])
            ax.legend(fontsize=7, frameon=False, labelcolor='#ebf5fc')
        elif i == 4:
            ax.step(x, y, where='post', color=PALETTE[i])
        else:
            ax.plot(x, y, color=PALETTE[i])
    panel.figure.subplots_adjust(hspace=.68, wspace=.40, left=.09, right=.98, top=.92, bottom=.12)
    panel.canvas.draw_idle()


def _plot_quality(window, cfg, quality):
    panel = window.quality_plot
    panel.figure.clear()
    ax = panel.figure.add_subplot(111)
    panel.axis(ax, 'Полные остатки по длине мельницы', 'Расстояние от входа, м', 'Полный остаток, %')
    pts = quality['samples']
    x = [p['Расстояние по камерам, м'] for p in pts]
    for i, size in enumerate(cfg['sieves_mm']):
        key = f'R{size:g}, %'
        ax.plot(x, [p[key] for p in pts], lw=1.7, marker='o', markersize=3,
                label=key, color=PALETTE[i%len(PALETTE)])
    chambers = cfg['mills'][0]['chambers']
    d = chambers[0]['length_m']
    if len(chambers) == 2:
        diaphragm = cfg['mills'][0]['diaphragm_m']
        ax.axvline(d, color='#f0b76a', lw=2.1, linestyle='--')
        if diaphragm > 0:
            ax.axvspan(d, d + diaphragm, color='#f0b76a', alpha=.13)
        ymax = ax.get_ylim()[1]
        ax.text(max(d*.45, 0), ymax*.96, 'Камера I', ha='center', va='top', color='#f0b76a')
        ax.text(d + diaphragm + chambers[1]['length_m']*.50, ymax*.96,
                'Камера II', ha='center', va='top', color='#f0b76a')
    else:
        ax.text(d*.50, ax.get_ylim()[1]*.96, 'Камера I', ha='center', va='top', color='#f0b76a')
    ax.legend(fontsize=7, ncol=2, frameon=False, labelcolor='#ebf5fc')
    panel.figure.tight_layout(pad=2.)
    panel.canvas.draw_idle()


def _plot_fractions(window, cfg, run):
    panel = window.fraction_plot
    panel.figure.clear()
    axes = panel.figure.subplots(3, 1)
    selected = window.fraction_combo.currentText()
    fields = [('diameter_history','Диаметры мелющих тел, мм','мм'),
              ('fraction_mass_history','Масса фракций, т','т'),
              ('coefficient_history','Удельный износ фракций, г/т','г/т')]
    for ax, (key, title, unit) in zip(axes, fields):
        panel.axis(ax, title, ylabel=unit)
        hist = run[key]
        if not hist:
            continue
        names = [name for name in hist[0] if name not in ('Наработка, ч','Вся загрузка, г/т')
                 and (selected == 'Все камеры' or name.startswith(selected + ' '))]
        for i, name in enumerate(names):
            ax.plot([r['Наработка, ч'] for r in hist],
                    [r.get(name, math.nan) for r in hist], lw=1.4,
                    color=PALETTE[i%len(PALETTE)], label=name.replace(' · ', ' '))
        if ax == axes[0] and names:
            ax.legend(fontsize=6, frameon=False, labelcolor='#ebf5fc', ncol=2)
    panel.figure.subplots_adjust(hspace=.7, left=.12, right=.97, top=.94, bottom=.10)
    panel.canvas.draw_idle()


def _plot_forecast(window, cfg, run):
    panel = window.forecast_plot
    panel.figure.clear()
    a, b = panel.figure.subplots(2, 1)
    x = [r['hours'] for r in run['rows']]
    panel.axis(a, 'Износ и остаток массы', ylabel='т')
    a.plot(x, [r['loss_t'] for r in run['rows']], color=PALETTE[0], label='Износ, т')
    a.plot(x, [r['total_media_t'] for r in run['rows']], color=PALETTE[1], label='Остаток, т')
    a.legend(fontsize=7, frameon=False, labelcolor='#ebf5fc')
    panel.axis(b, 'Средний диаметр мелющих тел', ylabel='мм')
    for i in range(1, len(cfg['mills'][0]['chambers'])+1):
        key = f'Б1К{i} Dср, мм'
        b.plot(x, [r[key] for r in run['rows']], label=f'Камера {i}',
               color=PALETTE[(i+2)%len(PALETTE)])
    b.legend(fontsize=7, frameon=False, labelcolor='#ebf5fc')
    panel.figure.subplots_adjust(hspace=.55, left=.11, right=.97, top=.94, bottom=.11)
    panel.canvas.draw_idle()


def _plot_start(window, cfg):
    panel = window.start_plot
    panel.figure.clear()
    ax = panel.figure.add_subplot(111)
    rows = [r for r in starting_media(cfg) if r['Начальная масса, т'] > 0]
    xs = list(range(len(rows)))
    ax.bar(xs, [r['Начальная масса, т'] for r in rows],
           color=[PALETTE[(r['Камера']-1)%len(PALETTE)] for r in rows])
    ax.set_xticks(xs)
    ax.set_xticklabels([f"К{r['Камера']} Ø{r['Ø, мм']:g}" for r in rows], rotation=35, ha='right')
    panel.axis(ax, 'Состав загрузки перед началом работы', 'Камера / диаметр', 'Масса, т')
    panel.figure.tight_layout(pad=2.)
    panel.canvas.draw_idle()


def _status_style(label, ok):
    if ok:
        label.setStyleSheet('color:#85dfbf;')
        parent = label.parentWidget()
        if isinstance(parent, QGroupBox):
            parent.setStyleSheet('QGroupBox {border:1px solid #328a78;}')
    else:
        label.setStyleSheet('color:#ff7474;')
        parent = label.parentWidget()
        if isinstance(parent, QGroupBox):
            parent.setStyleSheet('QGroupBox {border:2px solid #e95662; color:#ff7474;}')


def install(MillWindow):
    """Патч класса вызывается один раз ДО main()/создания MillWindow."""
    if getattr(MillWindow, '_production_patch_installed', False):
        return
    MillWindow._production_patch_installed = True
    build_orig = MillWindow._build
    load_orig = MillWindow.load_config
    collect_orig = MillWindow.collect_config

    def build(self):
        build_orig(self)
        PlotPanel = type(self.overview_plot)
        self._active_payload = None
        self._plan_cache = None
        self._timer.setInterval(130)  # обновление после движения ползунка
        # Кнопки импорта/экспорта только в верхнем меню «Файл».
        for button in self.centralWidget().findChildren(QPushButton):
            if button.text() in ('Импорт JSON', 'Экспорт Excel',
                                 'Импорт протокола Бонда JSON',
                                 'Импорт грансостава CSV', 'Импорт журнала CSV'):
                button.hide()
        # Используем живую ссылку владельца, а не временный QAction.menu().
        file_menu = self.file_menu
        if file_menu:
            for action in list(file_menu.actions()):
                if ('Бонда' in action.text() or 'грансостава клинкера' in action.text()):
                    file_menu.removeAction(action)
            file_menu.addSeparator()
            file_menu.addAction('Выход', self.close)

        # Лабораторная характеристика клинкера не запрашивается как вход.
        for group in self.left.findChildren(QGroupBox):
            if group.title() in ('Лабораторные свойства клинкера',
                                 'Гранулометрический состав клинкера, %'):
                group.hide()
        _decorate_form(self.left, self.geometry_fields)
        _decorate_form(self.left, self.inputs)

        overview = self.right.tabs.widget(0)
        ol = overview.layout()
        choose = QGroupBox('Контроль качества и производительности')
        form = QFormLayout(choose)
        self.cement_profile = QComboBox()
        self.cement_profile.addItems(list(PROFILES))
        form.addRow('Технологический профиль цемента', self.cement_profile)
        self.cement_profile.currentIndexChanged.connect(self.schedule)
        self.target_product = QDoubleSpinBox()
        self.target_product.setRange(0, 20000.)
        self.target_product.setDecimals(2)
        self.target_product.setValue(72.)
        self.target_product.valueChanged.connect(self.schedule)
        form.addRow('Минимальная производительность, т/ч', self.target_product)
        _attach_help(form, self.target_product, 'target_product_tph')
        _attach_slider(form, self.target_product, 'target_product_tph')
        self.quality_status = QLabel('Проверка технологических критериев появится после расчёта')
        self.quality_status.setWordWrap(True)
        form.addRow(self.quality_status)
        note = QLabel('Карта задаёт технологические цели предприятия. Модельный «Блейн» не заменяет физическое испытание и не подтверждает ГОСТ.')
        note.setWordWrap(True)
        form.addRow(note)
        ol.insertWidget(0, choose)
        cards = ol.itemAt(1).layout()
        card = QGroupBox('R0,045 на выходе, %')
        metric_lay = QVBoxLayout(card)
        self.metric_r0045 = QLabel('—')
        self.metric_r0045.setFont(QFont('', 15, QFont.Weight.Bold))
        metric_lay.addWidget(self.metric_r0045)
        cards.addWidget(card, 1, 2)
        self.metrics.append(self.metric_r0045)
        self.optimization_note = QLabel('Рекомендация по массе появится при открытии вкладки')
        self.optimization_note.setWordWrap(True)
        self.right.tabs.widget(3).layout().insertWidget(0, self.optimization_note)

        forecast = QWidget()
        layout = QVBoxLayout(forecast)
        self.forecast_summary = QLabel('Прогноз загружается при открытии вкладки')
        self.forecast_summary.setWordWrap(True)
        layout.addWidget(self.forecast_summary)
        self.forecast_plot = PlotPanel()
        layout.addWidget(self.forecast_plot, 2)
        self.forecast_table = QTableWidget()
        self._read_only_table(self.forecast_table)
        self.forecast_table.setMinimumHeight(180)
        layout.addWidget(self.forecast_table, 1)
        self.right.addTab(forecast, 'Прогноз износа')
        start_page = QWidget()
        start_layout = QVBoxLayout(start_page)
        self.start_plot = PlotPanel()
        start_layout.addWidget(self.start_plot, 2)
        self.start_table = QTableWidget()
        self._read_only_table(self.start_table)
        start_layout.addWidget(self.start_table, 1)
        self.right.addTab(start_page, 'Начальная загрузка')
        self.right.tabs.currentChanged.connect(lambda _index: self._render_active())

    def collect(self):
        cfg = collect_orig(self)
        cfg['cement_profile'] = self.cement_profile.currentText()
        cfg['target_product_tph'] = self.target_product.value()
        return cfg

    def load(self, cfg, calculate=False):
        with QSignalBlocker(self.cement_profile):
            self.cement_profile.setCurrentText(profile_name(cfg))
        with QSignalBlocker(self.target_product):
            base = cfg.get('target_product_tph')
            if base is None:
                mode = cfg.get('throughput_mode')
                base = (float(cfg.get('measured_total_t', 0)) / max(float(cfg.get('measured_hours', 1)), 1e-9)
                        if mode == 'Масса / время' else float(cfg.get('fresh_feed_tph', 0)))
            self.target_product.setValue(float(base))
        load_orig(self, cfg, calculate=calculate)

    def draw_results(self, cfg, run, quality, recommendation):
        self._active_payload = (cfg, run, quality, recommendation)
        self._plan_cache = None
        end = run['rows'][-1]
        values = [run['throughput']['product_tph'], run['total_wear_t'],
                  end['total_media_t'], quality['r008'], quality['blaine_proxy'],
                  quality['r0045']]
        for label, value in zip(self.metrics, values):
            label.setText(_fmt(value, 2))
        checks = assessments(cfg, quality, end['Производительность, т/ч'])
        by_key = {r['key']: r for r in checks}
        _status_style(self.metrics[3], by_key.get('r008', {'ok':True})['ok'])
        _status_style(self.metrics[4], by_key.get('blaine_proxy', {'ok':True})['ok'])
        _status_style(self.metric_r0045, by_key.get('r0045', {'ok':True})['ok'])
        for r in checks:
            if r['key'] == 'throughput':
                continue
        passed = all(r['ok'] for r in checks)
        self.quality_status.setText(('✓ Все заданные цели соблюдены' if passed
                                   else '✕ Выход за заданные технологические цели')
                                   + '\n' + ' · '.join(f"{r['label']}: {_fmt(r['value'],2)} "
                                            + ('✓' if r['ok'] else '✕') for r in checks))
        self.quality_status.setStyleSheet('color:#88e4c7' if passed else 'color:#ff7878')
        op_wi = quality.get('operating_wi_kwh_t')
        self.derived_label.setText(
            f"F80 допущения: {quality['f80_um']:.0f} мкм · "
            f"P80 расчёт: {quality['p80_um']:.0f} мкм · "
            f"Wi эксплуатационный: {op_wi:.2f}" if op_wi is not None else
            f"F80 допущения: {quality['f80_um']:.0f} мкм · P80 расчёт: {quality['p80_um']:.0f} мкм · Wi: нет"
        )
        self._render_active()

    def render_active(self):
        if self._active_payload is None:
            return
        cfg, run, quality, recommendation = self._active_payload
        current = self.right.tabs.currentIndex()
        if current == 0:
            _plot_overview(self, cfg, run)
        elif current == 1:
            _plot_quality(self, cfg, quality)
        elif current == 2:
            with QSignalBlocker(self.fraction_combo):
                old = self.fraction_combo.currentText()
                self.fraction_combo.clear()
                self.fraction_combo.addItem('Все камеры')
                for n in range(1, len(cfg['mills'][0]['chambers'])+1):
                    self.fraction_combo.addItem(f'Б1К{n}')
                self.fraction_combo.setCurrentText(old)
            _plot_fractions(self, cfg, run)
        elif current == 3:
            plan = self._get_plan()
            self.optimization_note.setText(plan['status'] +
                f". Всего: {plan['total_t']:.3f} т; профиль: {profile_name(cfg)}. "
                'Производительность Q зафиксирована исходными измерениями, а не оптимизируется моделью.')
            from model import mass_kg
            rows = []
            for r in plan['rows']:
                rows.append({'Камера': r['chamber'], 'Тип': r['type'], 'Материал': r['material'],
                            'Ø, мм': r['diameter_mm'], 'Догрузить, т': r['initial_t'],
                            'Догрузить, шт': math.ceil(r['initial_t']*1000/
                                                       mass_kg(r, r['diameter_mm']))})
            if not rows:
                rows = [{'Результат': 'Подходящей или необходимой догрузки нет'}]
            self._populate_result(self.reco_table, rows, list(rows[0]))
        elif current == 4:
            columns = ['Точка','Расстояние по камерам, м','Камера'] + [f'R{s:g}, %' for s in cfg['sieves_mm']]
            self._populate_result(self.sample_table, quality['samples'], columns)
        elif current == 6:
            _plot_forecast(self, cfg, run)
            end = run['rows'][-1]
            self.forecast_summary.setText(
                f"Исходная масса: {run['initial_media_t']:.3f} т · Потеря за период: "
                f"{run['total_wear_t']:.3f} т · Масса после {cfg['horizon_h']:g} ч: "
                f"{end['total_media_t']:.3f} т. Калибровка по заводу: "
                + ('есть предварительная' if cfg.get('wear_calibrated') else 'не выполнена (демомодель)'))
            rows = run['cohort_results']
            self._populate_result(self.forecast_table, rows, list(rows[0]) if rows else [])
        elif current == 7:
            _plot_start(self, cfg)
            rows = starting_media(cfg)
            self._populate_result(self.start_table, rows, list(rows[0]) if rows else [])
        # История (индекс 5) намеренно не перестраивается при изменении ползунков.

    def fractions(self, *_):
        if self._active_payload is not None and self.right.tabs.currentIndex() == 2:
            cfg, run, *_ = self._active_payload
            _plot_fractions(self, cfg, run)

    def get_plan(self):
        if self._plan_cache is None:
            cfg, run, *_ = self._active_payload
            self._plan_cache = plan_reload(cfg, run)
        return self._plan_cache

    MillWindow._build = build
    MillWindow.collect_config = collect
    MillWindow.load_config = load
    MillWindow._draw_results = draw_results
    MillWindow._draw_fractions = fractions
    MillWindow._render_active = render_active
    MillWindow._get_plan = get_plan
