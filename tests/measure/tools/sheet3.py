"""Doors and windows before and after: Measure today (score.py's run) beside the session 3 prototype.
python3 sheet3.py <score.py outdir> <proto3 outdir> <out.png>
Green: swing doors (dot at the hinge); dark green: double; purple: sliding or pocket; teal: bifold;
red: opening; blue: window. The key's doors and windows are the thin grey lines underneath."""
import json, os, sys
import numpy as np, cv2
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A, B, OUTP = sys.argv[1:4]
PLANS = ['studio', 'twostory', 'floor2', 'cabin', 'bedroom']
COL = {'swing': (40, 150, 40), 'double': (0, 100, 0), 'window': (220, 120, 0), 'opening': (40, 40, 220), 'sliding': (170, 40, 170),
       'pocket': (170, 40, 170), 'bypass': (170, 40, 170), 'bifold': (0, 160, 200), 'barn': (90, 60, 30)}
FAM = {'bypass': 'sliding', 'pocket': 'sliding', 'barn': 'sliding', 'double': 'swing'}
fam = lambda t: FAM.get(t, t)

def stats(name, items, key):
    ppf = key['ppf']
    def match(keys, fs):
        used, n, ok = set(), 0, 0
        for k in keys:
            kc = (np.array(k['a']) + np.array(k['b'])) / 2; kw = np.linalg.norm(np.array(k['a']) - np.array(k['b']))
            best = None
            for i, f in enumerate(fs):
                if i in used: continue
                c = (np.array(f['a']) + np.array(f['b'])) / 2; d = np.linalg.norm(c - kc)
                if d <= max(1.5 * ppf, kw / 2) and (best is None or d < best[1]): best = (i, d)
            if best: used.add(best[0]); n += 1; ok += fam(fs[best[0]]['kind']) == fam(k['type'])
        return n, ok, len(fs) - len(used)
    kd = key.get('doors', []) + [dict(o, type='opening') for o in key.get('openings', [])]
    d = match(kd, [f for f in items if f['kind'] != 'window'])
    w = match([dict(x, type='window') for x in key.get('windows', [])], [f for f in items if f['kind'] == 'window'])
    return 'doors %d of %d right, windows %d of %d, %d extra' % (d[1], len(kd), w[0], len(key.get('windows', [])), d[2] + w[2])

def panel(name, items, title, key):
    img = cv2.imread(os.path.join(D, 'plans', name + '.jpg'))
    g = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    vis = cv2.addWeighted(g, 0.45, np.full_like(g, 255), 0.55, 0)
    W = vis.shape[1]; lw = max(4, W // 160)
    for k in key.get('doors', []) + key.get('windows', []) + key.get('openings', []):
        cv2.line(vis, tuple(map(int, k['a'])), tuple(map(int, k['b'])), (150, 150, 150), lw + 6)
    for f in items:
        c = COL.get(f['kind'], (0, 0, 0))
        cv2.line(vis, tuple(map(int, f['a'])), tuple(map(int, f['b'])), c, lw)
        if f.get('hinge_pt'): cv2.circle(vis, tuple(map(int, f['hinge_pt'])), lw + 3, c, -1)
        m = ((np.array(f['a']) + np.array(f['b'])) / 2).astype(int)
        cv2.putText(vis, f['kind'], (int(m[0]) + 6, int(m[1]) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1, cv2.LINE_AA)
    head = np.full((58, W, 3), 255, np.uint8)
    cv2.putText(head, title, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 40, 40), 2, cv2.LINE_AA)
    cv2.putText(head, stats(name, items, key), (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (90, 90, 90), 1, cv2.LINE_AA)
    return np.vstack([head, vis])

rows = []
for name in PLANS:
    key = json.load(open(os.path.join(D, 'keys', name + '.json')))
    fa = json.load(open(os.path.join(A, name + '.found.json')))
    ia = []
    for d in fa.get('doors', []):
        ia.append({'kind': d['type'], 'a': d['a'], 'b': d['b']})
    fb = json.load(open(os.path.join(B, name + '.found.json')))
    a = panel(name, ia, name + ': Measure today', key)
    b = panel(name, fb['openings'], name + ': session 3', key)
    row = np.hstack([a, np.full((a.shape[0], 16, 3), 255, np.uint8), b])
    s = 1400 / row.shape[1]
    rows.append(cv2.resize(row, None, fx=s, fy=s, interpolation=cv2.INTER_AREA))
cv2.imwrite(OUTP, np.vstack([np.vstack([r, np.full((20, r.shape[1], 3), 255, np.uint8)]) for r in rows]))
