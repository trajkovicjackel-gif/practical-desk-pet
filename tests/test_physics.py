# -*- coding: utf-8 -*-
"""Plain-assert unit tests for desktop_pet.physics (no pytest needed).

Run:  python tests/test_physics.py
"""

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desktop_pet import physics
from desktop_pet.physics import (
    Ball, PongState, pong_step, pong_ai_step,
    slingshot_velocity, projectile_step, slap_down, trajectory_points,
    balloon_target_y, balloon_step, balloon_attraction, balloon_collision,
    pong_ball_collision, explosion_impulse,
    circle_rect_overlap, clamp,
)

FIELD = (0, 0, 1920, 1040)  # typical work area

failures = []


def check(name, cond, detail=""):
    if not cond:
        failures.append(f"{name}: {detail}")
        print(f"FAIL {name} {detail}")
    else:
        print(f"ok   {name}")


# ---------------------------------------------------------------- pong
def test_pong_bounce_edges():
    st = PongState(field=FIELD)
    st.balls.append(Ball(x=10, y=500, r=50, vx=-100, vy=0))
    pong_step(st, 1 / 60, FIELD)
    b = st.balls[0]
    check("pong left bounce", b.vx > 0, f"vx={b.vx}")
    check("pong stays in field", b.x - b.r >= 0, f"x={b.x}")

    st.balls[0] = Ball(x=1900, y=500, r=50, vx=100, vy=0)
    pong_step(st, 1 / 60, FIELD)
    check("pong right bounce", st.balls[0].vx < 0, f"vx={st.balls[0].vx}")


def test_pong_top_loss_scores_plus():
    st = PongState(field=FIELD)
    st.balls.append(Ball(x=960, y=60, r=50, vx=0, vy=-400))
    events = []
    for _ in range(30):
        events = pong_step(st, 1 / 60, FIELD)
        if events:
            break
    check("pong top event", any(e[0] == "lost_top" for e in events), str(events))
    check("pong top score +1", st.score == 1, f"score={st.score}")
    check("pong ball removed", len(st.balls) == 0)


def test_pong_bottom_loss_scores_minus():
    st = PongState(field=FIELD)
    st.balls.append(Ball(x=960, y=1000, r=50, vx=0, vy=200))
    events = pong_step(st, 1 / 30, FIELD)
    check("pong bottom event", any(e[0] == "lost_bottom" for e in events), str(events))
    check("pong bottom score -1", st.score == -1, f"score={st.score}")


def test_pong_platform_bounce():
    st = PongState(field=FIELD)
    st.top_platform = (400, 0, 200, 14)
    st.balls.append(Ball(x=500, y=30, r=50, vx=0, vy=-120))
    events = pong_step(st, 1 / 60, FIELD)
    check("pong platform bounce keeps ball", len(st.balls) == 1)
    check("pong platform bounce vy>0", st.balls[0].vy > 0, f"vy={st.balls[0].vy}")
    check("pong platform no loss event", events == [], str(events))


def test_pong_ai_follows():
    tp = (0.0, 0.0, 200.0, 14.0)
    ball = Ball(x=1500, y=300, r=50)
    tp2 = pong_ai_step(tp, ball, 1 / 60, speed=420)
    check("pong ai moves toward ball", tp2[0] > 0, f"x={tp2[0]}")
    check("pong ai speed capped", tp2[0] <= 420 / 60 + 0.5, f"x={tp2[0]}")


def test_pong_ai_predictive():
    # hell mode: predicts the ball's future x (ball moving up-right)
    tp = (0.0, 0.0, 200.0, 14.0)
    ball = Ball(x=500, y=600, r=50, vx=300, vy=-200)
    # platform at y=0..14; time to reach = (600-14)/200 = 2.93s
    # predicted x = 500 + 300*2.93 = 1379 (clamped to field)
    px = tp[0]
    for _ in range(200):
        px, _, _, _ = pong_ai_step((px, 0, 200, 14), ball, 1 / 60,
                                   speed=780, predictive=True, field=FIELD)
    check("predictive aims ahead of the ball",
          px > 1000, f"platform x={px} (predicted ~1379)")


# ------------------------------------------------------------ basketball
def test_slingshot_direction():
    # pull down-left (dx>0, dy<0) -> launch up-right (vx>0, vy<0)
    vx, vy = slingshot_velocity(300, -200, 9.0)
    check("slingshot pulls down-left -> launches up-right", vx > 0 and vy < 0, f"({vx},{vy})")
    check("slingshot magnitude scales with distance", abs(vx) > 1000)


