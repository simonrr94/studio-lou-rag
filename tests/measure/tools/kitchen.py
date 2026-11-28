"""Counters, islands and bath fixtures: the engine's KITCHEN.find run in Node on the plans with fixtures
in their keys, with the stand-in model's rough boxes, scored against the keys. python3 kitchen.py [plan ...]
(CORE=1 and JITTER=2 work as in score.py; KINDS=bath or KINDS=kitchen scores only those.) For each
fixture: overlap with the key (1.00 exact), how far a counter's front edge is off in inches, and for a
bath fixture whether the side people stand at (front) matches the key (ok / WRONG).
Pictures in /tmp/kitchen: the key in green, the engine's outline in blue (red when only the model's box)."""
import json, os, sys, subprocess
import numpy as np, cv2
sys.argv, _args = sys.argv[:1], sys.argv[1:]
from score import mock, poly_mask
import jsparity as JP
D = JP.D
PLANS = _args or ['studio', 'cabin', 'twostory', 'floor2']
BATHK = {'toilet', 'tub', 'shower', 'vanity'}
KINDS = os.environ.get('KINDS', '')
pick = lambda k: not KINDS or (KINDS == 'bath') == (k in BATHK)
RUN = r'''
const fs = require('fs'), vm = require('vm');
const ctx = { Math, console, Uint8Array, Int32Array, Float32Array, Uint32Array, Object, JSON, Array, String, Number, isFinite };
vm.createContext(ctx);
const src = fs.readFileSync(process.argv[2], 'utf8');
for (const name of ['WALLS', 'KITCHEN']) { const s = src.indexOf('var ' + name + ' = (function'), e = src.indexOf('})();', s) + 5; vm.runInContext(src.slice(s, e) + '\nthis.' + name + ' = ' + name + ';', ctx); }
const meta = JSON.parse(fs.readFileSync(process.argv[3] + '.json'));
const g = new Uint8Array(fs.readFileSync(process.argv[3] + '.gray'));
const G = { g, w: meta.w, h: meta.h };
const res = ctx.WALLS.measure(G, meta.rooms, meta.hints);
const fx = ctx.KITCHEN.find(G, res, meta.fixtures);
fs.writeFileSync(process.argv[3] + '.fx.json', JSON.stringify({ ppf: res.ppf, fixtures: fx }));
'''
open(os.path.join(JP.TMP, 'kitchen.js'), 'w').write(RUN)
tot = []; fronts = [0, 0]; per = {}
for name in PLANS:
    key = json.load(open(os.path.join(D, 'keys', name + '.json'))); out = json.load(open(os.path.join(D, 'keys', name + '.out.json')))
    img = cv2.imread(os.path.join(D, 'plans', name + '.jpg')); g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); H, W = g.shape
    rj, oj = mock(name, key, out, img); mr, mo = json.loads(rj)['rooms'], json.loads(oj)
    hints = {'list': mo['openings'], 'overall': {'w': mo['overall']['width_ft'], 'h': mo['overall']['length_ft']}, 'dims': mo.get('dims', [])}
    base = os.path.join(JP.TMP, name)
    json.dump({'w': W, 'h': H, 'rooms': [JP.page_room(r) for r in mr], 'hints': hints, 'fixtures': mo.get('fixtures', [])}, open(base + '.json', 'w'))
    g.tofile(base + '.gray')
    subprocess.run(['node', os.path.join(JP.TMP, 'kitchen.js'), JP.ENGINE, base], check=True)
    res = json.load(open(base + '.fx.json')); ppf = key['ppf']
    vis = img.copy(); rows = []
    for k, f in zip(key.get('fixtures', []), res['fixtures']):
        x0, y0, x1, y1 = k['rect']; kp = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        km, fm = poly_mask(kp, (H, W)), poly_mask(f['poly'], (H, W))
        iou = float((km & fm).sum() / max(1, (km | fm).sum()))
        fp = np.array(f['poly']); fx0, fy0 = fp.min(0); fx1, fy1 = fp.max(0)
        front = {'N': (fy1, y1), 'S': (fy0, y0), 'W': (fx1, x1), 'E': (fx0, x0)}.get(k.get('wall'))
        off = abs(front[0] - front[1]) / ppf * 12 if front and k['kind'] == 'counter' else None
        if not pick(k['kind']): continue
        fr = ''
        if k['kind'] in BATHK:
            ok = f.get('front') in k.get('front', '').split(); fronts[0] += ok; fronts[1] += 1
            fr = ' %s' % ('ok' if ok else 'WRONG(%s)' % f.get('front'))
        rows.append('%s %s %.2f%s%s%s' % (k['kind'], k.get('wall', ''), iou, ' front %.0f"' % off if off is not None else '', fr, ' ROUGH' if f.get('rough') else ''))
        tot.append(iou); per.setdefault(k['kind'], []).append(iou)
        cv2.polylines(vis, [np.array(kp, np.int32)], True, (0, 160, 0), 1)
        cv2.polylines(vis, [np.array(f['poly'], np.int32)], True, (0, 0, 220) if f.get('rough') else (220, 0, 0), 1)
    os.makedirs('/tmp/kitchen', exist_ok=True); cv2.imwrite('/tmp/kitchen/%s.png' % name, vis)
    print('%-9s %s' % (name, ' | '.join(rows)))
print('MEAN %.2f' % (sum(tot) / max(1, len(tot))) + '  ' + '  '.join('%s %.2f' % (k, sum(v) / len(v)) for k, v in sorted(per.items())) + ('  fronts %d of %d' % tuple(fronts) if fronts[1] else ''))
