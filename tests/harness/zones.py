"""Tests for zones in living rooms (Z2): the main group on the focal point, then the secondary zones.
python3 zones.py <base_url> <outdir>
Plans (make_open.py): fire/ fire2/ fire3/ (fireplaces), big/ (a big closed living room), open/ (a great room)."""
import json, os, sys
from playwright.sync_api import sync_playwright

H = os.path.dirname(os.path.abspath(__file__))
BASE, OUT = sys.argv[1].rstrip('/'), sys.argv[2]
os.makedirs(OUT, exist_ok=True)
R = []
def ok(name, cond, extra=''):
    R.append(('PASS' if cond else 'FAIL') + '  ' + name + (('  ' + extra[:400]) if extra else ''))
    print(R[-1], flush=True)

def router(plan):
    hd = os.path.join(H, plan)
    rj, oj = open(os.path.join(hd, 'rooms.json')).read(), open(os.path.join(hd, 'openings.json')).read()
    def route(r, *_):
        u = r.request.url
        if 'onrender.com/api/vision' in u:
            body = json.loads(r.request.post_data or '{}')
            return r.fulfill(status=200, content_type='application/json', body=json.dumps({'content': [{'text': oj if 'door, doorway opening' in body.get('prompt', '') else rj}]}))
        if u.startswith('http://localhost') or u.startswith('data:') or u.startswith('blob:'): return r.continue_()
        return r.abort()
    return route

# Every card of the living room: its label, its pieces (feet), what the checks say about them
CARDS = """async () => {
  var r = state.rooms.find(x => x.name === 'Living Room'), i = state.rooms.indexOf(r);
  select(i, false); setMode('furnish'); showPane(); startLayouts();
  await new Promise(res => { (function w() { if (state.layout && !state.layout.busy) res(); else setTimeout(w, 100); })(); });
  var fire = fireFt(r);
  return { fire: fire && { keep: fire.keep, mid: fire.mid, n: fire.n, a: fire.a, b: fire.b }, area: PLAN.polyArea(r.ftShape),
    cards: state.layout.list.map(o => ({ label: o.label, note: o.note,
      places: o.places.map(p => ({ id: p.spec.id, role: p.spec.role, cx: p.cx, cy: p.cy, rot: p.rot, poly: polyOf(p) })) })) };
}"""
USE = """async (k) => {
  var r = state.rooms.find(x => x.name === 'Living Room');
  if (!state.layout) {
    select(state.rooms.indexOf(r), false); showPane(); startLayouts();
    await new Promise(res => { (function w() { if (state.layout && !state.layout.busy) res(); else setTimeout(w, 100); })(); });
  }
  var before = JSON.stringify(state.pieces.map(p => [p.type, p.x, p.y]));
  state.layout.pick = k; renderLayouts(); useLayout();
  var rows = spaceRows(r).filter(rw => rw.status === 'close').map(rw => rw.label);
  undo();
  return { rows: rows, undone: JSON.stringify(state.pieces.map(p => [p.type, p.x, p.y])) === before };
}"""

def poly_hit(a, b):
    """Do two convex polygons overlap (separating axis)?"""
    for P in (a, b):
        for i in range(len(P)):
            p, q = P[i], P[(i + 1) % len(P)]; nx, ny = q['y'] - p['y'], p['x'] - q['x']
            pa = [nx * v['x'] + ny * v['y'] for v in a]; pb = [nx * v['x'] + ny * v['y'] for v in b]
            if max(pa) <= min(pb) + 1e-6 or max(pb) <= min(pa) + 1e-6: return False
    return True

def seat_front(p):
    import math
    a = math.radians(p['rot']); return (-math.sin(a), math.cos(a))   # GEO.turn((0, 1), rot)

