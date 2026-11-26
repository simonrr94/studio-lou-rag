"""Measure session 3 prototype: what each break in the walls is.
python3 proto3.py [plan ...]

Builds on proto2.py (spaces, names, scale). Each break found in the walls is:
1. Cut apart where a line crosses the wall (a jamb or window frame end) or where glass lines start or
   stop, so a glass wall beside a door comes apart into windows and the door.
2. Read from the drawing:
   - a quarter-circle arc the width of the gap from one end: a swing door, with its hinge and the room
     it opens into; two half-width arcs from both ends: a double door
   - two or more lines along the gap: glass. In an outside wall a window; between rooms a sliding door
   - one line, or short panels side by side, across a gap between rooms: a sliding door (a pocket door
     when 40" or less and one panel)
   - lines folding out from the wall a short way (not a full arc): a bifold
   - nothing: an opening
3. The model's list settles what the drawing can't: a plain gap the model calls a window, panels the
   model calls bifold, pocket, barn or sliding, a swing the model calls double. Each model item goes to
   the nearest break within 4 ft.
Scores doors (found, right kind), swing doors (hinge and room it opens into) and windows the way
score.py scores the page. Writes proto3/<plan>.png and proto3/<plan>.found.json."""
import json, os, sys, math
import numpy as np, cv2
_args = sys.argv[1:]; sys.argv = sys.argv[:1] + [a for a in _args if a.startswith('--seed=')]   # rough boxes passed on to proto2
import proto2
from score import poly_mask

D = proto2.D
PLANS = [a for a in _args if not a.startswith('--')] or ['bedroom', 'studio', 'cabin', 'twostory', 'floor2']
NO_MODEL = '--no-model' in _args
OUT = os.path.join(D, 'proto3' + ('-nomodel' if NO_MODEL else '')); os.makedirs(OUT, exist_ok=True)
FAM = {'bypass': 'sliding', 'pocket': 'sliding', 'barn': 'sliding', 'double': 'swing'}
fam = lambda t: FAM.get(t, t)

class Frame:
    """A break's own frame: t along it (0 at a, 1 at b), s across it in px (+ toward n)."""
    def __init__(self, br):
        self.a, self.b = np.array(br['a'], float), np.array(br['b'], float)
        self.w = np.linalg.norm(self.b - self.a)
        self.u = (self.b - self.a) / max(1e-6, self.w)
        self.n = np.array([-self.u[1], self.u[0]])
        self.depth = br['depth']
    def pt(self, t, s): return self.a + self.u * t * self.w + self.n * s
    def at(self, m, t, s):
        p = self.pt(t, s); x, y = int(round(p[0])), int(round(p[1]))
        return m[y, x] if 0 <= y < m.shape[0] and 0 <= x < m.shape[1] else 0

def band_rows(F, ink, h, ts):
    """For each offset s across the wall band, how much of the gap's length is inked."""
    out = []
    for s in range(-h, h + 1):
        out.append(np.mean([F.at(ink, t, s) for t in ts]))
    return np.array(out)

def cuts_of(F, ink, h, kmax):
    """Where to cut a break: lines crossing the wall, and where the glass pattern changes."""
    N = int(F.w)
    if N < 4 * kmax: return []
    ss = list(range(-h, h + 1))
    cross = np.array([np.mean([F.at(ink, i / N, s) for s in ss]) for i in range(N + 1)])
    lines = []
    for i in range(N + 1):
        col = [F.at(ink, i / N, s) for s in ss]
        # separate lines along the gap at this spot
        lines.append(min(2, sum(1 for j in range(len(col)) if col[j] and (j == 0 or not col[j - 1]))))
    lines = np.array(lines)
    L0 = max(int(1.5 * kmax), 10)
    cut = []
    # glass (2+ lines) starting or stopping, held for a while each side
    gl = (lines >= 2).astype(int)
    k = L0
    for i in range(L0, N - L0):
        if gl[i] != gl[i - 1]:
            before, after = gl[max(0, i - k):i].mean(), gl[i:i + k].mean()
            if abs(before - after) > 0.8 and not any(abs(c - i / N) * N < L0 for c in cut): cut.append(i / N)
    return sorted(cut)

