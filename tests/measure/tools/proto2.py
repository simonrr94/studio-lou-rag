"""Measure session 2 prototype: named rooms and a scale, walls first.
python3 proto2.py [--no-sizes] [plan ...]

Builds on proto.py (walls, breaks, spaces) and adds:
1. Names: the model's room list (the same stand-in reply score.py gives the page) is matched to the
   spaces: each room goes to the space covering most of its rough box.
2. Splits: a space holding two or more named rooms is cut along a wall line carried across the open
   floor (from a corner where a wall ends or turns, straight on to the next wall). The cut kept is the
   one whose pieces best match the rooms' rough boxes (and their printed sizes, as a ratio, when
   printed). Repeated until each piece holds one room.
3. Scale, from whichever of these the plan has, voted:
   - each named room against its printed size (width x length, or square feet)
   - printed dimension lines: the model reads the value and points at the ends, the drawing finds the
     line itself (and the break it measures, when it measures one)
   - the overall size against the outside faces of the walls
   - swing doors (rough: about 30" each), only when nothing else is found
   --no-sizes leaves printed room sizes out (to test the other ways on plans that print them).
Prints the same numbers score.py prints for the page, and writes proto2/<plan>.png."""
import json, os, sys, re, math
import numpy as np, cv2
sys.argv, _args = sys.argv[:1], sys.argv[1:]
import proto
from score import mock, poly_mask
import score as _score, random as _random
SEED = next((a.split('=')[1] for a in _args if a.startswith('--seed=')), None)
if SEED:   # other rough boxes and line ends from the stand-in model, to check nothing hangs on one draw
    class _R(_random.Random):
        def __init__(self, x=None): super().__init__(str(x) + SEED)
    _score.random = type('m', (), {'Random': _R})

D = proto.D
NO_SIZES = '--no-sizes' in _args or '--doors-only' in _args
DOORS_ONLY = '--doors-only' in _args
PLANS = [a for a in _args if not a.startswith('--')] or ['bedroom', 'studio', 'cabin', 'twostory', 'floor2']
OUT = os.path.join(D, 'proto2' + ('-doorsonly' if DOORS_ONLY else '-nosizes' if NO_SIZES else '')); os.makedirs(OUT, exist_ok=True)

def parse_ft(s):
    m = re.match(r"\s*(\d+)\s*['’]\s*(?:(\d+(?:\.\d+)?)\s*[\"”])?", s or '')
    return int(m.group(1)) + float(m.group(2) or 0) / 12 if m else None

# ---------- 1. names ----------
def box_px(r, W, H):
    b = r['bbox']; return (b['x'] / 100 * W, b['y'] / 100 * H, (b['x'] + b['w']) / 100 * W, (b['y'] + b['h']) / 100 * H)

