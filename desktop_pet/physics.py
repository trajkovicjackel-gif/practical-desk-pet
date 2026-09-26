# -*- coding: utf-8 -*-
"""Pure game logic for the Desktop Pet — no Qt imports, fully unit-testable.

All coordinates use a field rect (x, y, w, h) that callers pass in;
the caller maps this to the screen work area (desktop minus taskbar).
"""

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def circle_rect_overlap(cx, cy, r, rx, ry, rw, rh):
    """Circle (cx,cy,r) vs axis-aligned rect overlap test."""
    nx = clamp(cx, rx, rx + rw)
    ny = clamp(cy, ry, ry + rh)
    dx = cx - nx
    dy = cy - ny
    return dx * dx + dy * dy <= r * r


@dataclass
class Ball:
    """A circular ball with position/velocity in field coordinates."""
    x: float
    y: float
    r: float
    vx: float = 0.0
    vy: float = 0.0


# ---------------------------------------------------------------------------
# pong mode
# ---------------------------------------------------------------------------

@dataclass
class PongState:
    field: tuple  # (x, y, w, h)
    balls: list = field(default_factory=list)
    top_platform: tuple = (0.0, 0.0, 0.0, 0.0)   # (x, y, w, h)
    bottom_platform: tuple = (0.0, 0.0, 0.0, 0.0)
    ai_speed: float = 420.0
    score: int = 0

    # outcomes returned by step()
    LOST_TOP = "lost_top"        # ball passed the top platform -> user +1
    LOST_BOTTOM = "lost_bottom"  # ball passed the bottom platform -> user -1


def pong_step(state, dt, field):
    """Advance one pong tick. Returns (events, balls_to_remove).

    events: list of ('lost_top'|'lost_bottom', index)
    """
    events = []
    remove = []
    fx, fy, fw, fh = field
    for i, b in enumerate(state.balls):
        b.x += b.vx * dt
        b.y += b.vy * dt

        # left/right edges: bounce
        if b.x - b.r < fx:
            b.x = fx + b.r
            b.vx = abs(b.vx)
        elif b.x + b.r > fx + fw:
            b.x = fx + fw - b.r
            b.vx = -abs(b.vx)

        # platforms: bounce back when the ball touches one
        px, py, pw, ph = state.top_platform
        if b.vy < 0 and circle_rect_overlap(b.x, b.y, b.r, px, py, pw, ph):
            b.y = py + ph + b.r
            b.vy = abs(b.vy)
            continue
        px, py, pw, ph = state.bottom_platform
        if b.vy > 0 and circle_rect_overlap(b.x, b.y, b.r, px, py, pw, ph):
            b.y = py - b.r
            b.vy = -abs(b.vy)
            continue

        # top / bottom edge: ball disappears
        if b.y - b.r <= fy:
            events.append(("lost_top", i))
            remove.append(i)
        elif b.y + b.r >= fy + fh:
            events.append(("lost_bottom", i))
            remove.append(i)

    # remove lost balls (descending indices)
    for i in sorted(remove, reverse=True):
        state.balls.pop(i)
    for ev in events:
        if ev[0] == "lost_top":
            state.score += 1
        elif ev[0] == "lost_bottom":
            state.score -= 1
    return events


def pong_ai_step(top_platform, ball, dt, speed=None, predictive=False,
                 field=None):
    """Move the AI top platform toward the ball.

    difficulty is expressed by the caller via `speed` (movement speed) and
    `predictive` (aim at the ball's future x based on its velocity):
      easy  -> low speed, no prediction
      hard  -> high speed, no prediction
      hell  -> high speed + predictive aiming
    """
    px, py, pw, ph = top_platform
    if ball is None:
        return top_platform
    if predictive and ball.vy < 0 and field is not None:
        # time for the ball to reach the platform line, then extrapolate x
        t = (ball.y - (py + ph)) / (-ball.vy)
        if t > 0:
            fx, fy, fw, fh = field
            target = ball.x + ball.vx * t
            target = max(fx + ball.r, min(fx + fw - ball.r, target))
        else:
            target = ball.x - pw / 2.0
    else:
        target = ball.x - pw / 2.0
    delta = target - px
    spd = speed if speed is not None else 420.0
    step = clamp(delta, -spd * dt, spd * dt)
    return (px + step, py, pw, ph)


