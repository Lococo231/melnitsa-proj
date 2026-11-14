"""Live painter for the former web mill animations.

Cross-section: rotating shell, lifters, colliding grinding media, falling charge
and material fragments. Axial: two chambers, diaphragm, coarsening-to-fines
flow, rolling charge, discharge. Pure illustrative 2D dynamics; NOT plant DEM.
"""
from __future__ import annotations

import math
import weakref
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QRadialGradient, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QSizePolicy

from mill_dynamics import DrumCharge, AxialTransport

_SOURCE = None

def set_source(window):
    global _SOURCE
    _SOURCE=weakref.ref(window)


def current_parameters():
    if _SOURCE is not None:
        window=_SOURCE()
        if window is not None:
            try:
                return window.collect_config()
            except Exception:
                pass
    return {'mills':[{'diameter_m':4.,'rpm':16.,'length_m':13.4,
                      'chambers':[{'length_m':6.3},{'length_m':6.6}]}],
            'media':[], 'fresh_feed_tph':72.}


def _color(grade):
    colors=['#be8a58','#cda068','#d8b879','#c6ba8e','#a6c3ad',
            '#8ec8c7','#68bcd3','#6aaadd','#7b98d3','#9d9ad3']
    return QColor(colors[min(9,max(0,int(grade)))])