def box_mask(bx, shape):
    m = np.zeros(shape, np.uint8); x0, y0, x1, y1 = [int(round(v)) for v in bx]
    m[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 1; return m

def iou(a, b):
    u = (a | b).sum(); return (a & b).sum() / u if u else 0

# ---------- 2. splits ----------
def corners(reg):
    """Reflex corners of a space's outline, each with the two directions its walls carry on in."""
    cs, _ = cv2.findContours(reg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in cs:
        if cv2.contourArea(c) < 50: continue
        p = cv2.approxPolyDP(c, 2.5, True)[:, 0, :].astype(float)
        n = len(p)
        if n < 4: continue
        area = sum(p[i][0] * p[(i + 1) % n][1] - p[(i + 1) % n][0] * p[i][1] for i in range(n))
        for i in range(n):
            a, v, b = p[i - 1], p[i], p[(i + 1) % n]
            e1, e2 = v - a, b - v
            cr = e1[0] * e2[1] - e1[1] * e2[0]
            if cr * area >= 0: continue          # convex corner
            if np.linalg.norm(e1) < 4 or np.linalg.norm(e2) < 4: continue
            dirs = []
            for d in (e1 / np.linalg.norm(e1), -e2 / np.linalg.norm(e2)):
                ang = math.degrees(math.atan2(d[1], d[0])) % 90
                if min(ang, 90 - ang) <= 8:      # level or plumb: snap it
                    d = np.array([round(d[0]), round(d[1])], float)
                dirs.append(d)
            out.append((v, dirs))
    return out

def carry(reg, v, d, maxlen, enter=6):
    """Step from corner v along d through the space until a wall: the cut line."""
    H, W = reg.shape
    pts, t, outside = [], 1.0, 0
    while t < maxlen:
        x, y = int(round(v[0] + d[0] * t)), int(round(v[1] + d[1] * t))
        if not (0 <= x < W and 0 <= y < H): return None
        if reg[y, x]: pts.append((x, y)); outside = 0
        elif pts:
            outside += 1
            if outside > 2: break
        elif t > enter: return None
        t += 1
    if len(pts) < 6: return None
    return (pts[0], pts[-1])

def cut_pieces(reg, cut, min_area):
    m = reg.copy()
    cv2.line(m, cut[0], cut[1], 0, 3)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=4)
    pcs = [(lab == i).astype(np.uint8) for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= min_area]
    if len(pcs) < 2: return None
    # slivers left over join the piece they touch most
    return pcs

def rooms_in(pieces, rooms):
    """Each room goes to the piece holding most of its box."""
    got = [[] for _ in pieces]
    for r in rooms:
        ov = [(p & r['bm']).sum() for p in pieces]
        got[int(np.argmax(ov))].append(r)
    return got

def fit(piece, rs, ppf_hint=None):
    u = np.zeros_like(piece)
    for r in rs: u |= r['bm']
    return iou(piece, u)

def ratio_term(pieces, got):
    """Pieces' areas against the printed areas, as a ratio (no scale needed)."""
    a = []
    for p, rs in zip(pieces, got):
        pr = [r['area_ft'] for r in rs]
        if not rs or any(x is None for x in pr): return 0
        a.append((p.sum(), sum(pr)))
    if len(a) < 2: return 0
    s = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            s += abs(math.log((a[i][0] / a[j][0]) / (a[i][1] / a[j][1])))
    return s

def candidates(reg, rs, brks, kmax):
    """Cut lines: (start, direction, how far in it may start, penalty).
    Walls carried on from the space's inside corners; the faces of door and window jambs carried
    across; and, last, the line midway between two rooms' rough boxes."""
    out = [(v, d, 6, 0) for v, dirs in corners(reg) for d in dirs]
    H, W = reg.shape
    for br in brks:
        a, b = np.array(br['a'], float), np.array(br['b'], float)
        u = (b - a) / max(1e-6, np.linalg.norm(b - a))
        n = np.array([-u[1], u[0]])
        for p in (a, b):
            x, y = int(p[0]), int(p[1])
            if not (0 <= x < W and 0 <= y < H): continue
            if not reg[max(0, y - kmax * 2):y + kmax * 2, max(0, x - kmax * 2):x + kmax * 2].any(): continue
            for d in (n, -n): out.append((p, d, kmax + 6, 0.01))
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            A, B = rs[i]['box'], rs[j]['box']
            for ax in (0, 1):   # 0: rooms side by side, a plumb line; 1: one above the other, a level line
                lo, hi = (A, B) if (A[ax] + A[ax + 2]) < (B[ax] + B[ax + 2]) else (B, A)
                m = (lo[ax + 2] + hi[ax]) / 2
                o0, o1 = max(lo[1 - ax], hi[1 - ax]), min(lo[3 - ax], hi[3 - ax])
                if o1 <= o0: continue
                c = (m, (o0 + o1) / 2) if ax == 0 else ((o0 + o1) / 2, m)
                d = np.array([0., 1.]) if ax == 0 else np.array([1., 0.])
                c = np.array(c)
                if not reg[int(c[1]), int(c[0])]: continue
                # carry both ways from the middle: one cut from wall to wall
                e1, e2 = c.copy(), c.copy()
                while reg[int(e1[1]), int(e1[0])] and 0 < e1[0] < W - 1 and 0 < e1[1] < H - 1: e1 -= d
                out.append((e1 + d, d, 3, 0.05))
    return out

def trim(reg, r, kmax, brks):
    """One room in a space that runs on past its box (a vestibule or closet the model didn't name):
    cut off what lies mostly outside the room's box, along a wall line or jamb, when that clearly
    fits the box better."""
    out = []
    for _ in range(3):
        base = iou(reg, r['bm'])
        best = None
        for v, d, enter, pen in candidates(reg, [r], brks, kmax):
            c = carry(reg, v, d, max(reg.shape), enter)
            if not c: continue
            pcs = cut_pieces(reg, c, (kmax * 2) ** 2)
            if not pcs: continue
            keep = max(range(len(pcs)), key=lambda i: (pcs[i] & r['bm']).sum())
            rest = [q for i, q in enumerate(pcs) if i != keep]
            if any((q & r['bm']).sum() > 0.35 * q.sum() for q in rest): continue
            # what's cut off is room-sized, wider than the rough box can be off by (a strip along a
            # wall is the box being rough, not a second room)
            if any(cv2.distanceTransform(q, cv2.DIST_L2, 3).max() * 2 < max(3 * kmax, 0.04 * max(reg.shape)) for q in rest): continue
            gain = iou(pcs[keep], r['bm']) - base - pen
            if gain >= 0.06 and (best is None or gain > best[0]): best = (gain, pcs[keep], rest)
        if not best: break
        reg = best[1]; out += [(q, 'trimmed') for q in best[2]]
    return [(reg, r)] + out

def split(reg, rs, kmax, brks, depth=0):
    """Cut reg until each piece holds one room. Returns [(piece, room)]."""
    if len(rs) == 1: return trim(reg, rs[0], kmax, brks)
    if not rs or depth > 6: return [(reg, rs[0] if rs else None)]
    best = None
    min_area = (kmax * 2) ** 2
    seen = set()
    for v, d, enter, pen in candidates(reg, rs, brks, kmax):
        if True:
            c = carry(reg, v, d, max(reg.shape), enter)
            if not c: continue
            k = (c[0][0] // 3, c[0][1] // 3, c[1][0] // 3, c[1][1] // 3)
            if k in seen: continue
            seen.add(k)
            pcs = cut_pieces(reg, c, min_area)
            if not pcs: continue
            got = rooms_in(pcs, rs)
            if any(not g for g in got):
                # a piece with no room in it: fold it into its neighbour by trying the next cut
                continue
            L = math.hypot(c[1][0] - c[0][0], c[1][1] - c[0][1])
            f = sum(fit(p, g) * len(g) for p, g in zip(pcs, got)) / len(rs)
            score = f - 0.25 * ratio_term(pcs, got) - 0.002 * L / kmax - pen
            if best is None or score > best[0]: best = (score, pcs, got, c)
    if not best: return [(reg, rs[0])] + [(None, r) for r in rs[1:]]
    out = []
    for p, g in zip(best[1], best[2]): out += split(p, g, kmax, brks, depth + 1)
    return out

def join_leftovers(named, rooms, kmax):
    """A space no room claimed, lying mostly inside one room's box and next to that room's piece
    (a toilet nook behind a drawn tub edge), joins that room."""
    reach = np.ones((2 * kmax + 7, 2 * kmax + 7), np.uint8)
    out = [list(x) for x in named]
    for x in out:
        p, r = x
        if r is not None or p is None: continue   # 'trimmed' pieces stay out
        inside = [(rr, (p & rr['bm']).sum() / p.sum()) for rr in rooms]
        hits = [rr for rr, f in inside if f >= 0.6]
        if len(hits) != 1: continue
        if any(f >= 0.3 for rr, f in inside if rr is not hits[0]): continue
        for y in out:
            if y[1] is hits[0] and y[0] is not None and (cv2.dilate(y[0], reach) & p).any():
                k = int(kmax * 1.5) | 1
                y[0] = cv2.morphologyEx(y[0] | p, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8)) | y[0] | p
                x[0] = None; break
    return [tuple(x) if x[1] != 'trimmed' else (x[0], None) for x in out if x[0] is not None or x[1] is not None]

# ---------- 3. scale ----------
def thin_ink(g, wall):
    ink = (g < 200).astype(np.uint8)
    return ink & (1 - cv2.dilate(wall, np.ones((3, 3), np.uint8)))

def pin_dim(dm, g, ink, brks, kmax, W, H):
    """Find the drawn dimension line near the model's rough one. Returns (length px, line, break or None)."""
    a = np.array([dm['x1'] / 100 * W, dm['y1'] / 100 * H]); b = np.array([dm['x2'] / 100 * W, dm['y2'] / 100 * H])
    L = np.linalg.norm(b - a)
    if L < 10: return None
    dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
    if min(dx, dy) / max(dx, dy) < 0.4:   # level or plumb
        horiz = dx >= dy
        u = np.array([1., 0.]) if horiz else np.array([0., 1.])
    else:
        u = (b - a) / L
    nrm = np.array([-u[1], u[0]])
    c = (a + b) / 2
    t0, t1 = np.dot(a - c, u), np.dot(b - c, u)
    lo, hi = min(t0, t1) - 0.45 * L - 10, max(t0, t1) + 0.45 * L + 10
    J = int(0.03 * max(W, H)) + 4
    best = None
    for off in range(-J, J + 1):
        ts = np.arange(lo, hi)
        pts = c + np.outer(ts, u) + nrm * off
        xs, ys = np.round(pts[:, 0]).astype(int), np.round(pts[:, 1]).astype(int)
        ok = (xs >= 0) & (xs < W) & (ys >= 0) & (ys < H)
        prof = np.zeros(len(ts), np.uint8); prof[ok] = ink[ys[ok], xs[ok]]
        # runs, joined across gaps up to a third of the line (the printed value sits in the middle)
        d = np.diff(np.concatenate([[0], prof, [0]]).astype(int)); st = list(np.where(d == 1)[0]); en = list(np.where(d == -1)[0])
        if not st: continue
        runs = [[st[0], en[0], en[0] - st[0]]]
        for s, e in zip(st[1:], en[1:]):
            if s - runs[-1][1] <= max(8, 0.34 * L): runs[-1][1] = e; runs[-1][2] += e - s
            else: runs.append([s, e, e - s])
        for s, e, inked in runs:
            span = e - s
            if span < 0.6 * L or span > 1.45 * L or inked < 0.55 * span: continue
            # it overlaps the model's line, and is a line, not a wall face or text: both sides clear
            mid = (s + e) // 2
            side = 0
            for so in (-3, 3):
                q = c + np.outer(ts[s:e], u) + nrm * (off + so)
                qx, qy = np.clip(np.round(q[:, 0]).astype(int), 0, W - 1), np.clip(np.round(q[:, 1]).astype(int), 0, H - 1)
                side += ink[qy, qx].mean()
            if side > 0.5: continue
            pos = abs(off) / J + abs((ts[s] + ts[e - 1]) / 2 - (t0 + t1) / 2) / L
            sc = pos + 0.5 * abs(math.log(span / L))
            if best is None or sc < best[0]: best = (sc, span, (c + u * ts[s] + nrm * off, c + u * ts[e - 1] + nrm * off))
    if not best: return None
    span, (p, q) = best[1], best[2]
    # the break it measures: parallel, close by, the same stretch
    brk = None
    for br in brks:
        ba, bb = np.array(br['a'], float), np.array(br['b'], float)
        bu = (bb - ba) / max(1e-6, np.linalg.norm(bb - ba))
        if abs(np.dot(bu, u)) < 0.97: continue
        dist = abs(np.dot((ba + bb) / 2 - (p + q) / 2, nrm))
        if dist > max(6 * kmax, 0.07 * max(W, H)): continue
        i0, i1 = sorted([np.dot(ba, u), np.dot(bb, u)]); j0, j1 = sorted([np.dot(p, u), np.dot(q, u)])
        ov = max(0, min(i1, j1) - max(i0, j0)) / max(i1, j1) - min(i0, j0) if False else max(0, min(i1, j1) - max(i0, j0)) / (max(i1, j1) - min(i0, j0))
        if ov > 0.8 and (brk is None or dist < brk[0]): brk = (dist, br, i1 - i0 + 1)
    return span, (p, q), brk

def swings(brks, g, W, H):
    """Breaks with a quarter-circle arc at one end: swing doors. Width in px of each."""
    ink = cv2.dilate((g < 190).astype(np.uint8), np.ones((3, 3), np.uint8))
    out = []
    for br in brks:
        a, b = np.array(br['a'], float), np.array(br['b'], float)
        w = np.linalg.norm(b - a)
        if w < 12: continue
        # glass drawn across the gap: a window, not a door
        ts = np.linspace(0.15, 0.85, 30)
        acr = [ink[int(round(y)), int(round(x))] for x, y in (a + t * (b - a) for t in ts) if 0 <= x < W and 0 <= y < H]
        if acr and np.mean(acr) > 0.5: continue
        best = 0
        for hinge, other in ((a, b), (b, a)):
            u = (other - hinge) / w
            for sgn in (-1, 1):
                n = np.array([-u[1], u[0]]) * sgn
                hits = 0; N = 24; inner = 0
                for k in range(3, N - 2):   # the arc's middle, away from the wall and the leaf
                    th = k / N * math.pi / 2
                    dirv = math.cos(th) * u + math.sin(th) * n
                    for rad in np.arange(0.82 * w, 1.12 * w, 1.0):   # the hinge sits on the wall's face, not its middle
                        pt = hinge + rad * dirv
                        x, y = int(round(pt[0])), int(round(pt[1]))
                        if 0 <= x < W and 0 <= y < H and ink[y, x]: hits += 1; break
                    q = hinge + 0.55 * w * dirv; x, y = int(round(q[0])), int(round(q[1]))
                    if 0 <= x < W and 0 <= y < H and ink[y, x]: inner += 1
                if inner <= 0.25 * (N - 5): best = max(best, hits / (N - 5))
        if best >= 0.85: out.append(w)
    return out

def outer_box(wall):
    n, lab, st, _ = cv2.connectedComponentsWithStats(wall, connectivity=8)
    if n < 2: return None
    big = max(range(1, n), key=lambda i: st[i, cv2.CC_STAT_AREA])
    keep = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > 0.05 * st[big, cv2.CC_STAT_AREA]]
    xs0 = min(st[i, 0] for i in keep); ys0 = min(st[i, 1] for i in keep)
    xs1 = max(st[i, 0] + st[i, 2] for i in keep); ys1 = max(st[i, 1] + st[i, 3] for i in keep)
    return xs1 - xs0, ys1 - ys0