def run(page, plan):
    ctx = page.context
    page.goto(BASE + '/static/tools/floor-planner.html'); page.wait_for_function("() => typeof state !== 'undefined'")
    page.set_input_files('#fileInput', os.path.join(H, plan, 'plan.png'))
    page.wait_for_function("() => state.rooms.length && (state.openingsDone || !state.scale)", timeout=60000); page.wait_for_timeout(600)
    d = page.evaluate(CARDS)
    page.screenshot(path=os.path.join(OUT, plan + '.png'))
    json.dump(d, open(os.path.join(OUT, plan + '.json'), 'w'), indent=1)
    return d

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    def page_for(plan):
        ctx = b.new_context(viewport={'width': 1360, 'height': 860}); ctx.route('**/*', router(plan))
        pg = ctx.new_page(); pg.on('pageerror', lambda e: errs.append(plan + ': ' + str(e)))
        return pg

    # fire3: a closed room, a solid breast with wall either side
    pg = page_for('fire3'); d = run(pg, 'fire3'); L = [c['label'] for c in d['cards']]
    ok('fire3: the first card faces the fireplace', L and 'facing the fireplace' in L[0], json.dumps(L))
    ok('fire3: the TV goes over the fireplace', 'over the fireplace' in d['cards'][0]['note'], d['cards'][0]['note'])
    ok('fire3: a card with the TV on its own wall', any('own wall' in x for x in L), json.dumps(L))
    ok('fire3: nothing on the hearth or right in front of it', not any(poly_hit(p['poly'], d['fire']['keep']) for c in d['cards'] for p in c['places']))
    bk = [p for p in d['cards'][0]['places'] if p['id'] == 'bookcase']
    fm = d['fire']['mid']
    ok('fire3: bookcases either side of the fireplace', len(bk) == 2 and (bk[0]['cx'] - fm['x']) * (bk[1]['cx'] - fm['x']) + (bk[0]['cy'] - fm['y']) * (bk[1]['cy'] - fm['y']) < 0, json.dumps([(p['cx'], p['cy']) for p in bk]))
    u = pg.evaluate(USE, 0)
    ok('fire3: the fireplace layout used, nothing in burgundy', not u['rows'], json.dumps(u['rows']))
    ok('fire3: one Undo brings the room back', u['undone'])

    # fire2: the fireplace on the long inside wall, between two doors
    pg = page_for('fire2'); d = run(pg, 'fire2'); L = [c['label'] for c in d['cards']]
    ok('fire2: the first card faces the fireplace', L and 'facing the fireplace' in L[0], json.dumps(L))
    n = d['fire']['n']
    def back_to_fire(c):
        main = [p for p in c['places'] if p['id'] in ('sofa', 'loveseat', 'sectional')][:1]
        return bool(main) and (lambda f: f[0] * n['x'] + f[1] * n['y'] > 0.5)(seat_front(main[0]))
    ok('fire2: no layout turns its back on the fireplace', not any(back_to_fire(c) for c in d['cards']), json.dumps(L))
    ok('fire2: no media console in front of the fireplace', not any(p['id'] == 'media' and poly_hit(p['poly'], d['fire']['keep']) for c in d['cards'] for p in c['places']))
    ok('fire2: open to the kitchen, so every card has a dining zone', all('dining' in x for x in L), json.dumps(L))
    for k in range(len(d['cards'])):
        u = pg.evaluate(USE, k)
        ok('fire2: card %d used, nothing in burgundy' % (k + 1), not u['rows'], json.dumps(u['rows']))

    # big: a big closed living room, room for a reading spot and a desk
    pg = page_for('big'); d = run(pg, 'big'); L = [c['label'] for c in d['cards']]
    rd = [c for c in d['cards'] if 'reading' in c['label']]
    ok('big: a card with a reading corner', bool(rd), json.dumps(L))
    ok('big: a card with a desk', any('desk' in x for x in L), json.dumps(L))
    import math
    def near_seat(c):
        seats = [p for p in c['places'] if p['role'] == 'seat']
        ch = [p for p in c['places'] if p['id'] == 'armchair'][-1]
        return min(math.hypot(ch['cx'] - s['cx'], ch['cy'] - s['cy']) for s in seats if s is not ch) <= 8.5
    ok('big: the reading chair within conversation distance of the group', all(near_seat(c) for c in rd))
    for k in range(len(d['cards'])):
        u = pg.evaluate(USE, k)
        ok('big: card %d used, nothing in burgundy' % (k + 1), not u['rows'], json.dumps(u['rows']))

    # open: a great room open to the kitchen keeps its dining zone by the kitchen
    pg = page_for('open'); d = run(pg, 'open'); L = [c['label'] for c in d['cards']]
    ok('open: the first card has dining by the kitchen', L and 'dining by the kitchen' in L[0], json.dumps(L))
    b.close()
ok('no page errors', not errs, json.dumps(errs[:3]))
open(os.path.join(OUT, 'results.txt'), 'w').write('\n'.join(R) + '\n')
print('%d of %d pass' % (sum(1 for x in R if x.startswith('PASS')), len(R)))
