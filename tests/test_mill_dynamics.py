import math
from mill_dynamics import DrumCharge, AxialTransport


def test_charge_has_balls_and_clinker_and_integrates():
    charge=DrumCharge(rpm=16.,diameter_m=4.,chamber=1,
                      sizes_mm=[90,80,70,60,50])
    assert 5<len(charge.balls)<=46
    assert len(charge.grains)==80
    assert abs(charge.critical_rpm-21.15)<.2
    for _ in range(240):
        charge.step(.033)
    assert 7.8<charge.time<8.1
    assert charge.impact_count>0
    assert charge.breakage_count>0
    for body in charge.balls:
        assert math.hypot(body.x,body.y) <= 1.01-body.r
        assert all(math.isfinite(x) for x in (body.x,body.y,body.vx,body.vy))


def test_chambers_and_axial_discharge():
    first=DrumCharge(chamber=1,sizes_mm=[90,80,70])
    second=DrumCharge(chamber=2,sizes_mm=[25,20,17])
    assert min(ball.r for ball in second.balls)<max(ball.r for ball in first.balls)
    axial=AxialTransport(chambers=2,split=.48)
    for _ in range(400): axial.step(.04,throughput_tph=72.)
    assert axial.discharge>0
    assert all(0<=g.pos<1 for g in axial.grains)
    assert all(0<=g.grade<=9 for g in axial.grains)


def test_fixed_step_remains_stable_with_large_gui_pause():
    sim=DrumCharge()
    sim.step(100.)
    assert sim.time<=.08000001
    assert all(math.hypot(b.x,b.y)<1.01 for b in sim.balls)