def test_projectile_gravity_and_floor():
    b = Ball(x=960, y=500, r=50, vx=0, vy=0)
    for _ in range(60):
        projectile_step(b, 1 / 60, FIELD)
    check("projectile falls", b.y > 500, f"y={b.y}")
    check("projectile floor bounce keeps inside", b.y + b.r <= FIELD[3] + 1, f"y={b.y}")
    # after many ticks it should settle near the floor
    for _ in range(60 * 10):
        projectile_step(b, 1 / 60, FIELD)
    check("projectile settles on floor", FIELD[3] - (b.y + b.r) < 30, f"y={b.y}")


def test_projectile_wall_bounce():
    b = Ball(x=30, y=500, r=50, vx=-600, vy=0)
    for _ in range(120):
        projectile_step(b, 1 / 60, FIELD)
    check("projectile wall bounce keeps inside", b.x - b.r >= 0, f"x={b.x}")
    check("projectile wall bounce vx>=0", b.vx >= 0, f"vx={b.vx}")


def test_slap_down():
    b = Ball(x=960, y=500, r=50, vx=0, vy=-100)
    slap_down(b, 900.0)
    check("slap adds downward impulse", b.vy > 0, f"vy={b.vy}")


def test_trajectory_preview():
    pts = trajectory_points(500, 800, 700, -900, 50, FIELD)
    check("trajectory has points", len(pts) > 5, f"n={len(pts)}")
    check("trajectory inside field", all(0 <= x <= FIELD[2] and 0 <= y <= FIELD[3] for x, y in pts))


def test_trajectory_fraction():
    full = trajectory_points(500, 800, 700, -900, 50, FIELD, fraction=1.0)
    quarter = trajectory_points(500, 800, 700, -900, 50, FIELD, fraction=0.25)
    check("fraction reduces point count", len(quarter) < len(full),
          f"q={len(quarter)} full={len(full)}")
    check("fraction ~25%", abs(len(quarter) - max(1, int(len(full) * 0.25))) <= 2,
          f"q={len(quarter)} full={len(full)}")
    check("fraction keeps head", quarter[0] == full[0], f"{quarter[0]} vs {full[0]}")


def test_hoop_score_geometry():
    hoop = (FIELD[2] - 150 - 18, FIELD[3] - 150 - 12, 150, 150)
    ring_cx, ring_cy = hoop[0] + 75, hoop[1] + 75
    ring_r = 150 * 0.32
    b = Ball(x=ring_cx, y=ring_cy, r=50)
    d = math.hypot(b.x - ring_cx, b.y - ring_cy)
    check("hoop overlap scores", d <= ring_r + b.r * 0.4)


# --------------------------------------------------------------- balloon
def test_balloon_water_height():
    check("water 0 -> top", balloon_target_y(FIELD, 0) == 0)
    check("water 100 -> bottom", balloon_target_y(FIELD, 100) == FIELD[3])
    h50 = balloon_target_y(FIELD, 50)
    check("water 50 -> middle", abs(h50 - FIELD[3] / 2) < 1, f"h={h50}")
    check("monotonic (more water -> lower)",
          balloon_target_y(FIELD, 20) < balloon_target_y(FIELD, 80))


def test_balloon_step_slow_rise():
    y = balloon_target_y(FIELD, 100)      # bottom (full water)
    target = balloon_target_y(FIELD, 0)   # top (no water)
    y1 = balloon_step(y, target, 1 / 60)
    check("balloon rises slowly", y1 < y, f"y1={y1}")
    check("balloon step bounded", (y - y1) <= 46 / 60 + 1e-6, f"delta={y - y1}")
    # converges
    cur = y
    for _ in range(60 * 60):
        cur = balloon_step(cur, target, 1 / 60)
    check("balloon converges to target", abs(cur - target) < 2, f"cur={cur}")


def test_balloon_sink_on_water():
    # adding water makes the balloon heavier, so it sinks to the bottom;
    # sinking is deliberately faster than rising so it responds in real time
    top = balloon_target_y(FIELD, 0)       # top
    target = balloon_target_y(FIELD, 100)  # bottom
    y1 = balloon_step(top, target, 1 / 60)
    check("balloon sinks", y1 > top, f"y1={y1}")
    check("sink faster than rise", (y1 - top) > 46 / 60, f"delta={y1 - top}")
    cur = top
    for _ in range(60 * 30):
        cur = balloon_step(cur, target, 1 / 60)
    check("sink converges to bottom", abs(cur - target) < 2, f"cur={cur}")


