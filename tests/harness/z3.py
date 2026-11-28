"""Tests for zones in bedrooms, offices and entryways (Z3).
python3 z3.py <base_url> <outdir>
Plans (make_open.py): z3/ (a foyer at the front door, an office, a 261 sq ft primary bedroom) and z3n/ (the same house
with the office as a guest room, so the house has no office); the 10-room harness plan (a 156 sq ft bedroom, an
office, a front door straight into the living room)."""
import json, math, os, sys
from playwright.sync_api import sync_playwright

H = os.path.dirname(os.path.abspath(__file__))
BASE, OUT = sys.argv[1].rstrip('/'), sys.argv[2]
os.makedirs(OUT, exist_ok=True)
R = []
def ok(name, cond, extra=''):
    R.append(('PASS' if cond else 'FAIL') + '  ' + name + (('  ' + extra[:400]) if extra else ''))
    print(R[-1], flush=True)

def router(plan):
    hd = H if plan == 'harness' else os.path.join(H, plan)
    rj, oj = open(os.path.join(hd, 'rooms.json')).read(), open(os.path.join(hd, 'openings.json')).read()
    def route(r, *_):
        u = r.request.url
        if 'onrender.com/api/vision' in u:
            body = json.loads(r.request.post_data or '{}')
            return r.fulfill(status=200, content_type='application/json', body=json.dumps({'content': [{'text': oj if 'door, doorway opening' in body.get('prompt', '') else rj}]}))
        if u.startswith('http://localhost') or u.startswith('data:') or u.startswith('blob:'): return r.continue_()
        return r.abort()
    return route

# Every card of a room: its label, note and pieces (feet), plus the room's area, the walls the pieces face and the
# front doors
CARDS = """async (n) => {
  var r = state.rooms.find(x => x.name === n), i = state.rooms.indexOf(r);
  select(i, false); setMode('furnish'); showPane(); startLayouts();
  await new Promise(res => { (function w() { if (state.layout && !state.layout.busy) res(); else setTimeout(w, 100); })(); });
  var poly = r.ftShape;
  return { area: PLAN.polyArea(poly), kind: layoutKind(r), why: state.layout.why, fronts: frontDoors(r).map(d => ({ x: d.mid.x, y: d.mid.y, w: d.w })),
    cards: (state.layout.list || []).map(o => ({ label: o.label, note: o.note,
      places: o.places.map(p => { var f = GEO.turn({ x: 0, y: 1 }, p.rot), ahead = GEO.rayPoly({ x: p.cx, y: p.cy }, f.x, f.y, poly);
        return { id: p.spec.id, role: p.spec.role, w: p.spec.w, cx: p.cx, cy: p.cy, rot: p.rot, edge: p.edge, poly: polyOf(p), ahead: ahead, fx: f.x, fy: f.y }; }) })) };
}"""
USE = """async (a) => {
  var n = a[0], k = a[1], r = state.rooms.find(x => x.name === n);
  select(state.rooms.indexOf(r), false); showPane(); startLayouts();
  await new Promise(res => { (function w() { if (state.layout && !state.layout.busy) res(); else setTimeout(w, 100); })(); });
  var before = JSON.stringify(state.pieces.map(p => [p.type, p.x, p.y]));
  state.layout.pick = k; renderLayouts(); useLayout();
  var rows = spaceRows(r).filter(rw => rw.status === 'close').map(rw => rw.label);
  var placed = state.pieces.filter(p => pieceRoom(p) === r).length;
  undo();
  return { rows: rows, placed: placed, undone: JSON.stringify(state.pieces.map(p => [p.type, p.x, p.y])) === before };
}"""

def dist(a, b): return math.hypot(a['cx'] - b['cx'], a['cy'] - b['cy'])
def poly_dist(a, b):
    """Smallest distance between two convex polygons that don't overlap (vertex to edge both ways), 0 if they touch."""
    def seg(p, a, b):
        dx, dy = b['x'] - a['x'], b['y'] - a['y']; L = dx * dx + dy * dy or 1e-9
        t = max(0, min(1, ((p['x'] - a['x']) * dx + (p['y'] - a['y']) * dy) / L))
        return math.hypot(p['x'] - a['x'] - t * dx, p['y'] - a['y'] - t * dy)
    return min(min(seg(p, Q[i], Q[(i + 1) % len(Q)]) for p in P for i in range(len(Q))) for P, Q in ((a, b), (b, a)))

