"""Tests for kitchens and baths (Phase D, Nov 28): bath fixtures read from the plan, counter stools at an
island, a runner in the kitchen's work aisle, bath mats and vanity runners, the Rugs tab's runners and mats.
python3 kb.py <base_url> <outdir>     Plans (make_open.py): kb/ (kitchen with an island, two baths), kd/."""
import json, os, sys
from playwright.sync_api import sync_playwright

H = os.path.dirname(os.path.abspath(__file__))
BASE, OUT = sys.argv[1].rstrip('/'), sys.argv[2]
os.makedirs(OUT, exist_ok=True)
R = []
def ok(name, cond, extra=''):
    R.append(('PASS' if cond else 'FAIL') + '  ' + name + (('  ' + str(extra)[:400]) if extra else ''))
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

# A room's fixtures and its cards: labels, notes, pieces and rugs (feet), with what the checks say once used
CARDS = """async (name) => {
  var r = state.rooms.find(x => x.name === name), i = state.rooms.indexOf(r);
  state.layout = null; select(i, false); setMode('furnish'); showPane(); startLayouts();
  await new Promise(res => { (function w() { if (state.layout && !state.layout.busy) res(); else setTimeout(w, 100); })(); });
  var fx = kbFixtures(r), sweeps = doorSweeps();
  function rugPoly(rg) { return rg ? RUG.outline(RUG.get(rg.size), rg.rot, rg.cx, rg.cy) : null; }
  var list = (state.layout.list || []).slice(), cards = [];
  for (var k = 0; k < list.length; k++) { var o = list[k];
    await new Promise(res => { (function w() { if (state.layout && !state.layout.busy) res(); else setTimeout(w, 100); })(); });
    var rp = [o.rug, o.rug2].filter(Boolean).map(rugPoly);
    var info = { label: o.label, note: o.note, rugs: [o.rug, o.rug2].filter(Boolean).map(g => g.size),
      stools: o.places.filter(p => p.spec.id === 'stool').map(p => ({ x: p.cx, y: p.cy })),
      rugInside: rp.every(pl => pl.every(q => PLAN.pointInPoly(q, r.ftShape))),
      rugOffFixtures: rp.every(pl => fx.every(f => GEO.polyDist(pl, f.poly) > 0.01)),
      rugOffSwings: rp.every(pl => sweeps.every(s => GEO.polyDist(pl, s) > 0.01)), rugPolys: rp };
    state.layout.list = list; state.layout.pick = k; renderLayouts(); useLayout();
    r = state.rooms.find(x => x.name === name);
    info.close = spaceRows(r).filter(rw => rw.status === 'close').map(rw => rw.label);
    info.placed = { pieces: state.pieces.filter(p => pieceRoom(p) === r).length, rug: !!r.rug, rug2: !!r.rug2 };
    undo(); r = state.rooms.find(x => x.name === name);
    info.undone = !r.rug && !r.rug2 && !state.pieces.some(p => pieceRoom(p) === r);
    state.layout = null; select(i, false); startLayouts();
    cards.push(info);
  }
  await new Promise(res => { (function w() { if (state.layout && !state.layout.busy) res(); else setTimeout(w, 100); })(); });
  return { why: state.layout.why || null, fixtures: fx.map(f => ({ kind: f.kind, front: f.front, b: f.b })), cards: cards };
}"""

errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={'width': 1400, 'height': 900})
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.route('**/*', router('kb'))
    page.goto(BASE + '/static/tools/floor-planner.html'); page.wait_for_function("() => typeof state !== 'undefined'")
    page.set_input_files('#fileInput', os.path.join(H, 'kb', 'plan.png'))
    page.wait_for_function("() => state.rooms.length && (state.openingsDone || !state.scale)", timeout=60000); page.wait_for_timeout(600)
    res = {}
    for name in ['Kitchen', 'Bath', 'Primary Bath', 'Living Room']:
        res[name] = page.evaluate(CARDS, name)
        page.evaluate("() => { var L = state.layout; if (L && L.list && L.list.length) { L.pick = 0; renderLayouts(); draw(); } }")
        page.screenshot(path=os.path.join(OUT, 'kb-' + name.replace(' ', '_') + '.png'))
    json.dump(res, open(os.path.join(OUT, 'kb.json'), 'w'), indent=1)

    k, bt, pb = res['Kitchen'], res['Bath'], res['Primary Bath']
    kinds = lambda x: sorted(f['kind'] for f in x['fixtures'])
    ok('kitchen: counter and island read from the plan', kinds(k) == ['counter', 'island'], kinds(k))
    ok('bath: tub, toilet and vanity read, fronts right', kinds(bt) == ['toilet', 'tub', 'vanity'] and
       {f['kind']: f['front'] for f in bt['fixtures']} == {'tub': 'S', 'toilet': 'W', 'vanity': 'W'}, bt['fixtures'])
    ok('primary bath: double vanity, toilet and shower read, fronts right', kinds(pb) == ['shower', 'toilet', 'vanity'] and
       {f['kind']: f['front'] for f in pb['fixtures']}['vanity'] == 'S' and {f['kind']: f['front'] for f in pb['fixtures']}['toilet'] == 'E', pb['fixtures'])
    c0 = k['cards'][0] if k['cards'] else {}
    ok('kitchen: first card has 3 stools at the 6\' island', len(c0.get('stools', [])) == 3, c0.get('label'))
    isl = [f for f in k['fixtures'] if f['kind'] == 'island'][0]['b']
    ok('kitchen: stools on the side away from the counter', all(s['y'] > isl['y'] + isl['h'] - 0.1 for s in c0.get('stools', [])) and c0.get('stools'), c0.get('stools'))
    ok('kitchen: a runner in the aisle, 2\'6" wide (44" aisle less 6" each side)', c0.get('rugs') and c0['rugs'][0].startswith('2.5x'), c0.get('rugs'))
    if c0.get('rugPolys'):
        ys = [q['y'] for q in c0['rugPolys'][0]]; cnt = [f for f in k['fixtures'] if f['kind'] == 'counter'][0]['b']
        ok('kitchen: the runner sits between the counter and the island', min(ys) >= cnt['y'] + cnt['h'] and max(ys) <= isl['y'], (min(ys), max(ys)))
    ok('kitchen: a second card with the runner alone', len(k['cards']) == 2 and not k['cards'][1]['stools'] and k['cards'][1]['rugs'], [c['label'] for c in k['cards']])
    for nm, x in res.items():
        for c in x['cards']:
            if nm != 'Living Room': ok('%s "%s": rugs inside the room, off the fixtures and out of the door swings' % (nm, c['label']), c['rugInside'] and c['rugOffFixtures'] and c['rugOffSwings'])
            ok('%s "%s": used with nothing in burgundy, one Undo' % (nm, c['label']), not c['close'] and c['undone'], c['close'])
    cb = bt['cards'][0] if bt['cards'] else {}
    ok('bath: a mat by the tub and a mat at the single vanity', len(cb.get('rugs', [])) == 2 and cb['rugs'][0] in ('21x34', '20x30') and cb['rugs'][1] in ('21x34', '20x30'), cb.get('rugs'))
    cp = pb['cards'][0] if pb['cards'] else {}
    ok('primary bath: a mat at the shower and a runner along the double vanity', len(cp.get('rugs', [])) == 2 and cp['rugs'][1] in ('2x5', '2x6'), cp.get('rugs'))
    ok('living room still gets its own layouts', res['Living Room']['cards'] and 'stool' not in json.dumps(res['Living Room']['cards'][0]['label']).lower())

    # The Rugs tab: runners and mats in a bath, a tap lays one by the tub
    rt = page.evaluate("""() => {
      var r = state.rooms.find(x => x.name === 'Bath'); state.layout = null; select(state.rooms.indexOf(r), false); setMode('furnish');
      state.ptab = 'rugs'; showPane(); renderFurnish();
      var cards = Array.from(document.querySelectorAll('#rugBody [data-rug]')).map(b => b.getAttribute('data-rug'));
      placeRug('21x34');
      var f = state.scale.ftPerPx, cx = r.rug.x / 100 * state.W * f, cy = r.rug.y / 100 * state.H * f, tub = kbFixtures(r).find(q => q.kind === 'tub').b;
      var out = { cards: cards, sub: document.getElementById('rugSub').innerText, at: [cx, cy], tub: tub };
      undo(); var r2 = state.rooms.find(x => x.name === 'Living Room'); select(state.rooms.indexOf(r2), false); renderFurnish();
      out.living = Array.from(document.querySelectorAll('#rugBody [data-rug]')).map(b => b.getAttribute('data-rug'));
      return out; }""")
    ok('Rugs tab in a bath lists mats and runners', rt['cards'] == ['20x30', '21x34', '2x5', '2x6'], rt['cards'])
    ok('a mat tapped in a bath lands in front of the tub', abs(rt['at'][1] - (rt['tub']['y'] + rt['tub']['h'] + 21 / 24)) < 0.3 and rt['tub']['x'] < rt['at'][0] < rt['tub']['x'] + rt['tub']['w'], rt)
    ok('Rugs tab in a living room unchanged', rt['living'] == ['5x8', '6x9', '8x10', '9x12', '10x14', '6r', '8r'], rt['living'])

    # Kitchen/dining (kd/): the table cards gain stools and a runner where they fit
    page.route('**/*', router('kd'))
    page.goto(BASE + '/static/tools/floor-planner.html'); page.wait_for_function("() => typeof state !== 'undefined'")
    page.set_input_files('#fileInput', os.path.join(H, 'kd', 'plan.png'))
    page.wait_for_function("() => state.rooms.length && (state.openingsDone || !state.scale)", timeout=60000); page.wait_for_timeout(600)
    kd = page.evaluate(CARDS, 'Kitchen/Dining')
    page.evaluate("() => { var L = state.layout; if (L && L.list && L.list.length) { L.pick = 0; renderLayouts(); draw(); } }")
    page.screenshot(path=os.path.join(OUT, 'kd-Kitchen_Dining.png'))
    json.dump(kd, open(os.path.join(OUT, 'kd.json'), 'w'), indent=1)
    ok('kitchen/dining: table cards still offered', len(kd['cards']) >= 2, kd.get('why'))
    for c in kd['cards']:
        ok('kitchen/dining "%s": nothing in burgundy, rugs clear, one Undo' % c['label'], not c['close'] and c['undone'] and c['rugInside'] and c['rugOffFixtures'], (c['close'], c['rugs']))
    ok('no page errors', not errs, errs)
    b.close()
print('%d of %d pass' % (sum(1 for x in R if x.startswith('PASS')), len(R)))