class MillCutWidget(QWidget):
    def __init__(self, mode, parent=None):
        super().__init__(parent)
        self.mode=mode
        self.params=current_parameters()
        self._chamber=1
        self._fps=30
        self._time_speed=1.
        self._build_model()
        self.timer=QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.setMinimumHeight(290)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.ticks=0

    def _build_model(self):
        mill=self.params['mills'][0]
        self.rpm=mill.get('rpm',16.)
        self.diameter=mill.get('diameter_m',4.)
        self.chambers=mill.get('chambers',[])
        lengths=[float(c.get('length_m',6.0)) for c in self.chambers]
        split=(lengths[0]/sum(lengths)) if len(lengths)>1 and sum(lengths)>0 else 1.
        media=[]
        for item in self.params.get('media',[]):
            if int(item.get('chamber',1))==self._chamber:
                media.append(float(item.get('diameter_mm',50.)))
        self.drum=DrumCharge(rpm=self.rpm,diameter_m=self.diameter,
                             chamber=self._chamber,sizes_mm=media)
        self.axial=AxialTransport(len(self.chambers) or 2,split=split)

    def set_chamber(self,number):
        self._chamber=int(number)
        self._build_model()
        self.update()

    def _tick(self):
        if not self.isVisible():
            return
        self.drum.step(.033*self._time_speed)
        self.axial.step(.033*self._time_speed,
                        float(self.params.get('fresh_feed_tph',72.)))
        self.ticks+=1
        self.update()

    def _background(self,p,r):
        p.fillRect(self.rect(),QColor('#0c1e2c'))
        p.setPen(QPen(QColor('#355e75'),1))
        p.setBrush(QBrush(QColor('#142f42')))
        p.drawRoundedRect(r,12,12)

    def _circle(self,p,x,y,r,color,shade=True):
        if shade:
            grad=QRadialGradient(x-r*.34,y-r*.42,r*1.30)
            grad.setColorAt(0,QColor('#eef5f7'))
            grad.setColorAt(.26,QColor(color))
            grad.setColorAt(1,QColor('#344b5c'))
            p.setBrush(QBrush(grad))
        else:p.setBrush(QColor(color))
        p.setPen(QPen(QColor('#122c39'),.65))
        p.drawEllipse(QRectF(x-r,y-r,2*r,2*r))

    def _cross(self,p,r):
        size=min(r.width()*.74,r.height()*.90)
        rad=size*.47
        cx=r.center().x()-.06*r.width()
        cy=r.center().y()+12
        # Note: y grows downward; steel bodies roll down the toe.
        p.setBrush(QBrush(QColor('#17364a')))
        p.setPen(QPen(QColor('#e6ae54'),max(3,rad*.026)))
        p.drawEllipse(QRectF(cx-rad,cy-rad,2*rad,2*rad))
        # Liners rotate with the shell.
        for k in range(18):
            theta=self.drum.rotation+k*2*math.pi/18
            x1=cx+rad*.95*math.cos(theta);y1=cy+rad*.95*math.sin(theta)
            x2=cx+rad*.86*math.cos(theta+.045);y2=cy+rad*.86*math.sin(theta+.045)
            p.setPen(QPen(QColor('#d7a04d'),max(1.5,rad*.016)))
            p.drawLine(int(x1),int(y1),int(x2),int(y2))
        for grain in self.drum.grains:
            x=cx+grain.x*rad;y=cy+grain.y*rad
            size=max(1.3,grain.r*rad)
            self._circle(p,x,y,size,_color(grain.grade),False)
        for ball in self.drum.balls:
            self._circle(p,cx+ball.x*rad,cy+ball.y*rad,max(4.,ball.r*rad),QColor('#8fa5b0'))
        p.setPen(QColor('#cfe2ec'))
        p.setFont(QFont('Segoe UI',9))
        px=cx+rad+18
        p.drawText(QRectF(px,cy-rad+4,max(120,r.right()-px-8),70),
                   Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.TextWordWrap,
                   f'Камера {self._chamber}\n{self.rpm:.1f} об/мин\n{self.rpm/max(.01,self.drum.critical_rpm)*100:.0f}% nкр')
        p.setPen(QColor('#b5c9d6'))
        p.drawText(QRectF(px,cy+10,max(120,r.right()-px-8),100),
                   Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.TextWordWrap,
                   f'Ударов (схема): {self.drum.impact_count}\n'
                   f'Дроблений (схема): {self.drum.breakage_count}\n'
                   'Подъём → падение → удар → истирание')
        p.setPen(QColor('#6d94aa'))
        p.drawText(QRectF(r.left()+10,r.bottom()-33,r.width()-20,25),
                   Qt.AlignmentFlag.AlignHCenter,
                   '2D динамическая демонстрация контактов, не расчёт DEM')

    def _length(self,p,r):
        x=r.left()+45; y=r.top()+55
        width=r.width()-90; height=max(120,r.height()-108)
        ymid=y+.5*height
        chamber_split=self.axial.split if self.axial.chambers==2 else 1.
        sep=x+width*chamber_split
        # outer cylinder with two chambers
        p.setPen(QPen(QColor('#d5a35c'),3))
        p.setBrush(QColor('#203b4d'))
        p.drawRoundedRect(QRectF(x,y,width,height),10,10)
        if chamber_split<1:
            p.setPen(QPen(QColor('#dfb26f'),4))
            p.drawLine(int(sep),int(y+2),int(sep),int(y+height-2))
            for k in range(5):
                yy=y+12+k*(height-24)/4
                p.setPen(QPen(QColor('#7bb4bd'),2))
                p.drawLine(int(sep-4),int(yy),int(sep+4),int(yy))
        # Staggered media outlines and rolling texture. Axial projection shows
        # many balls in charge, not claiming collision simulation in 3D.
        p.setBrush(QColor('#30475a'))
        p.setPen(QPen(QColor('#466679'),1))
        p.drawRect(QRectF(x+2,ymid,width-4,height*.50-2))
        for i in range(50):
            xx=x+(i+.5)/50*width
            local_ch=1 if xx<sep else 2
            radius=(.022 if local_ch==1 else .014)*height
            yy=ymid+height*.18+math.sin(self.axial.time*1.8+i*.52)*radius*.65
            self._circle(p,xx,yy,radius,QColor('#8ba5b4' if local_ch==1 else '#81a7a2'))
        # clinker stream flows axially; particle grade advances through chambers.
        for grain in self.axial.grains:
            xx=x+grain.pos*width
            yy=y+grain.depth*height*.65+math.sin(grain.phase)*8
            rad=max(2.5,min(9.,(11.-grain.grade)*.58))
            self._circle(p,xx,yy,rad,_color(grain.grade),False)
        p.setPen(QPen(QColor('#68d8cf'),2.2))
        p.drawLine(int(x-35),int(ymid),int(x-3),int(ymid))
        p.drawLine(int(x+width+4),int(ymid),int(x+width+35),int(ymid))
        p.drawText(QRectF(x-50,y-33,110,26),Qt.AlignmentFlag.AlignHCenter,'Клинкер →')
        p.drawText(QRectF(x+width-105,y-33,145,26),Qt.AlignmentFlag.AlignRight,'→ Цемент')
        p.setFont(QFont('Segoe UI',9))
        p.drawText(QRectF(x+8,y+7,(sep-x)-16,28),Qt.AlignmentFlag.AlignLeft,
                   'Камера 1: удары')
        if chamber_split<1:
            p.drawText(QRectF(sep+8,y+7,(x+width-sep)-16,28),Qt.AlignmentFlag.AlignLeft,
                       'Камера 2: истирание')
        p.drawText(QRectF(x,r.bottom()-31,width,24),Qt.AlignmentFlag.AlignHCenter,
                   f'Продольный поток, условно: выход частиц {self.axial.discharge} шт. (схема)')

    def paintEvent(self,_event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        r=self.rect().adjusted(7,7,-7,-7)
        self._background(p,r)
        if self.mode=='cross':self._cross(p,r)
        else:self._length(p,r)
        p.end()


class HelpAnimationWidget(QWidget):
    """Drop-in replacement for operator_workflow_ui.HelpAnimationWidget."""
    def __init__(self, mode, parent=None):
        super().__init__(parent)
        self.view=MillCutWidget('cross' if mode=='cross' else 'length',self)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        controls=QHBoxLayout()
        self.pause=QPushButton('Пауза')
        self.pause.setCheckable(True)
        self.pause.toggled.connect(self._toggle)
        controls.addWidget(self.pause)
        if mode=='cross':
            controls.addWidget(QLabel('Камера:'))
            self.chamber_picker=QComboBox()
            self.chamber_picker.addItems([f'Камера {i+1}' for i in range(len(self.view.chambers))])
            self.chamber_picker.currentIndexChanged.connect(lambda i:self.view.set_chamber(i+1))
            controls.addWidget(self.chamber_picker)
        controls.addStretch(1)
        controls.addWidget(QLabel('Модель движения: демонстрация 2D'))
        layout.addLayout(controls)
        layout.addWidget(self.view,1)
        self.setMinimumHeight(325)

    def _toggle(self,paused):
        if paused:
            self.view.timer.stop()
            self.pause.setText('Продолжить')
        else:
            self.view.timer.start()
            self.pause.setText('Пауза')
