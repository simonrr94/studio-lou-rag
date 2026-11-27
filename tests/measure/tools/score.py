"""Score Measure against the answer keys.
python3 score.py <base_url> <outdir> [plan ...]
For each plan: a stand-in model reply is made from the key (room names, printed sizes, rough boxes
nudged off the true ones, a rough list of doors and windows), the page reads the plan, and what Measure
found is compared with the key: scale, room outlines (overlap), doors, windows, openings."""
import json, os, sys, math, random
import numpy as np, cv2
from playwright.sync_api import sync_playwright

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSPDF = open('/home/claude/harness/vendor/package/dist/jspdf.umd.min.js').read() if os.path.exists('/home/claude/harness/vendor/package/dist/jspdf.umd.min.js') else ''
INIT = open('/home/claude/harness/init.js').read() if os.path.exists('/home/claude/harness/init.js') else ''
# printed overall sizes, as a model reading the dimension lines would report them
OVERALL = {'studio': (None, 23.0), 'cabin': (20.0, 28.0), 'bedroom': (13 + 10 / 12, 12.0), 'twostory': (None, None), 'floor2': (None, None)}

def core_rect(poly, H, W):
    """The largest axis-aligned rectangle inside a room's outline."""
    m = np.zeros((H, W), np.uint8); cv2.fillPoly(m, [np.array(poly, np.int32)], 1)
    hgt = np.zeros(W, int); best = (0, 0, 0, 0, 0)
    for y in range(H):
        hgt = np.where(m[y] > 0, hgt + 1, 0)
        st = []
        for x in range(W + 1):
            hh = hgt[x] if x < W else 0
            s = x
            while st and st[-1][1] >= hh:
                s0, h0 = st.pop()
                if h0 * (x - s0) > best[0]: best = (h0 * (x - s0), s0, y - h0 + 1, x, y + 1)
                s = s0
            st.append((s, hh))
    return best[1], best[2], best[3], best[4]