# ---------------------------------------------------------------------------
# basketball mode (slingshot + projectile)
# ---------------------------------------------------------------------------

GRAVITY = 1600.0        # px/s^2
RESTITUTION = 0.62      # bounciness off walls/floor
FLOOR_FRICTION = 0.985  # vx damping per tick (frame-rate independent-ish)


def slingshot_velocity(drag_dx, drag_dy, k=9.0):
    """Angry-birds style slingshot.

    drag_dx/drag_dy use the convention (start_position - current_position):
    pulling the ball down-left gives dx>0, dy<0, and the launch goes up-right
    (vx>0, vy<0). Magnitude scales with the pull distance via k.
    """
    return drag_dx * k, drag_dy * k


def projectile_step(ball, dt, field):
    """One tick of parabolic motion with wall bounces. Returns bounce events."""
    events = []
    fx, fy, fw, fh = field
    ball.vy += GRAVITY * dt
    ball.x += ball.vx * dt
    ball.y += ball.vy * dt

    if ball.x - ball.r < fx:
        ball.x = fx + ball.r
        ball.vx = abs(ball.vx) * RESTITUTION
        events.append("wall_l")
    elif ball.x + ball.r > fx + fw:
        ball.x = fx + fw - ball.r
        ball.vx = -abs(ball.vx) * RESTITUTION
        events.append("wall_r")

    if ball.y - ball.r < fy:
        ball.y = fy + ball.r
        ball.vy = abs(ball.vy) * RESTITUTION
        events.append("wall_t")
    elif ball.y + ball.r > fy + fh:
        ball.y = fy + fh - ball.r
        ball.vy = -abs(ball.vy) * RESTITUTION
        ball.vx *= FLOOR_FRICTION
        events.append("floor")

    if abs(ball.vx) < 2.0:
        ball.vx = 0.0
    return events


def slap_down(ball, impulse=900.0):
    """Click-to-slap: push the ball downward."""
    ball.vy += impulse
    return ball


def trajectory_points(x, y, vx, vy, r, field, gravity=GRAVITY, dt=1/60.0,
                      max_seconds=2.2, restitution=RESTITUTION, step_every=3,
                      fraction=1.0):
    """Predict the flight path (with wall bounces) for trajectory preview.

    Returns a list of (px, py) sampled points (already decimated by step_every).
    When fraction < 1.0, only the first `fraction` of the whole flight is
    returned (e.g. 0.25 = the first quarter of the path).
    """
    fx, fy, fw, fh = field
    pts = []
    cx, cy, cvx, cvy = float(x), float(y), float(vx), float(vy)
    n = int(max_seconds / dt)
    for i in range(n):
        cvy += gravity * dt
        cx += cvx * dt
        cy += cvy * dt
        if cx - r < fx:
            cx = fx + r
            cvx = abs(cvx) * restitution
        elif cx + r > fx + fw:
            cx = fx + fw - r
            cvx = -abs(cvx) * restitution
        if cy - r < fy:
            cy = fy + r
            cvy = abs(cvy) * restitution
        elif cy + r > fy + fh:
            cy = fy + fh - r
            cvy = -abs(cvy) * restitution
            cvx *= FLOOR_FRICTION
        if i % step_every == 0:
            pts.append((cx, cy))
        if abs(cvy) < 10 and cy > fy + fh - r - 2:
            break
    if fraction < 1.0:
        keep = max(1, int(len(pts) * fraction))
        pts = pts[:keep]
    return pts


# ---------------------------------------------------------------------------
# balloon mode
# ---------------------------------------------------------------------------

def balloon_target_y(field, water_pct):
    """Floating height: more water -> lower (0% floats at the very top).

    water 0%   -> floats at the top edge.
    water 100% -> sinks to the bottom edge.
    (field is (x, y_top, w, h) in screen coordinates, y grows downward.)
    """
    fx, fy, fw, fh = field
    return fy + fh * (water_pct / 100.0)