def vote(votes):
    """votes: (ppf, weight, source). The cluster (within 4%) with the most weight."""
    if not votes: return None, None, []
    best = None
    for v, _, _ in votes:
        cl = [x for x in votes if abs(x[0] / v - 1) <= 0.04]
        w = sum(x[1] for x in cl)
        if best is None or w > best[0] + 1e-9: best = (w, cl)
    cl = best[1]
    ppf = sum(x[0] * x[1] for x in cl) / sum(x[1] for x in cl)
    srcs = sorted(set(x[2] for x in cl))
    return ppf, srcs, cl

def scale_of(named, model_open, g, wall, brks, kmax, W, H):
    votes = []
    # rooms against their printed sizes
    for piece, r in named:
        if piece is None or r is None or NO_SIZES: continue
        x, y, w, h = cv2.boundingRect(piece)
        fill = piece.sum() / float(w * h)
        if r['w_ft'] and r['l_ft']:
            for pw, ph in ((r['w_ft'], r['l_ft']), (r['l_ft'], r['w_ft'])):
                a, b = w / pw, h / ph
                if abs(a / b - 1) <= 0.06:
                    votes.append(((a + b) / 2, 1.0, 'room sizes'))
            if fill > 0.85 and not any(v[2] == 'room sizes' and v[0] for v in votes[-1:]):
                pass
        elif r['area_ft'] and fill > 0.5:
            votes.append((math.sqrt(piece.sum() / r['area_ft']), 1.0, 'room sizes'))
    # dimension lines
    ink = thin_ink(g, wall)
    pinned = []
    for dm in ([] if DOORS_ONLY else model_open.get('dims') or []):
        ft = dm.get('feet') or parse_ft(dm.get('text'))
        if not ft: continue
        p = pin_dim(dm, g, ink, brks, kmax, W, H)
        if not p: continue
        span, line, brk = p
        pinned.append((dm, span, line, brk))
        wgt = 1.0
        if brk and abs(brk[2] / span - 1) <= 0.06: wgt = 1.5
        votes.append((span / ft, wgt, 'dimension lines'))
    # overall size
    ov = model_open.get('overall') or {}
    ob = outer_box(wall)
    if ob:
        for px_, ft in ((ob[0], ov.get('width_ft')), (ob[1], ov.get('length_ft'))):
            if ft and not DOORS_ONLY: votes.append((px_ / ft, 1.0, 'overall size'))
    ppf, srcs, cl = vote(votes)
    if ppf and (len(cl) >= 2 or len(votes) == 1):
        return ppf, srcs, votes, pinned
    # swing doors: rough, only when nothing else agrees
    sw = swings(brks, g, W, H)
    if len(sw) >= 2:
        votes.append((float(np.median(sw)) / (30 / 12.), 0.5, 'doors (rough)'))
        if not ppf or len(cl) < 2: return votes[-1][0], ['doors (rough)'], votes, pinned
    return ppf, srcs, votes, pinned