def split_breaks(brs, ink, kmax, outside_wall=lambda F, h, kmax: True):
    out = []
    for br in brs:
        F = Frame(br)
        h = max(2, int(br['depth'] / 2))
        cs = cuts_of(F, ink, h, kmax) if outside_wall(F, h, kmax) else []
        edges = [0] + cs + [1]
        for t0, t1 in zip(edges[:-1], edges[1:]):
            a, b = F.pt(t0, 0), F.pt(t1, 0)
            # step off the crossing line itself
            pad = 2 / max(1, F.w)
            if t0 > 0: a = F.pt(t0 + pad, 0)
            if t1 < 1: b = F.pt(t1 - pad, 0)
            out.append(dict(br, a=(a[0], a[1]), b=(b[0], b[1]), w=np.linalg.norm(b - a)))
    return out

def arc_score(F, ink, hinge_t, side, radius, sweep_from_wall=True):
    """How much of a quarter circle of this radius from the hinge (t = 0 or 1) is inked."""
    hinge = F.pt(hinge_t, 0)
    u = F.u if hinge_t == 0 else -F.u
    n = F.n * side
    hits, inner, N = 0, 0, 24
    for k in range(3, N - 2):
        th = k / N * math.pi / 2
        d = math.cos(th) * u + math.sin(th) * n
        ok = False
        for rad in np.arange(0.82 * radius, 1.12 * radius + 1, 1.0):
            p = hinge + rad * d; x, y = int(round(p[0])), int(round(p[1]))
            if 0 <= y < ink.shape[0] and 0 <= x < ink.shape[1] and ink[y, x]: ok = True; break
        hits += ok
        p = hinge + 0.55 * radius * d; x, y = int(round(p[0])), int(round(p[1]))
        if 0 <= y < ink.shape[0] and 0 <= x < ink.shape[1] and ink[y, x]: inner += 1
    if inner > 0.25 * (N - 5): return 0
    return hits / (N - 5)

def leaf_score(F, ink, hinge_t, side, h):
    """A door leaf drawn as a straight line from the hinge into the room, at any angle."""
    u = F.u if hinge_t == 0 else -F.u
    n = F.n * side
    hinge = F.pt(hinge_t, 0) + n * h      # on the wall's face
    best = 0
    for ang in range(15, 91, 3):
        th = math.radians(ang); d = math.cos(th) * u + math.sin(th) * n
        pts = [hinge + d * r for r in np.linspace(0.15 * F.w, 0.9 * F.w, 20)]
        hit = np.mean([ink[int(round(q[1])), int(round(q[0]))] if 0 <= round(q[1]) < ink.shape[0] and 0 <= round(q[0]) < ink.shape[1] else 0 for q in pts])
        if hit < 0.9: continue
        # and the arc its far end swept, from the leaf back down to the other jamb
        arc = []
        for a2 in np.linspace(3, ang - 3, max(4, int(ang / 4))):
            t2 = math.radians(a2); d2 = math.cos(t2) * u + math.sin(t2) * n; ok = 0
            for rad in np.arange(0.85 * F.w, 1.12 * F.w, 1.0):
                q = hinge + d2 * rad; x, y = int(round(q[0])), int(round(q[1]))
                if 0 <= y < ink.shape[0] and 0 <= x < ink.shape[1] and ink[y, x]: ok = 1; break
            arc.append(ok)
        if np.mean(arc) >= 0.7: best = max(best, hit)
    return best

def off_wall(F, ink, side, h, depth):
    """Ink just off the wall face on one side, out to depth: folding leaves, a sliding panel's track."""
    c = 0; n = 0
    for t in np.linspace(0.05, 0.95, 30):
        for s in range(h + 2, h + 2 + int(depth)):
            n += 1; c += F.at(ink, t, s * side)
    return c / max(1, n)