def mock(name, key, out, img):
    H, W = img.shape[:2]
    rnd = random.Random(name)   # the same nudges every run
    rooms = []
    for r in out['rooms']:
        if r.get('minor') or any(k.get('minor') and k['name'] == r['name'] for k in key['rooms']): continue
        p = np.array(r['poly'], float); x0, y0 = p.min(0); x1, y1 = p.max(0)
        if os.environ.get('CORE'):   # CORE=1: the box drawn round the room's main rectangle only (bump-outs and legs left out)
            x0, y0, x1, y1 = core_rect(r['poly'], H, W)
        j = lambda v, s: v + rnd.uniform(-s, s)
        J = 0.03 * float(os.environ.get('JITTER', 1))   # JITTER=2: boxes twice as rough (the real model's can be)
        bx0, by0, bx1, by1 = j(x0, J * W), j(y0, J * H), j(x1, J * W), j(y1, J * H)
        kr = [k for k in key['rooms'] if k['name'] == r['name']][0]
        pr = kr.get('printed') or ''
        wft = lft = None
        import re
        m = re.match(r"(\d+)'(?:\s*(\d+)\")?\s*x\s*(\d+)'(?:\s*(\d+)\")?", pr.replace('’', "'").replace('”', '"'))
        if m: wft = int(m.group(1)) + int(m.group(2) or 0) / 12; lft = int(m.group(3)) + int(m.group(4) or 0) / 12
        sq = re.search(r'(\d+) sq ft', pr)
        rooms.append({'name': r['name'], 'label': r['name'], 'width_ft': wft, 'length_ft': lft, 'area_sqft': int(sq.group(1)) if sq else None,
                      'source': 'labeled' if (wft or sq) else 'estimated',
                      'bbox': {'x': round(bx0 / W * 100, 2), 'y': round(by0 / H * 100, 2), 'w': round((bx1 - bx0) / W * 100, 2), 'h': round((by1 - by0) / H * 100, 2)}})
    ops = []
    for d in key.get('doors', []):
        c = (np.array(d['a']) + np.array(d['b'])) / 2
        ops.append({'kind': 'door', 'type': {'swing': 'swing', 'sliding': 'sliding', 'bypass': 'sliding', 'bifold': 'bifold', 'pocket': 'pocket'}.get(d['type'], 'swing'),
                    'x': round((c[0] + rnd.uniform(-10, 10)) / W * 100, 2), 'y': round((c[1] + rnd.uniform(-10, 10)) / H * 100, 2), 'width_in': None,
                    'rooms': [d.get('into') or '', d.get('room2') or '']})
    for w in key.get('windows', []):
        c = (np.array(w['a']) + np.array(w['b'])) / 2
        ops.append({'kind': 'window', 'type': None, 'x': round((c[0] + rnd.uniform(-10, 10)) / W * 100, 2), 'y': round((c[1] + rnd.uniform(-10, 10)) / H * 100, 2), 'width_in': None, 'rooms': ['', 'outside']})
    for o in key.get('openings', []):
        c = (np.array(o['a']) + np.array(o['b'])) / 2
        ops.append({'kind': 'opening', 'type': None, 'x': round(c[0] / W * 100, 2), 'y': round(c[1] / H * 100, 2), 'width_in': None, 'rooms': o.get('rooms', ['', ''])})
    # printed dimension lines: the value read right, the ends pointed at roughly (2% of the picture)
    dims = []
    for dm in key.get('dims', []):
        e = lambda v, s: round((v + rnd.uniform(-0.02, 0.02) * s) / s * 100, 2)
        dims.append({'text': dm['text'], 'feet': dm['ft'], 'x1': e(dm['a'][0], W), 'y1': e(dm['a'][1], H), 'x2': e(dm['b'][0], W), 'y2': e(dm['b'][1], H)})
    # counters and islands: a rough box round each (each side off by up to 1.5% of the picture, 3% with JITTER=2);
    # their own random numbers, so the rest of the reply is the same as before they were added
    fr, fx = random.Random(name + 'fixtures'), []
    J2 = 0.015 * float(os.environ.get('JITTER', 1))
    for f in key.get('fixtures', []):
        x0, y0, x1, y1 = f['rect']
        x0, x1 = x0 + fr.uniform(-J2, J2) * W, x1 + fr.uniform(-J2, J2) * W
        y0, y1 = y0 + fr.uniform(-J2, J2) * H, y1 + fr.uniform(-J2, J2) * H
        fx.append({'kind': f['kind'], 'x': round(x0 / W * 100, 2), 'y': round(y0 / H * 100, 2), 'w': round((x1 - x0) / W * 100, 2), 'h': round((y1 - y0) / H * 100, 2)})
    ow, ol = OVERALL.get(name, (None, None))
    return json.dumps({'unit': 'ft', 'rooms': rooms}), json.dumps({'openings': ops, 'overall': {'width_ft': ow, 'length_ft': ol}, 'dims': dims, 'fixtures': fx})

def poly_mask(poly, shape):
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.array(poly, np.int32)], 1)
    return m