# ---------- run ----------
def analyze(name):
    key = json.load(open(os.path.join(D, 'keys', name + '.json')))
    out = json.load(open(os.path.join(D, 'keys', name + '.out.json')))
    for r in out['rooms']:
        kr = [k for k in key['rooms'] if k['name'] == r['name']][0]; r['minor'] = kr.get('minor', False)
    img = cv2.imread(os.path.join(D, 'plans', name + '.jpg')); g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    rooms_js, open_js = mock(name, key, out, img)
    mrooms, mopen = json.loads(rooms_js)['rooms'], json.loads(open_js)
    wall, kmax, k = proto.walls_of(g)
    br = proto.breaks(wall, kmax, False) + proto.breaks(wall, kmax, True)
    sp = proto.spaces(wall, br, kmax, grow=False)
    rooms = []
    for r in mrooms:
        bx = box_px(r, W, H)
        rr = {'name': r['name'], 'bm': box_mask(bx, (H, W)), 'box': bx,
              'w_ft': r.get('width_ft'), 'l_ft': r.get('length_ft'), 'area_ft': r.get('area_sqft') or (r['width_ft'] * r['length_ft'] if r.get('width_ft') and r.get('length_ft') else None)}
        if NO_SIZES: rr['w_ft'] = rr['l_ft'] = rr['area_ft'] = None
        # the space holding most of its box
        ov = [(s & rr['bm']).sum() for s in sp]
        rr['space'] = int(np.argmax(ov)) if ov and max(ov) > 0 else None
        rooms.append(rr)
    named, shared = [], []
    for i, s in enumerate(sp):
        rs = [r for r in rooms if r['space'] == i]
        if len(rs) > 1: shared.append(' + '.join(r['name'] for r in rs))
        if not rs: named.append((s, None)); continue
        named += split(s, rs, kmax, br)
    for r in rooms:
        if r['space'] is None: named.append((None, r))
    named = join_leftovers(named, rooms, kmax)
    ppf, srcs, votes, pinned = scale_of([(p, r) for p, r in named if r], mopen, g, wall, br, kmax, W, H)
    return dict(key=key, out=out, img=img, g=g, H=H, W=W, mrooms=mrooms, mopen=mopen, wall=wall, kmax=kmax, br=br, sp=sp,
                rooms=rooms, named=named, shared=shared, ppf=ppf, srcs=srcs, votes=votes, pinned=pinned)