def read_break(br, ink, inkd, h, kmax, ppf, inside, gray):
    F = Frame(br)
    w = F.w
    ts = np.linspace(0.12, 0.88, 40)
    rows = band_rows(F, ink, h, ts)
    span = [r >= 0.7 for r in rows]
    nspan = sum(1 for j in range(len(span)) if span[j] and (j == 0 or not span[j - 1]))
    jbest = int(np.argmax(rows)) - h
    gl = [F.at(gray, t, jbest) for t in ts]
    inked = [v for v in gl if v < 200]
    r_dark = bool(inked) and float(np.mean(inked)) < 140
    part = sum(1 for j in range(len(rows)) if 0.25 <= rows[j] < 0.7 and (j == 0 or not (0.25 <= rows[j - 1] < 0.7)))
    # outside on either side?
    probe = max(2 * kmax, int(0.4 * w))
    outs = [not inside(F.pt(0.5, side * (h + probe))) for side in (1, -1)]
    exterior = any(outs)
    r = {'w': w, 'exterior': exterior, 'outs': outs, 'nspan': nspan, 'part': part, 'dark': r_dark}
    best = (0, None, None)
    for ht in (0, 1):
        for side in (1, -1):
            sc = arc_score(F, inkd, ht, side, w)
            lf = leaf_score(F, inkd, ht, side, h)
            v = sc if sc >= 0.85 else (0.85 if lf >= 0.9 else sc * 0.9)
            if v > best[0]: best = (v, ht, side)
    r.update(arc=best[0], hinge=best[1], side=best[2])
    if nspan >= 2 and not (best[0] >= 0.85 and not exterior):
        # glass: in an outside wall a window, an arc there is furniture or a sill
        r.update(kind='window' if exterior else 'sliding'); return r
    if best[0] >= 0.85:
        r.update(kind='swing'); return r
    for side in (1, -1):
        if min(arc_score(F, inkd, 0, side, w / 2), arc_score(F, inkd, 1, side, w / 2)) >= 0.8:
            r.update(kind='double', side=side); return r
    fold = max(off_wall(F, ink, 1, h, 0.35 * w), off_wall(F, ink, -1, h, 0.35 * w))
    r['fold'] = fold
    if nspan == 1 or part >= 1:
        if exterior and nspan == 1:
            r.update(kind='window'); return r   # a single glass line in an outside wall
        inches = w / ppf * 12 if ppf else None
        r.update(kind='pocket' if (inches and inches <= 40 and part == 0) else 'sliding'); return r
    if fold >= 0.04:
        r.update(kind='bifold'); return r
    r.update(kind='opening'); return r

def settle(found, mopen, W, H, ppf):
    """The model's list settles what the drawing can't."""
    reach = 4 * ppf if ppf else 0.06 * max(W, H)
    used = set()
    items = []
    for o in mopen.get('openings', []):
        c = np.array([o['x'] / 100 * W, o['y'] / 100 * H])
        best = None
        for i, f in enumerate(found):
            d = np.linalg.norm(np.array(f['c']) - c)
            if d <= reach and i not in used and (best is None or d < best[1]): best = (i, d)
        if best: used.add(best[0]); items.append((found[best[0]], o))
    for f, o in items:
        mk = 'window' if o['kind'] == 'window' else 'opening' if o['kind'] == 'opening' else (o.get('type') or 'swing')
        f['model'] = mk
        k = f['kind']
        if k == 'opening' and mk == 'window': f['kind'] = 'window'
        elif k == 'opening' and mk in ('bifold', 'sliding', 'pocket', 'barn', 'double'): f['kind'] = mk
        elif k in ('sliding', 'pocket') and mk in ('bifold', 'sliding', 'pocket', 'barn', 'double'): f['kind'] = mk
        elif k in ('sliding', 'pocket') and mk == 'opening' and not f['dark']: f['kind'] = 'opening'   # a faint threshold line
        elif k == 'bifold' and mk in ('sliding', 'pocket', 'barn', 'opening', 'double'): f['kind'] = mk
        elif k == 'swing' and mk == 'double': f['kind'] = 'double'
        elif k == 'swing' and ppf and f['w'] / ppf * 12 > 42 and mk in ('bifold', 'sliding', 'pocket', 'barn', 'double', 'opening'): f['kind'] = mk
        elif k == 'window' and mk == 'swing' and f.get('arc', 0) >= 0.85: f['kind'] = 'swing'
        elif k == 'double' and mk in ('bifold', 'opening', 'sliding', 'pocket', 'barn'): f['kind'] = mk
        elif k == 'window' and mk in ('sliding', 'bifold', 'opening') and f['exterior'] and f['nspan'] < 2: f['kind'] = mk
        elif k == 'window' and mk in ('sliding',) and not f['exterior']: f['kind'] = 'sliding'
    return found