def score(name, key, out, found, img):
    H, W = img.shape[:2]
    res = {'plan': name}
    ppf = 1 / found['ftPerPx'] if found.get('ftPerPx') else None
    res['scale'] = None if not ppf else round(abs(ppf - key['ppf']) / key['ppf'] * 100, 1)
    # rooms: overlap of each key room with the found room of the same name
    ious = []
    vis = img.copy()
    for r in out['rooms']:
        kr = [k for k in key['rooms'] if k['name'] == r['name']][0]
        if kr.get('minor'): continue
        km = poly_mask(r['poly'], (H, W))
        cv2.polylines(vis, [np.array(r['poly'], np.int32)], True, (0, 160, 0), 2)
        f = [x for x in found['rooms'] if x['name'].lower() == r['name'].lower()]
        if not f or not f[0]['poly']: ious.append((r['name'], 0.0)); continue
        fm = poly_mask(f[0]['poly'], (H, W))
        cv2.polylines(vis, [np.array(f[0]['poly'], np.int32)], True, (0, 0, 220), 2)
        inter, uni = (km & fm).sum(), (km | fm).sum()
        ious.append((r['name'], round(inter / uni, 3) if uni else 0))
    res['rooms'] = ious
    res['room_avg'] = round(sum(v for _, v in ious) / max(1, len(ious)), 3)
    # doors and windows: matched by position (within 18" or half the width), then type
    def match(keys, founds, tol_ft=1.5):
        used, hits = set(), []
        for k in keys:
            kc = (np.array(k['a']) + np.array(k['b'])) / 2; kw = np.linalg.norm(np.array(k['a']) - np.array(k['b']))
            best = None
            for i, f in enumerate(founds):
                if i in used: continue
                dist = np.linalg.norm(np.array(f['c']) - kc)
                if dist <= max(tol_ft * key['ppf'], kw / 2) and (best is None or dist < best[1]): best = (i, dist)
            if best: used.add(best[0]); hits.append((k, founds[best[0]]))
            else: hits.append((k, None))
        return hits, len(founds) - len(used)
    fd = [f for f in found['doors'] if f['type'] != 'window']
    fw = [f for f in found['doors'] if f['type'] == 'window']
    dh, dfp = match(key.get('doors', []) + [dict(o, type='opening') for o in key.get('openings', [])], fd)
    wh, wfp = match(key.get('windows', []), fw)
    fam = lambda t: {'bypass': 'sliding', 'pocket': 'sliding', 'barn': 'sliding', 'double': 'swing'}.get(t, t)
    res['doors'] = '%d/%d found, %d right type, %d extra' % (sum(1 for k, f in dh if f), len(dh), sum(1 for k, f in dh if f and fam(f['type']) == fam(k['type'])), dfp)
    res['doors_missed'] = [k.get('type') + '@%d,%d' % tuple(((np.array(k['a']) + np.array(k['b'])) / 2).astype(int)) for k, f in dh if not f]
    res['doors_wrongtype'] = ['%s as %s' % (k['type'], f['type']) for k, f in dh if f and fam(f['type']) != fam(k['type'])]
    res['windows'] = '%d/%d found, %d extra' % (sum(1 for k, f in wh if f), len(wh), wfp)
    for f in found['doors']:
        col = (220, 120, 0) if f['type'] == 'window' else (200, 0, 200)
        cv2.line(vis, tuple(map(int, f['a'])), tuple(map(int, f['b'])), col, 3)
    cv2.imwrite(os.path.join(OUT, name + '.png'), vis)
    # one number to watch: rooms, doors and windows found, and scale, each counted the same
    parts = [res['room_avg'], sum(1 for k, f in dh if f) / max(1, len(dh)), sum(1 for k, f in wh if f) / max(1, len(wh)),
             max(0, 1 - (res['scale'] if res['scale'] is not None else 100) / 10)]
    res['score'] = round(sum(parts) / len(parts) * 100)
    return res

NO_DOORS = False
FOUND_JS = """() => {
  var f = state.scale && state.scale.ftPerPx, W = state.W, H = state.H;
  function px(p) { return [p.x / f, p.y / f]; }
  return { ftPerPx: f || null, from: state.scale && state.scale.from, walls: state.scale && state.scale.walls,
    rooms: state.rooms.map(function (r) {
      var poly = r.ftShape && f ? r.ftShape.map(px) : r.bbox ? [[r.bbox.x/100*W, r.bbox.y/100*H], [(r.bbox.x+r.bbox.w)/100*W, r.bbox.y/100*H], [(r.bbox.x+r.bbox.w)/100*W, (r.bbox.y+r.bbox.h)/100*H], [r.bbox.x/100*W, (r.bbox.y+r.bbox.h)/100*H]] : null;
      return { name: r.name, poly: poly }; }),
    doors: f ? state.doors.map(function (d) { var g = DOOR.geom(doorFt(d)); var a = px(g.jambs[0]), b = px(g.jambs[1]);
      return { type: d.type === 'window' ? 'window' : (d.type || 'swing'), a: a, b: b, c: [(a[0]+b[0])/2, (a[1]+b[1])/2] }; }) : [] };
}"""

