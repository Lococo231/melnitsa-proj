"""Animation-oriented mill dynamics helpers.

This module is intentionally independent from Qt. It provides a light-weight,
physically motivated approximation of:
- charge motion in a transverse mill section
- axial transport through a two-chamber cement ball mill

The animation is illustrative only and is NOT used for plant calculations.
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


@dataclass
class AxialParticle:
    x: float
    y: float
    vx: float
    chamber: int
    grade: int
    age: float
    phase: float


class DrumCharge:
    """Small stable 2D cross-section contact model.

    The objective is visual plausibility, not industrial DEM fidelity.
    """

    def __init__(self, rpm: float = 16.0, diameter_m: float = 4.0,
                 chamber: int = 1, sizes_mm: list[float] | None = None,
                 seed: int = 19):
        self.rng = random.Random(seed + int(chamber))
        self.rpm = max(0.01, float(rpm))
        self.diameter_m = max(1.0, float(diameter_m))
        self.chamber = int(chamber)
        self.time = 0.0
        self.rotation = 0.0
        self.impact_count = 0
        self.breakage_count = 0
        self.gravity = 7.6 if self.chamber == 1 else 6.8
        self.omega = 2 * pi * self.rpm / 60.0
        sizelist = [float(s) for s in (sizes_mm or [90, 80, 70, 60, 50]) if float(s) > 0]
        if not sizelist:
            sizelist = [60.0]
        self._radii = [min(0.090, max(0.026, s / self.diameter_m / 1000.0 * 2.6)) for s in sizelist]
        self.balls: list[Body] = []
        self.grains: list[Body] = []
        self._seed_balls()
        for _ in range(90):
            self.grains.append(self._fresh_grain())

    @property
    def critical_rpm(self) -> float:
        return 42.3 / sqrt(self.diameter_m)

    def _seed_balls(self) -> None:
        spacing = max(self._radii) * (2.03 if self.chamber == 1 else 1.96)
        rows = 7 if self.chamber == 1 else 8
        max_balls = 44 if self.chamber == 1 else 52
        for row in range(rows):
            y = 0.90 - row * spacing * (0.92 if self.chamber == 1 else 0.84)
            width = sqrt(max(0.0, 1.0 - y * y)) - max(self._radii)
            offset = 0.5 * spacing if row % 2 else 0.0
            x = -width + offset
            while x <= width and len(self.balls) < max_balls:
                r = self._radii[len(self.balls) % len(self._radii)]
                if x * x + y * y < (1 - r) ** 2:
                    self.balls.append(Body(x, y, self.rng.uniform(-0.03, 0.03), 0.0, r))
                x += spacing

    def _fresh_grain(self) -> Body:
        x = self.rng.uniform(-0.68, 0.58)
        y = self.rng.uniform(-0.56, 0.52)
        if x * x + y * y > 0.82:
            x, y = x * 0.78, y * 0.78
        g = self.rng.randint(0, 3)
        return Body(x, y, self.rng.uniform(-0.22, 0.22), self.rng.uniform(-0.06, 0.06),
                    0.008 + (5 - g) * 0.004, grade=g, age=0.0)

    @staticmethod
    def _collide(a: Body, b: Body, restitution: float = 0.12) -> float:
        dx, dy = b.x - a.x, b.y - a.y
        dsq = dx * dx + dy * dy
        rr = a.r + b.r
        if dsq >= rr * rr:
            return 0.0
        d = max(1e-6, sqrt(dsq))
        nx, ny = dx / d, dy / d
        overlap = rr - d
        ma, mb = max(0.001, a.r ** 3), max(0.001, b.r ** 3)
        total = ma + mb
        a.x -= nx * overlap * (mb / total)
        a.y -= ny * overlap * (mb / total)
        b.x += nx * overlap * (ma / total)
        b.y += ny * overlap * (ma / total)
        relative = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny
        if relative >= 0.0:
            return 0.0
        impulse = -(1 + restitution) * relative / (1 / ma + 1 / mb)
        a.vx -= impulse * nx / ma
        a.vy -= impulse * ny / ma
        b.vx += impulse * nx / mb
        b.vy += impulse * ny / mb
        return -relative

    def _wall(self, body: Body, friction: float) -> None:
        radius = hypot(body.x, body.y)
        limit = 1.0 - body.r
        if radius <= limit:
            return
        nx, ny = body.x / max(radius, 1e-8), body.y / max(radius, 1e-8)
        body.x, body.y = nx * limit, ny * limit
        tvx, tvy = -self.omega * body.y, self.omega * body.x
        reln = (body.vx - tvx) * nx + (body.vy - tvy) * ny
        if reln > 0:
            body.vx -= 1.15 * reln * nx
            body.vy -= 1.15 * reln * ny
        body.vx += (tvx - body.vx) * friction
        body.vy += (tvy - body.vy) * friction

    def step(self, delta: float) -> None:
        remaining = min(max(0.0, float(delta)), 0.08)
        while remaining > 1e-9:
            dt = min(remaining, 1 / 170)
            remaining -= dt
            self.rotation += self.omega * dt
            self.time += dt
            wall_friction = 0.23 if self.chamber == 1 else 0.16
            for ball in self.balls:
                ball.vy += self.gravity * dt
                ball.x += ball.vx * dt
                ball.y += ball.vy * dt
                self._wall(ball, wall_friction)
            for _ in range(2):
                for i, a in enumerate(self.balls):
                    for b in self.balls[i + 1:]:
                        if self._collide(a, b, restitution=0.14 if self.chamber == 1 else 0.10) > 0.32:
                            self.impact_count += 1
                    self._wall(a, wall_friction * 0.85)
            for grain in self.grains:
                grain.age += dt
                grain.vy += self.gravity * dt * 0.58
                grain.x += grain.vx * dt
                grain.y += grain.vy * dt
                self._wall(grain, 0.08)
                for ball in self.balls:
                    speed = self._collide(grain, ball, restitution=0.08)
                    if speed > (0.52 if self.chamber == 1 else 0.44) and self.rng.random() < (0.22 if self.chamber == 1 else 0.14):
                        grain.grade = min(9, grain.grade + 1)
                        grain.r = max(0.003, grain.r * 0.79)
                        self.breakage_count += 1
                        grain.vx *= 0.74
                        grain.vy *= 0.74
                        break
                if grain.age > 6.0 or grain.grade >= 9:
                    other = self._fresh_grain()
                    grain.x, grain.y, grain.vx, grain.vy, grain.r, grain.grade, grain.age = (
                        other.x, other.y, other.vx, other.vy, other.r, other.grade, other.age)


class AxialTransport:
    """Animation state for the longitudinal section of a cement ball mill."""

    def __init__(self, chamber_lengths_m: list[float] | None = None,
                 seed: int = 31):
        self.rng = random.Random(seed)
        lengths = chamber_lengths_m or [6.3, 6.6]
        if len(lengths) < 2:
            lengths = [lengths[0], lengths[0]]
        total = max(0.1, float(sum(lengths[:2])))
        self.chamber_lengths = [float(lengths[0]), float(lengths[1])]
        self.split = self.chamber_lengths[0] / total
        self.time = 0.0
        self.discharge = 0
        self.particles: list[AxialParticle] = []
        for _ in range(90):
            chamber = 1 if self.rng.random() < self.split else 2
            x = self.rng.uniform(0.02, self.split - 0.01) if chamber == 1 else self.rng.uniform(self.split + 0.01, 0.97)
            self.particles.append(self._new_particle(x=x, chamber=chamber, age=self.rng.uniform(0.0, 6.0)))

    def _new_particle(self, x: float = 0.01, chamber: int = 1, age: float = 0.0) -> AxialParticle:
        grade = self.rng.randint(0, 2) if chamber == 1 else self.rng.randint(4, 7)
        y = self.rng.uniform(0.22, 0.62) if chamber == 1 else self.rng.uniform(0.25, 0.58)
        vx = self.rng.uniform(0.04, 0.07)
        return AxialParticle(x=x, y=y, vx=vx, chamber=chamber, grade=grade,
                             age=age, phase=self.rng.random() * 2 * pi)

    def step(self, dt: float, throughput_tph: float = 72.0) -> None:
        delta = min(0.09, max(0.0, float(dt)))
        self.time += delta
        base = 0.07 * max(0.35, min(2.3, throughput_tph / 72.0))
        for p in self.particles:
            p.age += delta
            if p.x < self.split:
                p.chamber = 1
                speed = base * 0.74
                p.phase += delta * 1.4
                p.y += sin(p.phase) * 0.008
                if self.rng.random() < delta * 1.3:
                    p.grade = min(6, p.grade + 1)
            else:
                p.chamber = 2
                speed = base * 1.08
                p.phase += delta * 1.9
                p.y += sin(p.phase) * 0.006
                if self.rng.random() < delta * 1.8:
                    p.grade = min(9, p.grade + 1)
            p.x += speed * delta
            if abs(p.x - self.split) < 0.02 and self.rng.random() < 0.18:
                p.y = min(0.66, max(0.19, p.y + self.rng.uniform(-0.04, 0.05)))
                p.grade = min(8, p.grade + 1)
            if p.x >= 1.0:
                self.discharge += 1
                fresh = self._new_particle(x=0.01, chamber=1)
                p.x, p.y, p.vx, p.chamber, p.grade, p.age, p.phase = (
                    fresh.x, fresh.y, fresh.vx, fresh.chamber, fresh.grade, fresh.age, fresh.phase)
            p.y = min(0.70, max(0.16, p.y))

    def media_layout(self) -> dict[str, list[tuple[float, float, float]]]:
        """Return stylized ball layouts for both chambers.

        Coordinates are normalized inside each chamber rectangle.
        """
        layout = {'ch1': [], 'ch2': []}
        # Chamber 1: larger balls and a higher shoulder.
        rows1 = 4
        for row in range(rows1):
            y = 0.78 - row * 0.12
            count = 8 - row
            for idx in range(count):
                x = 0.08 + idx * 0.095 + (0.045 if row % 2 else 0.0)
                if x < 0.96:
                    layout['ch1'].append((x, y - 0.03 * x, 0.044 - row * 0.004))
        # Chamber 2: smaller media and fuller fine-grinding bed.
        rows2 = 5
        for row in range(rows2):
            y = 0.80 - row * 0.10
            count = 10 - row
            for idx in range(count):
                x = 0.06 + idx * 0.085 + (0.04 if row % 2 else 0.0)
                if x < 0.97:
                    layout['ch2'].append((x, y - 0.015 * x, 0.030 - row * 0.0026))
        return layout


if __name__ == '__main__':
    drum = DrumCharge()
    axial = AxialTransport([6.3, 6.6])
    for _ in range(100):
        drum.step(0.03)
        axial.step(0.03)
    print(len(drum.balls), drum.impact_count, drum.breakage_count, axial.discharge)