errs = []
def page_for(b, plan):
    ctx = b.new_context(viewport={'width': 1360, 'height': 860}); ctx.route('**/*', router(plan))
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errs.append(plan + ': ' + str(e)))
    hd = H if plan == 'harness' else os.path.join(H, plan)
    pg.goto(BASE + '/static/tools/floor-planner.html'); pg.wait_for_function("() => typeof state !== 'undefined'")
    pg.set_input_files('#fileInput', os.path.join(hd, 'plan.png'))
    pg.wait_for_function("() => state.rooms.length && (state.openingsDone || !state.scale)", timeout=60000); pg.wait_for_timeout(600)
    return pg

def cards(pg, plan, room):
    d = pg.evaluate(CARDS, room)
    json.dump(d, open(os.path.join(OUT, '%s-%s.json' % (plan, room.replace(' ', '_'))), 'w'), indent=1)
    return d

def use_all(pg, plan, room, d):
    res = [pg.evaluate(USE, [room, k]) for k in range(len(d['cards']))]
    ok('%s %s: every card used has nothing in burgundy and one Undo brings the room back' % (plan, room),
       len(res) > 0 and all(not x['rows'] and x['undone'] and x['placed'] > 0 for x in res), json.dumps(res))

with sync_playwright() as pw:
    b = pw.chromium.launch()

    # ---- z3: a house with an office ----
    pg = page_for(b, 'z3')
    bd = cards(pg, 'z3', 'Primary Bedroom')
    ok('z3 primary bedroom (%d sq ft) gets cards' % bd['area'], len(bd['cards']) >= 2, json.dumps([c['label'] for c in bd['cards']]))
    seated = [c for c in bd['cards'] if any(p['id'] == 'armchair' for p in c['places'])]
    ok('a bedroom of 180 sq ft and up gets seating on at least one card', len(seated) >= 1, json.dumps([c['label'] for c in bd['cards']]))
    good = True; why = []
    for c in seated:
        bed = c['places'][0]; row = [p for p in c['places'] if p['role'] in ('bed', 'nightstand')]
        for p in c['places']:
            if p['id'] != 'armchair': continue
            if p['ahead'] is None or p['ahead'] < 4: good = False; why.append(('faces a wall', c['label'], p['ahead']))
            if p.get('edge') is not None and p['edge'] == bed.get('edge'): good = False; why.append(('headboard wall', c['label']))
            if min(poly_dist(p['poly'], q['poly']) for q in row) < 1 - 1e-3: good = False; why.append(('near the bed', c['label']))
    ok('bedroom seating faces the room, keeps off the headboard wall and 12"+ from the bed and nightstands', good, json.dumps(why))
    ok('the card names its zone mix', any('reading corner' in c['label'] or 'sitting area' in c['label'] for c in bd['cards']), json.dumps([c['label'] for c in bd['cards']]))
    ok('a house with an office: no bedroom card brings a desk', not any(any(p['role'] == 'desk' for p in c['places']) for c in bd['cards']), json.dumps([c['label'] for c in bd['cards']]))
    use_all(pg, 'z3', 'Primary Bedroom', bd)

    of = cards(pg, 'z3', 'Office')
    labels = [c['label'] for c in of['cards']]
    cl = [c for c in of['cards'] if 'chairs across' in c['label']]
    ok('office: one card with client chairs across the desk', len(cl) == 1, json.dumps(labels))
    if cl:
        c = cl[0]; desk = c['places'][0]; gs = [p for p in c['places'] if p['id'] == 'armchair' and p['role'] == 'chair']
        facing = all((desk['cx'] - g['cx']) * g['fx'] + (desk['cy'] - g['cy']) * g['fy'] > 0 for g in gs)
        ok('the client chairs face the desk, 2 of them', len(gs) == 2 and facing, json.dumps([(g['cx'], g['cy'], g['rot']) for g in gs]))
    ok('an office of 100 sq ft and up gets a reading corner or a loveseat on a card', any('reading corner' in l or 'loveseat' in l for l in labels), json.dumps(labels))
    rm = [c for c in of['cards'] if c['label'].startswith('Desk facing into the room')]
    ok('an office with a window leads with the desk facing it', bool(of['cards']) and of['cards'][0]['label'].startswith('Desk facing the window'), json.dumps(labels))
    ok('the desk facing into the room faces a view first (the window, else the door)', bool(rm) and 'You face the window' in rm[0]['note'], json.dumps([c['note'] for c in rm]))
    chairs = [p for c in of['cards'] + bd['cards'] for p in c['places'] if p['id'] == 'armchair' and p['role'] == 'seat']
    ok('reading chairs stand in corners, never in the middle of a wall', all(p.get('edge') is None for p in chairs) and len(chairs) > 0, json.dumps([(p['cx'], p['cy'], p.get('edge')) for p in chairs]))
    use_all(pg, 'z3', 'Office', of)

    fy = cards(pg, 'z3', 'Foyer')
    labels = [c['label'] for c in fy['cards']]
    ok('the foyer is an entry with a front door', fy['kind'] == 'entry' and len(fy['fronts']) == 1, json.dumps([fy['kind'], fy['fronts']]))
    ok('foyer cards: a console table, then a bench, by the front door', len(labels) == 2 and labels[0].startswith('Console table by the front door') and labels[1].startswith('Bench by the front door'), json.dumps(labels))
    if fy['fronts'] and fy['cards']:
        fd = fy['fronts'][0]
        near = all(1.5 <= math.hypot(c['places'][0]['cx'] - fd['x'], c['places'][0]['cy'] - fd['y']) <= 9 for c in fy['cards'])
        ok('the entry piece stands within 9\' of the front door', near, json.dumps([(c['places'][0]['cx'], c['places'][0]['cy']) for c in fy['cards']]))
    use_all(pg, 'z3', 'Foyer', fy)
    pg.evaluate("() => { var r = state.rooms.find(x => x.name === 'Foyer'); r.name = 'Mudroom'; renderAll(); }")
    md = cards(pg, 'z3', 'Mudroom')
    ok('a mudroom leads with the bench', bool(md['cards']) and md['cards'][0]['label'].startswith('Bench'), json.dumps([c['label'] for c in md['cards']]))
    pg.screenshot(path=os.path.join(OUT, 'z3.png'))
    pg.context.close()

    # ---- z3n: the same house with no office ----
    pg = page_for(b, 'z3n')
    bn = cards(pg, 'z3n', 'Primary Bedroom')
    ok('a house with no office: a bedroom of 180 sq ft and up offers a desk', any(any(p['role'] == 'desk' for p in c['places']) for c in bn['cards']), json.dumps([c['label'] for c in bn['cards']]))
    gr = cards(pg, 'z3n', 'Guest Room')
    ok('a bedroom under 180 sq ft (%d) gets no armchair, and a desk only on the smaller-bed card' % gr['area'],
       not any(any(p['id'] == 'armchair' for p in c['places']) or (any(p['role'] == 'desk' for p in c['places']) and 'and a desk' not in c['label']) for c in gr['cards']), json.dumps([c['label'] for c in gr['cards']]))
    use_all(pg, 'z3n', 'Primary Bedroom', bn)
    pg.context.close()

    # ---- harness: a front door straight into the living room; a small bedroom ----
    pg = page_for(b, 'harness')
    lv = cards(pg, 'harness', 'Living Room')
    ok('a front door into the living room: a console or bench by it on a card', any('by the front door' in c['label'] for c in lv['cards']) and len(lv['fronts']) >= 1, json.dumps([c['label'] for c in lv['cards']]))
    hb = cards(pg, 'harness', 'Bedroom')
    ok('the harness bedroom (%d sq ft, under 180) gets no armchair' % hb['area'], not any(any(p['id'] == 'armchair' for p in c['places']) for c in hb['cards']), json.dumps([c['label'] for c in hb['cards']]))
    use_all(pg, 'harness', 'Living Room', lv)
    pg.context.close()
    b.close()

ok('no page errors', not errs, json.dumps(errs[:3]))
open(os.path.join(OUT, 'results.txt'), 'w').write('\n'.join(R) + '\n')
print('%d of %d pass' % (sum(1 for x in R if x.startswith('PASS')), len(R)))
