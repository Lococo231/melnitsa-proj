"""Interactive 2D drum charge approximation, derived from the former HTML.

For display/education only. A full calibrated DEM is NOT performed; no
simulated collision is fed into the production fineness/wear equations.
Coordinates are normalized by drum radius. No Qt dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, sin, hypot, pi, sqrt
import random


@dataclass
class Body:
    x: float
    y: float
    vx: float
    vy: float
    r: float
    grade: int = 0
    age: float = 0.0


class DrumCharge:
    """Small stable illustrative contact model with wall friction and impacts."""

    def __init__(self, rpm: float = 16., diameter_m: float = 4., chamber: int = 1,
                 sizes_mm: list[float] | None = None, seed: int = 19):
        self.rng = random.Random(seed)
        self.rpm = max(.01, float(rpm))
        self.diameter_m = max(1., float(diameter_m))
        self.chamber = int(chamber)
        self.time = 0.
        self.rotation = 0.
        self.impact_count = 0
        self.breakage_count = 0
        self.gravity = 7.0
        self.omega = 2*pi*self.rpm/60.
        # 2D ball radii are magnified relative to true 90mm / 4m ratio.
        sizelist = [s for s in (sizes_mm or [90,80,70,60,50]) if float(s) > 0]
        self.balls: list[Body] = []
        self.grains: list[Body] = []
        radii = [min(.090,max(.032,float(s)/self.diameter_m/1000*2.7)) for s in sizelist]
        if not radii:
            radii = [.058]
        # Deterministic hexagonal initial pack at the bottom of rotating shell.
        spacing = max(radii) * 2.12
        for row in range(7):
            y = .91 - row * spacing
            width = sqrt(max(.0, 1. - y*y)) - max(radii)
            offset = .5 * spacing if row % 2 else 0.
            x = -width + offset
            while x <= width and len(self.balls) < 46:
                r = radii[len(self.balls) % len(radii)]
                if x*x + y*y < (1-r)**2:
                    self.balls.append(Body(x,y,self.rng.uniform(-.02,.02),0.,r))
                x += spacing
        for _ in range(80):
            self.grains.append(self._fresh_grain())

    @property
    def critical_rpm(self) -> float:
        return 42.3 / sqrt(self.diameter_m)

    def _fresh_grain(self) -> Body:
        x = self.rng.uniform(-.65,.60)
        y = self.rng.uniform(-.60,.60)
        if x*x + y*y > .80:
            x,y = x*.65,y*.65
        g = self.rng.randint(0,3)
        return Body(x,y,self.rng.uniform(-.20,.20),self.rng.uniform(-.1,.1),
                    .008 + (5-g)*.004,grade=g,age=0.)

    @staticmethod
    def _collide(a: Body, b: Body, restitution: float = .14) -> float:
        dx,dy = b.x-a.x,b.y-a.y
        dsq = dx*dx+dy*dy
        rr = a.r+b.r
        if dsq >= rr*rr:
            return 0.
        d = max(1e-6,sqrt(dsq))
        nx,ny=dx/d,dy/d
        overlap=rr-d
        ma,mb=max(.001,a.r**3),max(.001,b.r**3)
        denom=ma+mb
        a.x -= nx*overlap*(mb/denom)
        a.y -= ny*overlap*(mb/denom)
        b.x += nx*overlap*(ma/denom)
        b.y += ny*overlap*(ma/denom)
        relative=(b.vx-a.vx)*nx+(b.vy-a.vy)*ny
        if relative>=0:
            return 0.
        impulse=-(1+restitution)*relative/(1/ma+1/mb)
        a.vx-=impulse*nx/ma
        a.vy-=impulse*ny/ma
        b.vx+=impulse*nx/mb
        b.vy+=impulse*ny/mb
        return -relative

    def _wall(self,b: Body, friction: float):
        radius=hypot(b.x,b.y)
        limit=1. - b.r
        if radius <= limit:
            return
        nx,ny=b.x/max(radius,1e-8),b.y/max(radius,1e-8)
        b.x,b.y=nx*limit,ny*limit
        # Contact with moving wall; tangential velocity is omega x radius.
        tvx,tvy=-self.omega*b.y,self.omega*b.x
        reln=(b.vx-tvx)*nx+(b.vy-tvy)*ny
        if reln>0:
            b.vx-=1.2*reln*nx
            b.vy-=1.2*reln*ny
        b.vx+=(tvx-b.vx)*friction
        b.vy+=(tvy-b.vy)*friction

    def step(self, delta: float):
        # The caller can send irregular GUI frame intervals. Fixed time steps
        # avoid ball tunneling and large accumulation of energy.
        remaining=min(max(0.,float(delta)),.08)
        while remaining>1e-9:
            dt=min(remaining,1/160)
            remaining-=dt
            self.rotation+=self.omega*dt
            self.time+=dt
            for ball in self.balls:
                ball.vy+=self.gravity*dt
                ball.x+=ball.vx*dt
                ball.y+=ball.vy*dt
                self._wall(ball,friction=.22 if self.chamber==1 else .13)
            for _ in range(2):
                for i,a in enumerate(self.balls):
                    for b in self.balls[i+1:]:
                        if self._collide(a,b)>.30:
                            self.impact_count+=1
                    self._wall(a,friction=.18)
            for grain in self.grains:
                grain.age+=dt
                grain.vy+=self.gravity*dt*.6
                grain.x+=grain.vx*dt
                grain.y+=grain.vy*dt
                self._wall(grain,friction=.06)
                # Pictorial grinding event: collision lowers grain size class.
                for ball in self.balls:
                    speed=self._collide(grain,ball,restitution=.1)
                    if speed>.45 and self.rng.random()<(.20 if self.chamber==1 else .13):
                        grain.grade=min(9,grain.grade+1)
                        grain.r=max(.003,grain.r*.80)
                        self.breakage_count+=1
                        break
                if grain.age>5.5 or grain.grade>=9:
                    other=self._fresh_grain()
                    grain.x,grain.y,grain.vx,grain.vy,grain.r,grain.grade,grain.age=(
                        other.x,other.y,other.vx,other.vy,other.r,other.grade,other.age)


@dataclass
class AxialGrain:
    pos: float
    depth: float
    grade: int
    phase: float


class AxialTransport:
    """Visual axial feed-through and size class transition across 1–2 chambers."""

    def __init__(self, chambers: int = 2, split: float = .48, seed: int = 31):
        self.rng=random.Random(seed)
        self.chambers=max(1,min(2,int(chambers)))
        self.split=max(.15,min(.85,float(split)))
        self.time=0.
        self.grains=[]
        for i in range(110):
            x=self.rng.random()
            self.grains.append(AxialGrain(x,self.rng.uniform(.12,.88),
                                          int(7*x*self.rng.random()),
                                          self.rng.random()*2*pi))
        self.discharge=0

    def step(self,dt:float, throughput_tph: float = 72.):
        delta=min(.09,max(0.,float(dt)))
        self.time+=delta
        speed=.065*max(.35,min(2.2,throughput_tph/72.))
        for grain in self.grains:
            grain.pos+=speed*delta*(1.2 if grain.pos>self.split else .85)
            grain.phase+=delta*(2. if grain.pos<self.split else 3.)
            if self.rng.random()<delta*(.9 if grain.pos<self.split else 1.5):
                grain.grade=min(9,grain.grade+1)
            if grain.pos>=1:
                self.discharge+=1
                grain.pos=.005
                grain.grade=self.rng.randint(0,2)
                grain.depth=self.rng.uniform(.12,.88)


if __name__=='__main__':
    sim=DrumCharge()
    for i in range(100):
        sim.step(.03)
    print(len(sim.balls),sim.impact_count,sim.breakage_count)