def flank(br, wall):
    """How far the wall runs on in line with the break, past its shorter end."""
    F = Frame(br); runs = []
    for t0, sgn in ((0, -1), (1, 1)):
        p0 = F.pt(t0, 0); k = 0
        for k in range(2, 400):
            q = p0 + F.u * sgn * k; x, y = int(round(q[0])), int(round(q[1]))
            if not (0 <= y < wall.shape[0] and 0 <= x < wall.shape[1]) or not wall[y, x]: break
        runs.append(k)
    return min(runs)

def dedupe(brs, wall, kmax):
    """Two breaks side by side in one wall (a gap read once in the wall and once just inside it):
    keep the one the wall runs on from."""
    keep = [True] * len(brs)
    for i in range(len(brs)):
        for j in range(i + 1, len(brs)):
            A, B = Frame(brs[i]), Frame(brs[j])
            if abs(np.dot(A.u, B.u)) < 0.97: continue
            if abs(np.dot(B.pt(0.5, 0) - A.pt(0.5, 0), A.n)) > 2 * kmax: continue
            a0, a1 = sorted([np.dot(A.a, A.u), np.dot(A.b, A.u)]); b0, b1 = sorted([np.dot(B.a, A.u), np.dot(B.b, A.u)])
            if max(0, min(a1, b1) - max(a0, b0)) < 0.5 * min(a1 - a0, b1 - b0): continue
            if flank(brs[i], wall) >= flank(brs[j], wall): keep[j] = False
            else: keep[i] = False
    return [b for b, k in zip(brs, keep) if k]

