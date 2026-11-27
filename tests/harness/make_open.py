"""A second drawn test plan: a great room (a living room open along its whole side to the kitchen,
no dining room), for dining zones and their rugs, and a kitchen/dining room with counters and an island.
python3 make_open.py writes tests/harness/open/ and tests/harness/kd/: plan.png (20 px per foot, 6" walls), rooms.json (the stand-in model's rooms reply) and
openings.json (its doors and windows reply, with the plan's overall size)."""
import json, math, os
from PIL import Image, ImageDraw

PPF = 20          # pixels per foot
WALL = 10         # 6" walls
PAD = 60          # margin round the plan

def build(rooms, doors, windows, openings, open_sides, outdir, fixtures=()):
    W = int(max(r[1] + r[3] for r in rooms) * PPF + 2 * PAD)
    H = int(max(r[2] + r[4] for r in rooms) * PPF + 2 * PAD)
    im = Image.new('RGB', (W, H), 'white'); d = ImageDraw.Draw(im)
    X = lambda ft: PAD + ft * PPF
    def seg_drawn(a, b):
        for (p, q) in open_sides:
            if (abs(p[0] - a[0]) < 1e-6 and abs(q[0] - b[0]) < 1e-6 and abs(p[1] - a[1]) < 1e-6 and abs(q[1] - b[1]) < 1e-6): return False
        return True
    # walls: every room edge, centered on the room's outline, except open sides
    for name, x, y, w, h, *_ in rooms:
        for a, b in [((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)), ((x, y + h), (x + w, y + h)), ((x, y), (x, y + h))]:
            if not seg_drawn(a, b): continue
            d.rectangle([X(min(a[0], b[0])) - WALL / 2, X(min(a[1], b[1])) - WALL / 2, X(max(a[0], b[0])) + WALL / 2, X(max(a[1], b[1])) + WALL / 2], fill='#222222')
    def cut(a, b):   # clear a gap across the wall between points a and b (feet, along a wall line)
        x0, y0, x1, y1 = X(min(a[0], b[0])), X(min(a[1], b[1])), X(max(a[0], b[0])), X(max(a[1], b[1]))
        if abs(a[1] - b[1]) < 1e-6: d.rectangle([x0 + 1, y0 - WALL / 2 - 1, x1 - 1, y1 + WALL / 2 + 1], fill='white')
        else: d.rectangle([x0 - WALL / 2 - 1, y0 + 1, x1 + WALL / 2 + 1, y1 - 1], fill='white')
    ops = []
    for o in openings:
        a, b, rms = o; cut(a, b)
        ops.append({'kind': 'opening', 'type': None, 'x': (X((a[0] + b[0]) / 2)) / W * 100, 'y': X((a[1] + b[1]) / 2) / H * 100, 'width_in': None, 'rooms': rms})
    for dr in doors:   # (hinge point, along unit, width ft, into unit (perpendicular), rooms)
        hp, u, wd, n, rms = dr
        a = hp; b = (hp[0] + u[0] * wd, hp[1] + u[1] * wd); cut(a, b)
        # the leaf standing open, square to the wall, and its quarter arc
        lf = (hp[0] + n[0] * wd, hp[1] + n[1] * wd)
        d.line([X(hp[0]), X(hp[1]), X(lf[0]), X(lf[1])], fill='#222222', width=3)
        steps = 24; pts = []
        for k in range(steps + 1):
            t = k / steps * math.pi / 2
            v = (u[0] * math.cos(t) + n[0] * math.sin(t), u[1] * math.cos(t) + n[1] * math.sin(t))
            pts.append((X(hp[0] + v[0] * wd), X(hp[1] + v[1] * wd)))
        d.line(pts, fill='#555555', width=1)
        c = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ops.append({'kind': 'door', 'type': 'swing', 'x': X(c[0]) / W * 100, 'y': X(c[1]) / H * 100, 'width_in': round(wd * 12), 'rooms': rms})
    for a, b in windows:   # in outside walls: the gap with three thin lines along it
        cut(a, b)
        if abs(a[1] - b[1]) < 1e-6:
            for off in (-WALL / 2, 0, WALL / 2): d.line([X(a[0]), X(a[1]) + off, X(b[0]), X(b[1]) + off], fill='#333333', width=1)
        else:
            for off in (-WALL / 2, 0, WALL / 2): d.line([X(a[0]) + off, X(a[1]), X(b[0]) + off, X(b[1])], fill='#333333', width=1)
        c = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ops.append({'kind': 'window', 'type': None, 'x': X(c[0]) / W * 100, 'y': X(c[1]) / H * 100, 'width_in': None, 'rooms': ['', 'outside']})
    fx = []
    for kind, x0, y0, x1, y1 in fixtures:   # counters and islands: thin-line boxes, a sink on the long ones
        d.rectangle([X(x0), X(y0), X(x1), X(y1)], outline='#555555', width=2)
        if kind == 'island' or max(x1 - x0, y1 - y0) > 6:
            cx, cy = X((x0 + x1) / 2), X((y0 + y1) / 2); d.rounded_rectangle([cx - 14, cy - 9, cx + 14, cy + 9], 4, outline='#777777', width=1)
        fx.append({'kind': kind, 'x': round(X(x0) / W * 100, 2), 'y': round(X(y0) / H * 100, 2), 'w': round((x1 - x0) * PPF / W * 100, 2), 'h': round((y1 - y0) * PPF / H * 100, 2)})
    for name, x, y, w, h, *_ in rooms:   # printed names and sizes, for the eye (OCR is off in the harness)
        d.text((X(x + w / 2) - 30, X(y + h / 2) - 8), name.upper(), fill='#222222')
        d.text((X(x + w / 2) - 30, X(y + h / 2) + 6), "%d' x %d'" % (round(w), round(h)) if w == round(w) and h == round(h) else '', fill='#222222')
    os.makedirs(outdir, exist_ok=True)
    im.save(os.path.join(outdir, 'plan.png'))
    def fi(v):
        f = int(v); i = round((v - f) * 12); return f, i
    rj = []
    for name, x, y, w, h, *rest in rooms:
        printed = not rest or rest[0]
        rj.append({'name': name, 'label': name, 'width_ft': w if printed else None, 'length_ft': h if printed else None, 'area_sqft': None,
                   'source': 'labeled' if printed else 'estimated',
                   'bbox': {'x': round(X(x) / W * 100, 2), 'y': round(X(y) / H * 100, 2), 'w': round(w * PPF / W * 100, 2), 'h': round(h * PPF / H * 100, 2)}})
    ow = max(r[1] + r[3] for r in rooms) - min(r[1] for r in rooms); ol = max(r[2] + r[4] for r in rooms) - min(r[2] for r in rooms)
    json.dump({'unit': 'ft', 'rooms': rj}, open(os.path.join(outdir, 'rooms.json'), 'w'), indent=1)
    for o in ops: o['x'] = round(o['x'], 2); o['y'] = round(o['y'], 2)
    json.dump({'openings': ops, 'overall': {'width_ft': ow, 'length_ft': ol}, 'dims': [], 'fixtures': fx}, open(os.path.join(outdir, 'openings.json'), 'w'), indent=1)
    print(outdir, W, H, len(ops), 'openings')

