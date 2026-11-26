"""Prototype of the wall-first Measure (Python, to try ideas fast; the page version comes after).
python3 proto.py [plan ...]
1. Walls: the same dark-ink test the page uses (a k x k box of ink), then grown back to the wall's
   real edges.
2. Breaks: in every row and column, a wall, a gap, a wall: stacked rows make one break. Limits are in
   wall thicknesses, not feet, so this works before the scale is known.
3. Spaces: every break closed with a line; each enclosed area not touching the picture's edge is a space.
4. Scale: each labeled space's size against its printed size, voted.
Writes proto/<plan>.png (walls grey, breaks colored, spaces outlined) and prints how the spaces line
up with the answer key."""
import json, os, sys, re
import numpy as np, cv2

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(D, 'proto'); os.makedirs(OUT, exist_ok=True)
PLANS = (sys.argv[1:] if __name__ == '__main__' else []) or ['bedroom', 'studio', 'cabin', 'twostory', 'floor2']

def walls_of(g):
    dark = (g < 110).astype(np.uint8)
    # wall thickness: the most common run of ink 4px and longer, across rows and columns (walls are
    # long and all the same thickness; text and fixtures are thinner, a solid block is rare)
    from collections import Counter
    c = Counter()
    for m in (dark, dark.T):
        for row in m:
            d = np.diff(np.concatenate([[0], row, [0]]).astype(int)); st = np.where(d == 1)[0]; en = np.where(d == -1)[0]
            for L in (en - st):
                if L >= 4: c[int(L)] += 1
    kmax = c.most_common(1)[0][0]
    k = max(3, int(round(kmax * 0.35)))
    core = cv2.erode(dark, np.ones((k, k), np.uint8))
    full = cv2.dilate(core, np.ones((k, k), np.uint8)) & dark   # back out to the wall's edges
    return full, kmax, k

def breaks(wall, kmax, vertical):
    m = wall.T if vertical else wall
    H, W = m.shape
    lo, hi = max(4, int(kmax * 1.2)), int(kmax * 45)
    found, open_ = [], []
    for v in range(H):
        row = m[v]
        d = np.diff(np.concatenate([[0], row, [0]]).astype(int))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0] - 1
        nxt = []
        for i in range(len(starts) - 1):
            x1, x2 = ends[i], starts[i + 1]
            gap = x2 - x1 - 1
            if gap < lo or gap > hi: continue
            # the walls each side run along the scan line (a wall broken by a door), not across it
            # (two walls seen side by side): the longer flank at least two wall thicknesses
            f1, f2 = ends[i] - starts[i] + 1, ends[i + 1] - starts[i + 1] + 1
            # a gap between two short ends (the ends of walls meeting the scan line) is only a door
            # when it's door-sized: a closet's bifold yes, the length of a room no
            if max(f1, f2) < 2 * kmax and gap > 10 * kmax: continue
            hit = None
            for o in open_:
                if abs(o['x1'] - x1) <= 2 and abs(o['x2'] - x2) <= 2: hit = o; break
            if hit: open_.remove(hit); hit['v1'] = v; nxt.append(hit)
            else: nxt.append({'x1': x1, 'x2': x2, 'v0': v, 'v1': v})
        for o in open_: found.append(o)
        open_ = nxt
    found += open_
    out = []
    for o in found:
        depth = o['v1'] - o['v0'] + 1
        # as deep as a wall (not a sliver, not a whole room), with open floor past both faces
        if depth < max(2, kmax * 0.3) or depth > kmax * 2.2: continue
        u0, u1, vm = o['x1'] + 1, o['x2'] - 1, (o['v0'] + o['v1']) // 2
        a, b = (u0, vm), (u1, vm)
        if vertical: a, b = (vm, u0), (vm, u1)
        # floor past both faces: the middle of the gap, a wall thickness out each way, isn't wall
        um = (u0 + u1) // 2
        ok = True
        for side in (-1, 1):
            vv = (o['v0'] - kmax) if side < 0 else (o['v1'] + kmax)
            if 0 <= vv < H and m[vv, um]: ok = False   # off the picture counts as open
        # the walls each side of the gap run along it and end at the gap: a wall crossing the scan
        # line (two walls across a room, seen side by side) carries on past the band both ways
        for fu in (o['x1'], o['x2']):
            above = o['v0'] - 2 >= 0 and m[o['v0'] - 2, fu]
            below = o['v1'] + 2 < H and m[o['v1'] + 2, fu]
            if above and below: ok = False
        if not ok: continue
        # nothing crossing it: the gap row itself has no wall
        out.append({'a': a, 'b': b, 'w': u1 - u0 + 1, 'depth': depth, 'v': vertical})
    return out

