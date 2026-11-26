"""Before and after pictures: Measure today (score.py's run) beside the session 2 prototype.
python3 sheet.py <score.py outdir> <proto2 outdir> <out.png>
Each room is filled in its own color and tagged with its name and how well it matches the answer
key (1.00 is exact); the key's outlines are the thin dark lines."""
import json, os, sys
import numpy as np, cv2
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A, B, OUTP = sys.argv[1:4]
PLANS = ['studio', 'twostory', 'floor2', 'cabin', 'bedroom']
COLS = [(120, 190, 120), (90, 150, 220), (200, 140, 90), (180, 120, 200), (90, 200, 200), (200, 200, 110), (150, 110, 230), (110, 170, 170)]

def panel(name, found, title, keyppf):
    img = cv2.imread(os.path.join(D, 'plans', name + '.jpg'))
    g = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    vis = cv2.addWeighted(g, 0.55, np.full_like(g, 255), 0.45, 0)
    H, W = g.shape[:2]
    out = json.load(open(os.path.join(D, 'keys', name + '.out.json')))
    key = json.load(open(os.path.join(D, 'keys', name + '.json')))
    major = [r for r in out['rooms'] if not any(k.get('minor') and k['name'] == r['name'] for k in key['rooms'])]
    tags = []
    for i, r in enumerate(major):
        km = np.zeros((H, W), np.uint8); cv2.fillPoly(km, [np.array(r['poly'], np.int32)], 1)
        f = [x for x in found['rooms'] if x['name'].lower() == r['name'].lower() and x.get('poly')]
        col = COLS[i % len(COLS)]
        v = 0.0
        if f:
            fm = np.zeros((H, W), np.uint8); cv2.fillPoly(fm, [np.array(f[0]['poly'], np.int32)], 1)
            v = (km & fm).sum() / max(1, (km | fm).sum())
            ov = vis.copy(); ov[fm == 1] = col; vis = cv2.addWeighted(ov, 0.45, vis, 0.55, 0)
            cv2.polylines(vis, [np.array(f[0]['poly'], np.int32)], True, tuple(int(c * 0.6) for c in col), 3)
        tags.append((r, v, col))
    for r, v, col in tags:
        cv2.polylines(vis, [np.array(r['poly'], np.int32)], True, (60, 60, 60), 1)
    for r, v, col in tags:
        p = np.array(r['poly']); cx, cy = p.mean(0).astype(int)
        t = '%s %.2f' % (r['name'], v)
        (tw, th), _ = cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(vis, (cx - tw // 2 - 4, cy - th - 4), (cx + tw // 2 + 4, cy + 5), (255, 255, 255), -1)
        cv2.putText(vis, t, (cx - tw // 2, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 40, 140) if v < 0.85 else (40, 90, 40), 1, cv2.LINE_AA)
    ppf = 1 / found['ftPerPx'] if found.get('ftPerPx') else found.get('ppf')
    sc = 'no scale found' if not ppf else 'scale %.1f%% off%s' % (abs(ppf - keyppf) / keyppf * 100, (' (' + ', '.join(found['from']) + ')') if isinstance(found.get('from'), list) else '')
    avg = sum(v for _, v, _ in tags) / max(1, len(tags))
    head = np.full((58, W, 3), 255, np.uint8)
    cv2.putText(head, title, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 40, 40), 2, cv2.LINE_AA)
    cv2.putText(head, 'rooms %.2f, %s' % (avg, sc), (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (90, 90, 90), 1, cv2.LINE_AA)
    return np.vstack([head, vis])

rows = []
for name in PLANS:
    key = json.load(open(os.path.join(D, 'keys', name + '.json')))
    a = panel(name, json.load(open(os.path.join(A, name + '.found.json'))), name + ': Measure today', key['ppf'])
    b = panel(name, json.load(open(os.path.join(B, name + '.found.json'))), name + ': walls first, session 2', key['ppf'])
    row = np.hstack([a, np.full((a.shape[0], 16, 3), 255, np.uint8), b])
    s = 1400 / row.shape[1]
    rows.append(cv2.resize(row, None, fx=s, fy=s, interpolation=cv2.INTER_AREA))
    cv2.imwrite(OUTP.replace('.png', '-' + name + '.png'), rows[-1])
sheet = np.vstack([np.vstack([r, np.full((20, r.shape[1], 3), 255, np.uint8)]) for r in rows])
cv2.imwrite(OUTP, sheet)