HERE = os.path.dirname(os.path.abspath(__file__))
R, D, L, U = (1, 0), (0, 1), (-1, 0), (0, -1)

# The great room: one living room open along its whole side to the kitchen, no dining room;
# a bedroom and a bath off a short hall.
rooms2 = [
    ('Living Room', 0, 0, 26, 18), ('Kitchen', 26, 0, 11, 18),
    ('Bedroom', 0, 18, 14, 12), ('Bath', 14, 18, 8, 7), ('Hall', 14, 25, 8, 5), ('Closet', 22, 18, 15, 6, False),
]
doors2 = [((0, 7), D, 3, R, ['Living Room', 'outside']), ((5, 18), R, 2.75, D, ['Bedroom', 'Living Room']),
          ((15, 18), R, 2.5, D, ['Bath', 'Living Room']), ((28, 18), R, 2.75, D, ['Closet', 'Kitchen'])]
windows2 = [((4, 0), (10, 0)), ((14, 0), (21, 0)), ((29, 0), (34, 0)), ((0, 22), (0, 27)), ((4, 30), (10, 30)), ((37, 6), (37, 11))]
openings2 = [((14, 27), (14, 29.5), ['Bedroom', 'Hall'])]
build(rooms2, doors2, windows2, openings2, [((26, 0), (26, 18))], os.path.join(HERE, 'open'))

# A kitchen/dining room: an L of counters along the top and right walls (25" deep, from the wall's
# face), an island, and open floor at the left end for a table; a living room beside it.
w2 = 0.25   # half a wall, in feet: counters start at the wall's face
rooms3 = [('Kitchen/Dining', 0, 0, 24, 15), ('Living Room', 0, 15, 24, 14), ('Bath', 24, 15, 8, 7), ('Bedroom', 24, 0, 12, 15)]
doors3 = [((0, 18), D, 3, R, ['Living Room', 'outside']), ((25, 15), R, 2.5, D, ['Bath', 'Living Room']), ((24, 10), D, 2.75, R, ['Bedroom', 'Kitchen/Dining'])]
windows3 = [((3, 0), (9, 0)), ((14, 0), (19, 0)), ((0, 4), (0, 10)), ((5, 29), (11, 29)), ((36, 4), (36, 10))]
openings3 = [((4, 15), (16, 15), ['Kitchen/Dining', 'Living Room'])]
fixtures3 = [('counter', 12, w2, 24 - w2, w2 + 25 / 12), ('counter', 24 - w2 - 25 / 12, w2 + 25 / 12, 24 - w2, 8), ('island', 14.5, 5.5, 19.5, 8.5)]
build(rooms3, doors3, windows3, openings3, [], os.path.join(HERE, 'kd'), fixtures3)