def analyze3(name):
    A = proto2.analyze(name)
    if NO_MODEL: A['mopen'] = dict(A['mopen'], openings=[])   # the doors call failed: the drawing alone
    g, wall, kmax, H, W, ppf = A['g'], A['wall'], A['kmax'], A['H'], A['W'], A['ppf']
    ink = ((g < 200).astype(np.uint8)) & (1 - wall)
    inkd = cv2.dilate((g < 190).astype(np.uint8), np.ones((3, 3), np.uint8))
    spaces = np.zeros((H, W), np.uint8)
    for s in A['sp']: spaces |= s
    spaces = cv2.dilate(spaces, np.ones((5, 5), np.uint8))
    def inside(p):
        x, y = int(round(p[0])), int(round(p[1]))
        return 0 <= y < H and 0 <= x < W and spaces[y, x]
    def outside_wall(F, h, kmax):
        return any(not inside(F.pt(0.5, sg * (h + max(2 * kmax, 0.3 * F.w)))) for sg in (1, -1))
    brs = split_breaks(dedupe(A['br'], wall, kmax), ink, kmax, outside_wall)
    found = []
    for br in brs:
        if np.linalg.norm(np.array(br['b']) - np.array(br['a'])) < max(6, kmax): continue
        h = max(2, int(br['depth'] / 2))
        r = read_break(br, ink, inkd, h, kmax, ppf, inside, g)
        F = Frame(br)
        r.update(a=list(map(float, F.a)), b=list(map(float, F.b)), c=list(map(float, F.pt(0.5, 0))))
        # the room a swing door opens into
        if r['kind'] in ('swing', 'double'):
            p = F.pt(0.5, r['side'] * (h + 0.5 * F.w))
            r['hinge_pt'] = list(map(float, F.pt(r['hinge'], 0))) if r['kind'] == 'swing' else None
            r['into'] = None
            for piece, room in A['named']:
                if piece is not None and room is not None and piece[int(p[1]) if 0 <= p[1] < H else 0, int(p[0]) if 0 <= p[0] < W else 0]:
                    r['into'] = room['name']
        # the rooms each side
        sides = []
        for sgn in (1, -1):
            q = F.pt(0.5, sgn * (h + max(2 * kmax, 0.3 * F.w))); nm = None
            for piece, room in A['named']:
                if piece is not None and room is not None and 0 <= q[1] < H and 0 <= q[0] < W and piece[int(q[1]), int(q[0])]: nm = room['name']
            sides.append(nm)
        r['rooms'] = sides
        found.append(r)
    settle(found, A['mopen'], W, H, ppf)
    # with the model's list in hand, a weak read it doesn't list is dropped (a wall notch, a drawn fixture);
    # with no list (the call failed), the drawing alone decides
    if A['mopen'].get('openings'):
        found = [f for f in found if f.get('model') or f['kind'] in ('swing', 'window') or (f['kind'] in ('sliding', 'pocket') and f['dark'])]
    for f in found:
        if f['kind'] == 'swing' and ppf and f['w'] / ppf * 12 > 42 and not f.get('model'): f['kind'] = 'double'
    # a gap with the same room on both sides is part of the drawing inside the room (a tub edge), not a way through
    found = [f for f in found if not (f['rooms'][0] and f['rooms'][0] == f['rooms'][1] and not f.get('model'))]
    A['found'] = found
    return A

