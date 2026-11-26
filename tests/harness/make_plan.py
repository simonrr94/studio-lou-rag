"""Draws the harness test plan (10 rooms, 7 swing doors, 8 windows) at 20 px/ft and writes the
mocked model replies. Run: python3 make_plan.py"""
import json, math
from PIL import Image, ImageDraw

PPF, M, T = 20, 2, 0.5          # px per foot, margin (ft), wall thickness (ft)
W_FT, H_FT = 40, 28
img = Image.new('RGB', (int((W_FT + 2 * M) * PPF), int((H_FT + 2 * M) * PPF)), 'white')
d = ImageDraw.Draw(img)
def P(x, y): return ((x + M) * PPF, (y + M) * PPF)

ROOMS = [  # name, x0, y0, x1, y1 (wall center lines, ft)
    ('Living Room', 0, 0, 16, 15), ('Dining Room', 16, 0, 27, 11), ('Kitchen', 27, 0, 40, 11),
    ('Hall', 16, 11, 40, 15), ('Bedroom', 0, 15, 13, 28), ('Bath', 13, 15, 24, 21),
    ('Closet', 13, 21, 18, 28), ('Laundry', 18, 21, 24, 28), ('Office', 24, 15, 33, 28),
    ('Flex Room', 33, 15, 40, 28)]

WALLS = [((0, 0), (40, 0)), ((40, 0), (40, 28)), ((40, 28), (0, 28)), ((0, 28), (0, 0)),
         ((16, 0), (16, 11)), ((16, 11), (40, 11)), ((27, 0), (27, 11)), ((0, 15), (40, 15)),
         ((13, 15), (13, 28)), ((13, 21), (24, 21)), ((18, 21), (18, 28)), ((24, 15), (24, 28)),
         ((33, 15), (33, 28))]
OPENINGS_GAP = [((16, 11.25), (16, 14.75)),   # living to hall (x=16 from 11 to 15)
                ((19, 11), (23, 11)),        # dining to hall
                ((27, 2), (27, 9))]          # dining to kitchen
# swing doors: wall line, from, to (along the wall), side the leaf opens to (+1 / -1 across)
DOORS = [('v', 0, 4, 7, 1, 'Living Room', 'outside'),
         ('h', 15, 9, 11.5, 1, 'Bedroom', 'Living Room'),
         ('h', 15, 19, 21.5, 1, 'Bath', 'Hall'),
         ('h', 15, 27, 29.5, 1, 'Office', 'Hall'),
         ('h', 15, 35, 37.5, 1, 'Flex Room', 'Hall'),
         ('v', 13, 23, 25.5, 1, 'Closet', 'Bedroom'),
         ('v', 24, 24, 26.5, -1, 'Laundry', 'Office')]
WINDOWS = [('h', 0, 4, 9), ('h', 0, 19, 24), ('h', 0, 31, 36), ('v', 40, 3, 7),
           ('v', 0, 19, 24), ('h', 28, 4, 8), ('h', 28, 26, 31), ('v', 40, 19, 23)]

def wall(a, b):
    (x0, y0), (x1, y1) = a, b
    p0, p1 = P(min(x0, x1) - T / 2, min(y0, y1) - T / 2), P(max(x0, x1) + T / 2, max(y0, y1) + T / 2)
    d.rectangle([p0, p1], fill=(40, 40, 40))
def clear(o, at, a, b):
    if o == 'h': d.rectangle([P(a, at - T / 2 - 0.05), P(b, at + T / 2 + 0.05)], fill='white')
    else: d.rectangle([P(at - T / 2 - 0.05, a), P(at + T / 2 + 0.05, b)], fill='white')
for w in WALLS: wall(*w)
for a, b in OPENINGS_GAP:
    if a[0] == b[0]: clear('v', a[0], a[1], b[1])
    else: clear('h', a[1], a[0], b[0])
for o, at, a, b, s, *_ in DOORS:
    clear(o, at, a, b)
    wd = b - a
    if o == 'h':
        hinge, leaf, end = P(a, at), P(a, at + s * wd), P(b, at)
        d.line([hinge, leaf], fill=(40, 40, 40), width=3)
        box = [P(a - wd, at - wd), P(a + wd, at + wd)]
        st, en = (0, 90) if s > 0 else (270, 360)
    else:
        hinge, leaf, end = P(at, a), P(at + s * wd, a), P(at, b)
        d.line([hinge, leaf], fill=(40, 40, 40), width=3)
        box = [P(at - wd, a - wd), P(at + wd, a + wd)]
        st, en = (0, 90) if s > 0 else (90, 180)
    d.arc(box, st, en, fill=(60, 60, 60), width=1)
for o, at, a, b in WINDOWS:
    clear(o, at, a, b)
    for off in (-T / 2, 0, T / 2):
        if o == 'h': d.line([P(a, at + off), P(b, at + off)], fill=(70, 70, 70), width=1)
        else: d.line([P(at + off, a), P(at + off, b)], fill=(70, 70, 70), width=1)
    for e in (a, b):
        if o == 'h': d.line([P(e, at - T / 2), P(e, at + T / 2)], fill=(40, 40, 40), width=2)
        else: d.line([P(at - T / 2, e), P(at + T / 2, e)], fill=(40, 40, 40), width=2)
img.save('plan.png')

Wpx, Hpx = img.size
def pct(x, y): return round((x + M) * PPF / Wpx * 100, 2), round((y + M) * PPF / Hpx * 100, 2)
rooms = []
for name, x0, y0, x1, y1 in ROOMS:
    ix0, iy0, ix1, iy1 = x0 + T / 2, y0 + T / 2, x1 - T / 2, y1 - T / 2
    a, b = pct(ix0, iy0); c, e = pct(ix1, iy1)
    w, l = ix1 - ix0, iy1 - iy0
    rooms.append({'name': name, 'label': name, 'width_ft': w, 'length_ft': l, 'area_sqft': round(w * l),
                  'source': 'labeled', 'bbox': {'x': a, 'y': b, 'w': round(c - a, 2), 'h': round(e - b, 2)}})
ops = []
for o, at, a, b, s, r1, r2 in DOORS:
    x, y = pct(at, (a + b) / 2) if o == 'v' else pct((a + b) / 2, at)
    ops.append({'kind': 'door', 'type': 'swing', 'x': x, 'y': y, 'width_in': round((b - a) * 12), 'rooms': [r1, r2]})
for o, at, a, b in WINDOWS:
    x, y = pct(at, (a + b) / 2) if o == 'v' else pct((a + b) / 2, at)
    ops.append({'kind': 'window', 'type': None, 'x': x, 'y': y, 'width_in': round((b - a) * 12), 'rooms': ['', 'outside']})
json.dump({'unit': 'ft', 'rooms': rooms}, open('rooms.json', 'w'), indent=1)
json.dump({'openings': ops, 'overall': {'width_ft': W_FT + T, 'length_ft': H_FT + T}}, open('openings.json', 'w'), indent=1)
print(img.size, len(rooms), 'rooms', len(ops), 'openings')