def main():
    global BASE, OUT
    global NO_DOORS
    NO_DOORS = '--no-doors-call' in sys.argv
    sys.argv = [a for a in sys.argv if a != '--no-doors-call']
    BASE, OUT = sys.argv[1].rstrip('/'), sys.argv[2]
    PLANS = sys.argv[3:] or ['bedroom', 'studio', 'cabin', 'twostory', 'floor2']
    os.makedirs(OUT, exist_ok=True)
    rows = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for name in PLANS:
            key = json.load(open(os.path.join(D, 'keys', name + '.json')))
            out = json.load(open(os.path.join(D, 'keys', name + '.out.json')))
            for r in out['rooms']:
                kr = [k for k in key['rooms'] if k['name'] == r['name']][0]; r['minor'] = kr.get('minor', False)
            img = cv2.imread(os.path.join(D, 'plans', name + '.jpg'))
            rooms_js, open_js = mock(name, key, out, img)
            ctx = b.new_context(viewport={'width': 1360, 'height': 860})
            ctx.add_init_script(INIT)
            def make(rooms_js, open_js):
              def route(r, *_):
                u = r.request.url
                if 'onrender.com/api/vision' in u:
                    body = json.loads(r.request.post_data or '{}')
                    if 'door, doorway opening' in body.get('prompt', '') and NO_DOORS: return r.fulfill(status=500, body='down')
                    txt = open_js if 'door, doorway opening' in body.get('prompt', '') else rooms_js
                    return r.fulfill(status=200, content_type='application/json', body=json.dumps({'content': [{'text': txt}]}))
                if 'jspdf' in u: return r.fulfill(status=200, content_type='application/javascript', body=JSPDF)
                if u.startswith('http://localhost') or u.startswith('data:') or u.startswith('blob:'): return r.continue_()
                return r.abort()
              return route
            ctx.route('**/*', make(rooms_js, open_js))
            page = ctx.new_page(); errs = []
            page.on('pageerror', lambda e: errs.append(str(e)))
            page.goto(BASE + '/static/tools/floor-planner.html')
            page.wait_for_function("() => typeof state !== 'undefined'")
            page.set_input_files('#fileInput', os.path.join(D, 'plans', name + '.jpg'))
            try: page.wait_for_function("() => state.rooms.length", timeout=60000)
            except Exception:
                page.screenshot(path=os.path.join(OUT, name + '-fail.png'))
                print(name, 'no rooms:', errs, page.evaluate("() => document.body.innerText.slice(0, 400)")); ctx.close(); continue
            try: page.wait_for_function("() => state.openingsDone || !state.scale", timeout=15000)
            except Exception: pass
            page.wait_for_timeout(1500)
            page.screenshot(path=os.path.join(OUT, name + '-page.png'))
            found = page.evaluate(FOUND_JS)
            json.dump(found, open(os.path.join(OUT, name + '.found.json'), 'w'))
            r = score(name, key, out, found, img)
            r['errors'] = errs
            rows.append(r)
            ctx.close()
        b.close()
    json.dump(rows, open(os.path.join(OUT, 'scores.json'), 'w'), indent=1)
    for r in rows:
        print('%-9s score %3d | scale off %s%% | rooms %.2f %s' % (r['plan'], r['score'], r['scale'], r['room_avg'], ' '.join('%s=%.2f' % x for x in r['rooms'])))
        print('          doors %s %s %s | windows %s %s' % (r['doors'], ('missed ' + ', '.join(r['doors_missed'])) if r['doors_missed'] else '',
              ('wrong type ' + ', '.join(r['doors_wrongtype'])) if r['doors_wrongtype'] else '', r['windows'], ('ERR ' + r['errors'][0][:80]) if r['errors'] else ''))
    print('OVERALL %d' % round(sum(r['score'] for r in rows) / len(rows)))

if __name__ == '__main__': main()