def spaces(wall, brks, kmax, grow=True):
    H, W = wall.shape
    # small holes in the walls (a corner post drawn as an open square) are closed first
    kc = int(round(kmax * 1.3)) | 1
    block = cv2.morphologyEx(wall, cv2.MORPH_CLOSE, np.ones((kc, kc), np.uint8))
    for b in brks:
        cv2.line(block, (int(b['a'][0]), int(b['a'][1])), (int(b['b'][0]), int(b['b'][1])), 1, max(2, kmax // 2))
    # seal slivers up to 4px between walls (where a corner post meets two walls); grown back after
    block = cv2.dilate(block, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats((1 - block).astype(np.uint8), connectivity=4)
    # the outside: what the picture's edge reaches with every hole up to 2.5 wall thicknesses shut
    kb = int(round(kmax * 2.5)) | 1
    big = cv2.morphologyEx(block, cv2.MORPH_CLOSE, np.ones((kb, kb), np.uint8))
    m2 = np.zeros((H + 2, W + 2), np.uint8); outside = (1 - big).astype(np.uint8).copy()
    for x, y in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]:
        if outside[y, x] == 1: cv2.floodFill(outside, m2, (x, y), 2)
    outside = (outside == 2)
    out = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < (kmax * 3) ** 2: continue
        reg = (lab == i)
        if (reg & outside).sum() > 0.5 * reg.sum(): continue
        out.append(cv2.dilate(reg.astype(np.uint8), np.ones((5, 5), np.uint8)) if grow else reg.astype(np.uint8))
    return out

def main():
    rows = []
    for name in PLANS:
        key = json.load(open(os.path.join(D, 'keys', name + '.json')))
        out = json.load(open(os.path.join(D, 'keys', name + '.out.json')))
        img = cv2.imread(os.path.join(D, 'plans', name + '.jpg')); g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        wall, kmax, k = walls_of(g)
        br = breaks(wall, kmax, False) + breaks(wall, kmax, True)
        sp = spaces(wall, br, kmax)
        H, W = g.shape
        # each key room: the space that covers most of it
        res, used = [], {}
        for r in out['rooms']:
            kr = [x for x in key['rooms'] if x['name'] == r['name']][0]
            km = np.zeros((H, W), np.uint8); cv2.fillPoly(km, [np.array(r['poly'], np.int32)], 1)
            best = max(range(len(sp)), key=lambda i: (sp[i] & km).sum()) if sp else None
            if best is None or (sp[best] & km).sum() == 0: res.append((r['name'], 0, None, kr.get('minor'))); continue
            used.setdefault(best, []).append(r['name'])
            iou = (sp[best] & km).sum() / (sp[best] | km).sum()
            res.append((r['name'], round(float(iou), 2), best, kr.get('minor')))
        # breaks vs the key's doors, windows and openings
        keyb = key.get('doors', []) + key.get('windows', []) + key.get('openings', [])
        hit = 0
        for kb in keyb:
            kc = (np.array(kb['a']) + np.array(kb['b'])) / 2
            if any(np.linalg.norm((np.array(b['a']) + np.array(b['b'])) / 2 - kc) < max(15, 0.6 * np.linalg.norm(np.array(kb['a']) - np.array(kb['b']))) for b in br): hit += 1
        extra = sum(1 for b in br if not any(np.linalg.norm((np.array(b['a']) + np.array(b['b'])) / 2 - (np.array(kb['a']) + np.array(kb['b'])) / 2) < max(15, 0.6 * np.linalg.norm(np.array(kb['a']) - np.array(kb['b']))) for kb in keyb))
        vis = img.copy()
        vis[wall == 1] = (150, 150, 150)
        cols = [(80, 200, 80), (200, 120, 60), (60, 120, 220), (200, 60, 160), (60, 200, 200), (160, 160, 40), (120, 60, 200), (40, 140, 140), (220, 160, 120), (120, 200, 120)]
        for i, s in enumerate(sp):
            cs, _ = cv2.findContours(s, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            ov = vis.copy(); ov[s == 1] = cols[i % len(cols)]; vis = cv2.addWeighted(ov, 0.35, vis, 0.65, 0)
            cv2.drawContours(vis, cs, -1, cols[i % len(cols)], 2)
        for b in br: cv2.line(vis, tuple(map(int, b['a'])), tuple(map(int, b['b'])), (0, 0, 230), 3)
        cv2.imwrite(os.path.join(OUT, name + '.png'), vis)
        major = [x for x in res if not x[3]]
        merged = {i: n for i, n in used.items() if len(n) > 1}
        rows.append((name, kmax, len(br), hit, len(keyb), extra, major, merged, len(sp)))
        print('%-9s wall %2dpx | breaks %d (key %d/%d found, %d extra) | spaces %d' % (name, kmax, len(br), hit, len(keyb), extra, len(sp)))
        print('          rooms ' + ' '.join('%s=%.2f' % (n, v) for n, v, _, m in major))
        if merged: print('          shared spaces: ' + '; '.join(' + '.join(v) for v in merged.values()))

if __name__ == '__main__': main()