def run(name):
    A = analyze(name)
    key, out, img, g, H, W, wall, kmax, br, named, shared, ppf, srcs, votes, pinned = [A[k] for k in
        ('key', 'out', 'img', 'g', 'H', 'W', 'wall', 'kmax', 'br', 'named', 'shared', 'ppf', 'srcs', 'votes', 'pinned')]
    # score: the same numbers score.py gives the page
    res = {'plan': name, 'scale': None if not ppf else round(abs(ppf - key['ppf']) / key['ppf'] * 100, 1), 'from': srcs, 'shared': shared}
    ious = []
    vis = img.copy(); vis[wall == 1] = (150, 150, 150)
    cols = [(80, 200, 80), (200, 120, 60), (60, 120, 220), (200, 60, 160), (60, 200, 200), (160, 160, 40), (120, 60, 200), (40, 140, 140)]
    found = {}
    for i, (p, r) in enumerate(named):
        if p is None or r is None: continue
        pm = cv2.dilate(p, np.ones((5, 5), np.uint8))
        found[r['name']] = pm
        col = cols[i % len(cols)]
        ov = vis.copy(); ov[pm == 1] = col; vis = cv2.addWeighted(ov, 0.35, vis, 0.65, 0)
        cs, _ = cv2.findContours(pm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(vis, cs, -1, col, 2)
        M = cv2.moments(pm); cx, cy = int(M['m10'] / M['m00']), int(M['m01'] / M['m00'])
        cv2.putText(vis, r['name'], (cx - 30, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 40, 40), 2)
    for r in out['rooms']:
        if r.get('minor'): continue
        km = poly_mask(r['poly'], (H, W))
        cv2.polylines(vis, [np.array(r['poly'], np.int32)], True, (0, 120, 0), 1)
        ious.append((r['name'], round(float(iou(km, found[r['name']])), 3) if r['name'] in found else 0.0))
    for dm, span, (p, q), brk in pinned:
        cv2.line(vis, tuple(map(int, p)), tuple(map(int, q)), (200, 0, 200), 2)
    for b in br: cv2.line(vis, tuple(map(int, b['a'])), tuple(map(int, b['b'])), (0, 0, 230), 3)
    cv2.imwrite(os.path.join(OUT, name + '.png'), vis)
    fj = {'ppf': ppf, 'from': srcs, 'rooms': []}
    for nm, pm in found.items():
        cs, _ = cv2.findContours(pm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cs, key=cv2.contourArea)
        fj['rooms'].append({'name': nm, 'poly': cv2.approxPolyDP(c, 2.0, True)[:, 0, :].tolist()})
    json.dump(fj, open(os.path.join(OUT, name + '.found.json'), 'w'))
    res['rooms'] = ious
    res['room_avg'] = round(sum(v for _, v in ious) / max(1, len(ious)), 3)
    # breaks at the key's doors, openings and windows (sorting them is session 3)
    def near(kb):
        kc = (np.array(kb['a']) + np.array(kb['b'])) / 2; kw = np.linalg.norm(np.array(kb['a']) - np.array(kb['b']))
        return any(np.linalg.norm((np.array(b['a']) + np.array(b['b'])) / 2 - kc) <= max(1.5 * key['ppf'], kw / 2) for b in br)
    dk = key.get('doors', []) + key.get('openings', []); wk = key.get('windows', [])
    res['doors'] = (sum(map(near, dk)), len(dk)); res['windows'] = (sum(map(near, wk)), len(wk))
    parts = [res['room_avg'], res['doors'][0] / max(1, res['doors'][1]), res['windows'][0] / max(1, res['windows'][1]), max(0, 1 - (res['scale'] if res['scale'] is not None else 100) / 10)]
    res['score'] = round(sum(parts) / len(parts) * 100)
    res['votes'] = [(round(v, 2), w, s) for v, w, s in votes]
    return res

if __name__ == '__main__':
    rows = [run(n) for n in PLANS]
    json.dump(rows, open(os.path.join(OUT, 'scores.json'), 'w'), indent=1)
    for r in rows:
        print('%-9s score %3d | scale off %s%% from %s | rooms %.2f %s' % (r['plan'], r['score'], r['scale'], ', '.join(r['from'] or ['nothing']), r['room_avg'], ' '.join('%s=%.2f' % x for x in r['rooms'])))
        print('          breaks at doors %d/%d, windows %d/%d%s' % (r['doors'] + r['windows'] + (('; split ' + '; '.join(r['shared'])) if r['shared'] else '',)))
        print('          votes ' + ' '.join('%.2f(%s)' % (v, s.split()[0]) for v, w, s in r['votes']))
    print('OVERALL %d' % round(sum(r['score'] for r in rows) / len(rows)))
