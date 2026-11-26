"""Run the engine's WALLS (plan-engine.js) in Node on the five plans with the stand-in model replies,
and score it the way proto3.py scores the prototype. python3 jsparity.py [plan ...]
Needs node; the engine's WALLS section is cut out of plan-engine.js into a scratch folder."""
import json, os, sys, subprocess, re
import numpy as np, cv2
sys.argv, _args = sys.argv[:1], sys.argv[1:]
from score import mock, poly_mask
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = '/tmp/jsparity'; os.makedirs(TMP, exist_ok=True)
PLANS = _args or ['bedroom', 'studio', 'cabin', 'twostory', 'floor2']
FAM = {'bypass': 'sliding', 'pocket': 'sliding', 'barn': 'sliding', 'double': 'swing'}
fam = lambda t: FAM.get(t, t)
RUN = r'''
const fs = require('fs'), vm = require('vm');
const ctx = { Math, console, Uint8Array, Int32Array, Float32Array, Uint32Array, Object, JSON, Array, String, Number, isFinite };
vm.createContext(ctx);
const src = fs.readFileSync(process.argv[2], 'utf8');
const s = src.indexOf('var WALLS = (function'), e = src.indexOf('})();', s) + 5;
vm.runInContext(src.slice(s, e) + '\nthis.WALLS = WALLS;', ctx);
const meta = JSON.parse(fs.readFileSync(process.argv[3] + '.json'));
const g = new Uint8Array(fs.readFileSync(process.argv[3] + '.gray'));
const t = Date.now();
const res = ctx.WALLS.measure({ g, w: meta.w, h: meta.h }, meta.rooms, meta.hints);
res.ms = Date.now() - t;
fs.writeFileSync(process.argv[3] + '.res.json', JSON.stringify(res));
'''
open(os.path.join(TMP, 'run.js'), 'w').write(RUN)
ENGINE = os.environ.get('ENGINE') or os.path.normpath(os.path.join(D, '..', '..', 'static', 'tools', 'plan-engine.js'))

def page_room(r):
    return {'name': r['name'], 'bbox': r['bbox'], 'width': r.get('width_ft'), 'length': r.get('length_ft'),
            'printedArea': r.get('area_sqft'), 'source': r.get('source')}

def run(name):
    key = json.load(open(os.path.join(D, 'keys', name + '.json')))
    out = json.load(open(os.path.join(D, 'keys', name + '.out.json')))
    for r in out['rooms']:
        r['minor'] = [k for k in key['rooms'] if k['name'] == r['name']][0].get('minor', False)
    img = cv2.imread(os.path.join(D, 'plans', name + '.jpg')); g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); H, W = g.shape
    rj, oj = mock(name, key, out, img)
    mr, mo = json.loads(rj)['rooms'], json.loads(oj)
    hints = {'list': mo['openings'], 'overall': {'w': mo['overall']['width_ft'], 'h': mo['overall']['length_ft']}, 'dims': mo.get('dims', [])}
    base = os.path.join(TMP, name)
    json.dump({'w': W, 'h': H, 'rooms': [page_room(r) for r in mr], 'hints': hints}, open(base + '.json', 'w'))
    g.tofile(base + '.gray')
    subprocess.run(['node', os.path.join(TMP, 'run.js'), ENGINE, base], check=True)
    res = json.load(open(base + '.res.json'))
    # rooms
    ious = []
    for r in out['rooms']:
        if r['minor']: continue
        km = poly_mask(r['poly'], (H, W))
        i = [k for k, x in enumerate(mr) if x['name'] == r['name']]
        f = res['rooms'][i[0]] if i else None
        if not f: ious.append((r['name'], 0.0)); continue
        fm = poly_mask(f['poly'], (H, W))
        ious.append((r['name'], float((km & fm).sum() / (km | fm).sum())))
    ppf = res['ppf']
    sc = None if not ppf else abs(ppf - key['ppf']) / key['ppf'] * 100
    found = res['openings']
    def match(keys, fs):
        used, hits = set(), []
        for k in keys:
            kc = (np.array(k['a']) + np.array(k['b'])) / 2; kw = np.linalg.norm(np.array(k['a']) - np.array(k['b']))
            best = None
            for i, f in enumerate(fs):
                if i in used: continue
                d = np.linalg.norm(np.array(f['c']) - kc)
                if d <= max(1.5 * key['ppf'], kw / 2) and (best is None or d < best[1]): best = (i, d)
            if best: used.add(best[0]); hits.append((k, fs[best[0]]))
            else: hits.append((k, None))
        return hits, len(fs) - len(used)
    keyd = key.get('doors', []) + [dict(o, type='opening') for o in key.get('openings', [])]
    dh, dfp = match(keyd, [f for f in found if f['kind'] != 'window'])
    wh, wfp = match(key.get('windows', []), [f for f in found if f['kind'] == 'window'])
    right = sum(1 for k, f in dh if f and fam(f['kind']) == fam(k['type']))
    names = set(r['name'].lower() for r in mr)
    sw = [(k, f) for k, f in dh if f and k['type'] == 'swing' and f['kind'] == 'swing']
    hok = sum(1 for k, f in sw if np.linalg.norm(np.array(f['hingePt']) - np.array(k['a'] if k.get('hinge') == 'a' else k['b'])) < np.linalg.norm(np.array(f['hingePt']) - np.array(k['b'] if k.get('hinge') == 'a' else k['a'])))
    iok = sum(1 for k, f in sw if (f.get('into') or '').lower() == (k.get('into') or '').lower() or (k.get('into') or '').lower() not in names)
    ravg = sum(v for _, v in ious) / max(1, len(ious))
    parts = [ravg, right / max(1, len(dh)), sum(1 for k, f in wh if f) / max(1, len(wh)), max(0, 1 - (sc if sc is not None else 100) / 10)]
    s = round(sum(parts) / 4 * 100)
    print('%-9s score %3d | %5d ms | scale %s from %s | rooms %.2f %s' % (name, s, res['ms'], 'none' if sc is None else '%.1f%% off' % sc, ', '.join(res['from'] or []), ravg, ' '.join('%s=%.2f' % x for x in ious)))
    print('          doors %d/%d right, %d extra | windows %d/%d, %d extra | swings %d: hinge %d, into %d | corners %s' % (
        right, len(dh), dfp, sum(1 for k, f in wh if f), len(wh), wfp, len(sw), hok, iok, [len(r['poly']) for r in res['rooms'] if r]))
    return s

if __name__ == '__main__':
    ss = [run(n) for n in PLANS]
    print('OVERALL %d' % round(sum(ss) / len(ss)))