def score3(A, name):
    key, found, img = A['key'], A['found'], A['img']
    ppf_true = key['ppf']
    def match(keys, fs, tol_ft=1.5):
        used, hits = set(), []
        for k in keys:
            kc = (np.array(k['a']) + np.array(k['b'])) / 2; kw = np.linalg.norm(np.array(k['a']) - np.array(k['b']))
            best = None
            for i, f in enumerate(fs):
                if i in used: continue
                d = np.linalg.norm(np.array(f['c']) - kc)
                if d <= max(tol_ft * ppf_true, kw / 2) and (best is None or d < best[1]): best = (i, d)
            if best: used.add(best[0]); hits.append((k, fs[best[0]]))
            else: hits.append((k, None))
        return hits, len(fs) - len(used)
    fd = [f for f in found if f['kind'] != 'window']
    fw = [f for f in found if f['kind'] == 'window']
    keyd = key.get('doors', []) + [dict(o, type='opening') for o in key.get('openings', [])]
    dh, dfp = match(keyd, fd)
    wh, wfp = match(key.get('windows', []), fw)
    res = {'plan': name}
    res['doors'] = (sum(1 for k, f in dh if f), len(dh), sum(1 for k, f in dh if f and fam(f['kind']) == fam(k['type'])), dfp)
    res['wrong'] = ['%s as %s' % (k['type'], f['kind']) for k, f in dh if f and fam(f['kind']) != fam(k['type'])]
    res['missed'] = ['%s@%d,%d' % ((k['type'],) + tuple(((np.array(k['a']) + np.array(k['b'])) / 2).astype(int))) for k, f in dh if not f]
    res['windows'] = (sum(1 for k, f in wh if f), len(wh), wfp)
    # swing doors: hinge end and the room they open into
    # (a room the model didn't list, like a closet, can't be named: not counted against the swing)
    names = set(r['name'].lower() for r in A['mrooms'])
    listed = lambda nm: (nm or '').lower() in names
    sw = [(k, f) for k, f in dh if f and k['type'] == 'swing' and f['kind'] == 'swing']
    hinge_ok = into_ok = 0
    for k, f in sw:
        kh = np.array(k['a'] if k.get('hinge') == 'a' else k['b'])
        other = np.array(k['b'] if k.get('hinge') == 'a' else k['a'])
        if np.linalg.norm(np.array(f['hinge_pt']) - kh) < np.linalg.norm(np.array(f['hinge_pt']) - other): hinge_ok += 1
        if (f.get('into') or '').lower() == (k.get('into') or '').lower() or not listed(k.get('into')): into_ok += 1
    res['swings'] = (len(sw), hinge_ok, into_ok)
    res['bad_swing'] = []
    for k, f in sw:
        kh = np.array(k['a'] if k.get('hinge') == 'a' else k['b'])
        if (f.get('into') or '').lower() != (k.get('into') or '').lower() and listed(k.get('into')): res['bad_swing'].append('into %s not %s' % (f.get('into'), k.get('into')))
    # the page's score, now with kinds: doors count only when the kind is right
    ious = []
    for r in A['out']['rooms']:
        if any(x.get('minor') and x['name'] == r['name'] for x in key['rooms']): continue
        km = poly_mask(r['poly'], (A['H'], A['W']))
        f = [p for p, rr in A['named'] if p is not None and rr is not None and rr['name'] == r['name']]
        if not f: ious.append(0.0); continue
        fm = cv2.dilate(f[0], np.ones((5, 5), np.uint8))
        ious.append(float((km & fm).sum() / (km | fm).sum()))
    res['room_avg'] = sum(ious) / max(1, len(ious))
    res['scale'] = None if not A['ppf'] else abs(A['ppf'] - ppf_true) / ppf_true * 100
    parts = [res['room_avg'], res['doors'][2] / max(1, res['doors'][1]), res['windows'][0] / max(1, res['windows'][1]),
             max(0, 1 - (res['scale'] if res['scale'] is not None else 100) / 10)]
    res['score'] = round(sum(parts) / len(parts) * 100)
    # picture
    vis = img.copy()
    colk = {'swing': (0, 140, 0), 'double': (0, 100, 0), 'window': (220, 120, 0), 'opening': (0, 0, 220), 'sliding': (180, 0, 180),
            'pocket': (120, 0, 200), 'bifold': (0, 160, 200), 'barn': (90, 60, 30)}
    for f in found:
        cv2.line(vis, tuple(map(int, f['a'])), tuple(map(int, f['b'])), colk.get(f['kind'], (0, 0, 0)), 4)
        cv2.putText(vis, f['kind'][:3], (int(f['c'][0]) + 4, int(f['c'][1]) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, colk.get(f['kind'], (0, 0, 0)), 1, cv2.LINE_AA)
        if f.get('hinge_pt'): cv2.circle(vis, tuple(map(int, f['hinge_pt'])), 5, (0, 140, 0), -1)
    cv2.imwrite(os.path.join(OUT, name + '.png'), vis)
    json.dump({'ppf': A['ppf'], 'from': A['srcs'], 'openings': [{k: v for k, v in f.items() if k in ('kind', 'a', 'b', 'into', 'hinge_pt', 'model')} for f in found]},
              open(os.path.join(OUT, name + '.found.json'), 'w'))
    return res

if __name__ == '__main__':
    rows = []
    for n in PLANS:
        A = analyze3(n); rows.append(score3(A, n))
    for r in rows:
        print('%-9s score %3d | doors %d/%d found, %d right kind, %d extra | windows %d/%d, %d extra | swings %d: hinge %d, into %d' % (
            (r['plan'], r['score']) + r['doors'] + r['windows'] + r['swings']))
        if r['wrong'] or r['missed'] or r['bad_swing']:
            print('          ' + '; '.join(x for x in [('wrong: ' + ', '.join(r['wrong'])) if r['wrong'] else '', ('missed: ' + ', '.join(r['missed'])) if r['missed'] else '',
                                                        ('swings: ' + ', '.join(r['bad_swing'])) if r['bad_swing'] else ''] if x))
    print('OVERALL %d' % round(sum(r['score'] for r in rows) / len(rows)))