def test_balloon_attraction():
    # two overlapping balloons pull together; distant ones do not move
    offsets = balloon_attraction([(100.0, 100.0, 50.0), (110.0, 100.0, 50.0)])
    dx = offsets[0][0]
    check("nearby balloons attract", dx > 0, f"dx={dx}")
    offsets2 = balloon_attraction([(100.0, 100.0, 50.0), (900.0, 100.0, 50.0)])
    check("distant balloons unaffected",
          offsets2[0][0] == 0.0 and offsets2[1][0] == 0.0, str(offsets2))
    # symmetric: equal and opposite
    check("attraction symmetric",
          abs(offsets[0][0] + offsets[1][0]) < 1e-9, str(offsets))


def test_balloon_collision_volume():
    # overlapping balloons are pushed apart (no overlap left)
    a = (100.0, 100.0, 50.0)
    b = (130.0, 100.0, 50.0)
    offs = balloon_collision([a, b])
    x1 = a[0] + offs[0][0]
    x2 = b[0] + offs[1][0]
    check("overlap resolved", x2 - x1 >= 100.0 - 1e-6, f"{x1} {x2}")
    # non-overlapping balloons untouched
    offs2 = balloon_collision([(100.0, 100.0, 50.0), (500.0, 100.0, 50.0)])
    check("non-overlap untouched",
          offs2[0] == (0.0, 0.0) and offs2[1] == (0.0, 0.0), str(offs2))


def test_pong_ball_collision_elastic():
    # head-on equal-mass collision: velocities swap along the axis
    a = Ball(x=100, y=100, r=50, vx=300, vy=0)
    b = Ball(x=190, y=100, r=50, vx=-300, vy=0)   # overlapping (90 < 100)
    pong_ball_collision([a, b])
    check("head-on swap a", a.vx < 0, f"a.vx={a.vx}")
    check("head-on swap b", b.vx > 0, f"b.vx={b.vx}")
    check("separated", b.x - a.x >= 100.0 - 1e-6, f"{a.x} {b.x}")
    # energy preserved: |v| sum unchanged
    e0 = 300 * 300 + 300 * 300
    e1 = a.vx ** 2 + b.vx ** 2
    check("energy preserved", abs(e1 - e0) < 1e-6, f"{e1} vs {e0}")


def test_explosion_impulse():
    center = (200.0, 200.0)
    balls = [(150.0, 200.0, 50.0), (600.0, 200.0, 50.0)]
    offs = explosion_impulse(balls, center, radius=300, strength=30)
    check("near balloon pushed away", offs[0][0] < 0, str(offs[0]))
    check("far balloon unaffected", offs[1] == (0.0, 0.0), str(offs[1]))
    # stronger closer to center
    offs2 = explosion_impulse([(199.0, 200.0, 50.0)], center, 300, 30)
    check("closer -> stronger",
          abs(offs2[0][0]) > abs(offs[0][0]), f"{offs2[0]} vs {offs[0]}")


def test_circle_rect():
    check("circle rect overlap", circle_rect_overlap(100, 100, 10, 95, 95, 20, 20))
    check("circle rect no overlap", not circle_rect_overlap(200, 200, 10, 0, 0, 20, 20))
    check("clamp", clamp(150, 0, 100) == 100 and clamp(-5, 0, 100) == 0)


if __name__ == "__main__":
    test_pong_bounce_edges()
    test_pong_top_loss_scores_plus()
    test_pong_bottom_loss_scores_minus()
    test_pong_platform_bounce()
    test_pong_ai_follows()
    test_pong_ai_predictive()
    test_slingshot_direction()
    test_projectile_gravity_and_floor()
    test_projectile_wall_bounce()
    test_slap_down()
    test_trajectory_preview()
    test_trajectory_fraction()
    test_hoop_score_geometry()
    test_balloon_water_height()
    test_balloon_step_slow_rise()
    test_balloon_sink_on_water()
    test_balloon_attraction()
    test_balloon_collision_volume()
    test_pong_ball_collision_elastic()
    test_explosion_impulse()
    test_circle_rect()
    if failures:
        print(f"\n{len(failures)} FAILURES")
        sys.exit(1)
    print("\nALL TESTS PASSED")