def balloon_step(y, target_y, dt, rise_speed=46.0, sink_speed=160.0):
    """Slowly move the balloon toward its target height at uniform speed.

    Rising is gentle; sinking (heavier balloon) is noticeably faster so water
    changes respond in real time. Returns new y.
    """
    if abs(target_y - y) < 1.0:
        return target_y
    if target_y > y:
        return y + min(sink_speed * dt, abs(target_y - y))
    return y - min(rise_speed * dt, abs(target_y - y))


def balloon_attraction(balls):
    """Very weak mutual attraction between nearby balloons (a faint static
    pull). Strength is intentionally small so the user can pull balloons
    apart. Returns per-ball (dx, dy) offsets (pixels per tick)."""
    n = len(balls)
    offsets = [(0.0, 0.0)] * n
    for i in range(n):
        for j in range(i + 1, n):
            x1, y1, r1 = balls[i]
            x2, y2, r2 = balls[j]
            dx = x2 - x1
            dy = y2 - y1
            dist = math.hypot(dx, dy) or 1.0
            reach = (r1 + r2) * 1.35
            if dist >= reach:
                continue
            # faint pull, stronger when closer, capped very low
            strength = min(0.35, (reach - dist) / reach * 0.45)
            ux, uy = dx / dist, dy / dist
            offsets[i] = (offsets[i][0] + ux * strength,
                          offsets[i][1] + uy * strength)
            offsets[j] = (offsets[j][0] - ux * strength,
                          offsets[j][1] - uy * strength)
    return offsets


def balloon_collision(balls):
    """Hard collision volume: push overlapping balloons apart (no bounce).

    Returns per-ball (dx, dy) positional offsets that resolve every overlap.
    """
    n = len(balls)
    offsets = [0.0] * n
    offsets_y = [0.0] * n
    for i in range(n):
        for j in range(i + 1, n):
            x1, y1, r1 = balls[i]
            x2, y2, r2 = balls[j]
            dx = x2 - x1
            dy = y2 - y1
            dist = math.hypot(dx, dy) or 1.0
            overlap = (r1 + r2) - dist
            if overlap <= 0:
                continue
            ux, uy = dx / dist, dy / dist
            push = overlap / 2.0
            offsets[i] += -ux * push
            offsets_y[i] += -uy * push
            offsets[j] += ux * push
            offsets_y[j] += uy * push
    return list(zip(offsets, offsets_y))


def pong_ball_collision(balls):
    """Elastic collision between equal-mass pong balls.

    Overlapping pairs are separated and exchange the velocity component along
    the contact normal (equal-mass elastic bounce). Mutates the Ball objects.
    """
    n = len(balls)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = balls[i], balls[j]
            dx = b.x - a.x
            dy = b.y - a.y
            dist = math.hypot(dx, dy) or 1.0
            min_d = a.r + b.r
            if dist >= min_d:
                continue
            ux, uy = dx / dist, dy / dist
            # separate to just touching
            overlap = min_d - dist
            a.x -= ux * overlap / 2.0
            a.y -= uy * overlap / 2.0
            b.x += ux * overlap / 2.0
            b.y += uy * overlap / 2.0
            # equal-mass elastic: swap normal velocity components
            van = a.vx * ux + a.vy * uy
            vbn = b.vx * ux + b.vy * uy
            a.vx += (vbn - van) * ux
            a.vy += (vbn - van) * uy
            b.vx += (van - vbn) * ux
            b.vy += (van - vbn) * uy


def explosion_impulse(balls, center, radius, strength):
    """Shockwave from an explosion: push balloons away from `center`.

    Returns per-ball (dx, dy) positional impulses (pixels), strongest at the
    center and fading to zero at `radius`.
    """
    n = len(balls)
    offsets = [(0.0, 0.0)] * n
    cx, cy = center
    for i in range(n):
        x, y, r = balls[i]
        dx = x - cx
        dy = y - cy
        dist = math.hypot(dx, dy) or 1.0
        if dist > radius:
            continue
        falloff = 1.0 - dist / radius
        force = strength * (0.35 + 0.65 * falloff)
        ux, uy = dx / dist, dy / dist
        offsets[i] = (ux * force, uy * force)
    return offsets
