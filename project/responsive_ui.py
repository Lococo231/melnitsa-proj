"""Adaptive Qt sizing + sharp, aspect-preserving media-wear charts.

Installed last after staged_results_ui and existing workspace/multicore plugins.
No Qt widget is created in a multiprocessing worker. The Agg renderer receives
requested image dimensions and returns PNG to the GUI via existing signals.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QObject, QEvent, QRectF, QTimer, QRunnable
from PySide6.QtGui import QImage, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QScrollArea, QSizePolicy, QSlider, QSplitter, QTableWidget, QWidget,
)

import multicore_ui
from multicore_render import render_timeline_images

_METRICS = (
    ('diameter', 'Средний диаметр фракций, мм'),
    ('mass', 'Масса фракций, т'),
    ('wear', 'Удельный износ фракций, г/т'),
)


def _fit_rect(widget: QWidget, image: QImage) -> QRectF:
    """Pixel-accurate aspect-fit rectangle, also for portrait-sized panels."""
    rect = widget.contentsRect()
    if image.isNull() or rect.width() <= 0 or rect.height() <= 0:
        return QRectF()
    scale = min(rect.width() / image.width(), rect.height() / image.height())
    width = image.width() * scale
    height = image.height() * scale
    return QRectF(rect.left() + (rect.width()-width)/2.,
                  rect.top() + (rect.height()-height)/2., width, height)


def _patch_chart_label():
    """QLabel.setScaledContents(True) distorts PNG when the splitter moves."""
    cls = multicore_ui.HourPlotImage
    if getattr(cls, '_adaptive_paint_installed', False):
        return
    cls._adaptive_paint_installed = True
    original_init = cls.__init__

    def init(self, panel, parent=None):
        original_init(self, panel, parent)
        self._adaptive_image = QImage()
        self.setScaledContents(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

    def set_image(self, data, end):
        img = QImage.fromData(data, 'PNG')
        if img.isNull():
            raise ValueError('Невозможно декодировать изображение графика')
        self._adaptive_image = img
        self.end = max(.001, float(end))
        self.updateGeometry()
        self.update()

    def paint_event(self, event):
        img = getattr(self, '_adaptive_image', None)
        if img is None or img.isNull():
            # Avoid the original pixmap stretching even if old cached images exist.
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor('#162a3d'))
            painter.end()
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#162a3d'))
        target = _fit_rect(self, img)
        if target.isEmpty():
            painter.end()
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, img)
        # Matplotlib axes: left=.105, right=.785 for a side legend; all plot
        # coordinates must refer to the actual painted image, not the QLabel.
        left = float(getattr(self, 'left_fraction', .105))
        right = .785
        frac = max(0., min(1., float(getattr(self, 'hour', 0.)) /
                                 max(.001, float(getattr(self, 'end', 1.)))))
        x = target.left() + (left + (right-left)*frac)*target.width()
        painter.setPen(QPen(QColor(238, 246, 255, 195), 1,
                            Qt.PenStyle.DashLine))
        painter.drawLine(round(x), round(target.top()+.16*target.height()),
                         round(x), round(target.top()+.78*target.height()))
        painter.end()

    def mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            img = getattr(self, '_adaptive_image', None)
            if img is not None and not img.isNull():
                target = _fit_rect(self, img)
                if target.width() > 1 and target.left() <= event.position().x() <= target.right():
                    left = float(getattr(self, 'left_fraction', .105))
                    lo = target.left() + left*target.width()
                    hi = target.left() + .785*target.width()
                    fraction = max(0., min(1., (event.position().x()-lo)/max(1.,hi-lo)))
                    self.panel.hour_spin.setValue(fraction*self.end)
                    return
        # The old implementation assumes a stretched image; do not run that.
        QWidget.mousePressEvent(self, event)

    cls.__init__ = init
    cls.set_image = set_image
    cls.paintEvent = paint_event
    cls.mousePressEvent = mouse_press


class _FractionJob(QRunnable):
    """Render only the selected fraction metric at the *actual* panel aspect."""
    def __init__(self, generation, image_key, result, size, signals):
        super().__init__()
        self.generation = generation
        self.image_key = image_key
        self.result = result
        self.size = size
        self.signals = signals

    def run(self):
        try:
            images, workers, warning = render_timeline_images(
                self.result, groups=(self.image_key,), target_size=self.size)
            self.signals.charts_ready.emit(
                self.generation, 'fraction', (images, workers, warning))
        except Exception as exc:
            self.signals.charts_failed.emit(self.generation, 'fraction', str(exc))


def _desired_size(panel):
    # Target is Qt logical pixels; the Agg process renders at 2x resolution.
    controls = panel.time_controls.height() if panel.time_controls.isVisible() else 36
    return (max(260, panel.width()-18), max(175, panel.height()-controls-15))


def _size_differs(previous, desired):
    if previous is None:
        return True
    # Re-render only after a meaningful change; dragging the splitter should
    # not saturate the multiprocessing pool with dozens of redundant images.
    return any(abs(a-b) >= max(65, a*.20) for a,b in zip(previous, desired))


def _show_one_fraction(panel, result, group, parts):
    if not group.startswith('fraction_'):
        return _show_one_fraction._original(panel, result, group, parts)
    window = panel.window()
    stages = getattr(window, '_media_stages', None)
    if stages is not None and stages.currentIndex() != 1:
        # A hidden wear chart must not start a new expensive render.
        return True
    picker = getattr(window, '_fraction_metric', None)
    selected = picker.currentIndex() if picker is not None else 0
    key = f'{group}{selected}'
    images = result.get('_plot_images') or {}
    wanted = _desired_size(panel)
    failures = getattr(window, '_fraction_failures', set())
    if ((key not in images or _size_differs(getattr(window, '_fraction_sizes', {}).get(key),wanted))
            and key not in failures):
        request = getattr(window, '_request_fraction_image', None)
        if callable(request):
            request(key, result, wanted)
    if key not in images:
        # Return True so the old code does not render nine low-res graphs.
        if not hasattr(panel, '_fraction_wait_label'):
            label = QLabel('Подготавливается диаграмма фракций…', panel)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            panel.layout().insertWidget(0, label, 1)
            panel._fraction_wait_label = label
        if key in failures:
            panel._fraction_wait_label.setText('Не удалось подготовить график фракций. Проверьте сообщение в строке состояния.')
        else:
            panel._fraction_wait_label.setText('Подготавливается диаграмма фракций…')
        panel._fraction_wait_label.show()
        panel.canvas.hide()
        if hasattr(panel, '_multicore_container'):
            panel._multicore_container.hide()
        if hasattr(panel, '_fraction_single_image'):
            panel._fraction_single_image.hide()
        return True
    if not hasattr(panel, '_fraction_single_image'):
        image = multicore_ui.HourPlotImage(panel, panel)
        panel.layout().insertWidget(0, image, 1)
        panel._fraction_single_image = image
        panel.hour_spin.valueChanged.connect(image.set_hour)
    if hasattr(panel, '_fraction_wait_label'):
        panel._fraction_wait_label.hide()
    if hasattr(panel, '_pending_chart_label'):
        panel._pending_chart_label.hide()
    if hasattr(panel, '_multicore_container'):
        panel._multicore_container.hide()
    panel.canvas.hide()
    image = panel._fraction_single_image
    image.show()
    image.left_fraction = .105
    image.set_image(images[key], result['hours'])
    panel.set_time_range(result['hours'])
    image.set_hour(panel.hour_spin.value())
    return True


class _ResizeListener(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, target, event):
        if event.type() == QEvent.Type.Resize:
            window = self.window
            if getattr(window, '_adaptive_ready', False):
                window._adaptive_layout_timer.start()
                if target is window.fraction_plot:
                    if hasattr(window, '_fraction_resize_timer'):
                        window._fraction_resize_timer.start()
        return False


def _prepare_responsive_widgets(window):
    left, right = window.left, window.right
    splitter = window._master_splitter
    if isinstance(splitter, QSplitter):
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setOpaqueResize(True)
    # Remove the 345-px hard minimum set by the previous staged-tab update.
    for page in (left,right,left.tabs,right.tabs,left.picker,right.picker):
        page.setMinimumWidth(0)
        page.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Expanding)
    for adaptive in (left,right):
        for i in range(adaptive.tabs.count()):
            page = adaptive.tabs.widget(i)
            if page is not None:
                page.setMinimumWidth(0)
                page.setSizePolicy(QSizePolicy.Policy.Ignored,
                                   QSizePolicy.Policy.Expanding)
                if isinstance(page,QScrollArea):
                    page.setWidgetResizable(True)
                    page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    if page.widget() is not None:
                        page.widget().setMinimumWidth(0)
                        page.widget().setSizePolicy(
                            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    for panel in (window.sim_plot,window.overview_plot,
                  window.fraction_plot,window.history_plot):
        panel.setMinimumWidth(0)
        panel.setSizePolicy(QSizePolicy.Policy.Ignored,
                            QSizePolicy.Policy.Expanding)
    # The sections contain the ORIGINAL forms; keep them and their callbacks.
    root = left.tabs.widget(0)
    if isinstance(root,QScrollArea):
        body = root.widget()
        if body is not None:
            body.setMinimumWidth(0)
            for child in body.findChildren(QWidget):
                child.setMinimumWidth(0)
                if isinstance(child,QComboBox):
                    child.setMinimumContentsLength(6)
                    child.setSizeAdjustPolicy(
                        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                    child.setSizePolicy(QSizePolicy.Policy.Ignored,
                                        QSizePolicy.Policy.Fixed)
                if isinstance(child,QScrollArea):
                    child.setWidgetResizable(True)
                if isinstance(child,QLabel) and not child.textFormat()==Qt.TextFormat.RichText:
                    if len(child.text()) > 35:
                        child.setWordWrap(True)


def _reflow_forms(window):
    if not getattr(window, '_adaptive_ready', False):
        return
    root = window.left.tabs.widget(0)
    if not isinstance(root,QScrollArea) or root.widget() is None:
        return
    viewport_width = max(1,root.viewport().width())
    # Use a stacked label + field in narrow panels so an item's natural width
    # cannot pin the left panel at its original 500px width.
    policy = (QFormLayout.RowWrapPolicy.WrapAllRows if viewport_width < 570 else
              QFormLayout.RowWrapPolicy.WrapLongRows)
    for field in root.widget().findChildren(QWidget):
        form = field.layout()
        if isinstance(form,QFormLayout):
            if form.rowWrapPolicy() != policy:
                form.setRowWrapPolicy(policy)
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
            form.invalidate()
    body = root.widget()
    body.updateGeometry()
    if body.layout():
        body.layout().invalidate()
        body.layout().activate()
    root.updateGeometry()
    # Tables may overflow *inside their own scroll viewport*, not push the
    # entire right-hand tab to the old wide size.
    for table in (window.sample_table, window.start_table,
                  window.fraction_plot):
        table.setMinimumWidth(0)


def install(MillWindow):
    if getattr(MillWindow, '_adaptive_responsive_installed', False):
        return
    MillWindow._adaptive_responsive_installed = True
    old_build = MillWindow._build
    old_schedule = MillWindow.schedule
    _patch_chart_label()
    if not hasattr(_show_one_fraction, '_original'):
        _show_one_fraction._original = multicore_ui._show_png_set
        multicore_ui._show_png_set = _show_one_fraction

    def build(window):
        window._adaptive_ready = False
        old_build(window)
        window._fraction_sizes = {}
        window._fraction_failures = set()
        window._fraction_working = False
        window._fraction_requested = None
        window._adaptive_layout_timer = QTimer(window)
        window._adaptive_layout_timer.setSingleShot(True)
        window._adaptive_layout_timer.setInterval(50)
        window._adaptive_layout_timer.timeout.connect(lambda:_reflow_forms(window))
        window._fraction_resize_timer = QTimer(window)
        window._fraction_resize_timer.setSingleShot(True)
        window._fraction_resize_timer.setInterval(450)
        window._fraction_resize_timer.timeout.connect(lambda:_request_on_resize(window))
        window._adaptive_resize_listener = _ResizeListener(window)
        for widget in (window.left, window.right, window.fraction_plot,
                       window._master_splitter):
            if widget is not None:
                widget.installEventFilter(window._adaptive_resize_listener)
        _prepare_responsive_widgets(window)
        # Show a single fraction chart at sufficient height, instead of 3
        # squeezed images that become unreadable on narrow splitters.
        row = window.fraction_plot.parentWidget().layout().itemAt(0).layout()
        if not isinstance(row,QHBoxLayout):
            raise RuntimeError('Не найден блок выбора камеры графиков износа')
        window._fraction_metric = QComboBox(window.fraction_plot.parentWidget())
        window._fraction_metric.addItems([label for _,label in _METRICS])
        window._fraction_metric.setMinimumContentsLength(8)
        window._fraction_metric.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        window._fraction_metric.setSizePolicy(QSizePolicy.Policy.Ignored,
                                              QSizePolicy.Policy.Fixed)
        row.insertWidget(max(0,row.count()-1),QLabel('Показатель:'))
        row.insertWidget(max(0,row.count()-1),window._fraction_metric,1)
        window._fraction_metric.currentIndexChanged.connect(
            lambda _:window._draw_fractions())
        window._sim_signals.charts_ready.connect(
            lambda n,g,_: _finished_fraction(window,n,g,False))
        window._sim_signals.charts_failed.connect(
            lambda n,g,error: _finished_fraction(window,n,g,True,error))
        window._adaptive_ready = True
        _reflow_forms(window)

    def request_fraction(window,key,result,size):
        if getattr(window,'_fraction_working',False):
            return
        if not hasattr(window,'_chart_pool'):
            return
        window._fraction_working=True
        window._fraction_requested=(key,size)
        window._fraction_sizes[key]=size
        window._charts_loading['fraction']=window._sim_generation
        window._chart_pool.start(_FractionJob(
            window._sim_generation, key, result, size, window._sim_signals))

    def _finished_fraction(window,n,g,failed,error=''):
        if g != 'fraction' or n != getattr(window, '_sim_generation', -1):
            return
        window._fraction_working=False
        if failed:
            key = window._fraction_requested[0] if window._fraction_requested else None
            if key:
                window._fraction_failures.add(key)
            window.statusBar().showMessage('Не удалось построить график фракций: '+error, 20000)
            return
        QTimer.singleShot(0, lambda: _request_on_resize(window))

    def _request_on_resize(window):
        if not getattr(window,'_adaptive_ready',False):
            return
        if window.right.tabs.currentIndex()!=2:
            return
        stages=getattr(window,'_media_stages',None)
        if stages is not None and stages.currentIndex()!=1:
            return
        result=getattr(window,'_timeline_outcome',None)
        if result is None or getattr(window,'_sim_dirty',True):
            return
        window._draw_fractions()

    def schedule(window,*args):
        # A new timeline invalidates pending resize render requests.
        if getattr(window,'_adaptive_ready',False):
            window._fraction_working=False
            window._fraction_sizes.clear()
            window._fraction_failures.clear()
        return old_schedule(window,*args)

    MillWindow._build = build
    MillWindow.schedule = schedule
    MillWindow._request_fraction_image = request_fraction
