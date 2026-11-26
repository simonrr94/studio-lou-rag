"""Floor Planner test harness.
Usage: python3 run.py <base_url> <outdir> [extra]
Drives the page with the test plan and mocked model replies, saving captures (screenshots,
panel text, plan state, export pages) to outdir. compare.py diffs two outdirs."""
import json, os, sys, subprocess, time
from playwright.sync_api import sync_playwright

H = os.path.dirname(os.path.abspath(__file__))
BASE, OUT = (sys.argv[1].rstrip('/'), sys.argv[2]) if __name__ == '__main__' else ('http://localhost:8001', '/tmp/x')
os.makedirs(OUT, exist_ok=True)
ROOMS = open(os.path.join(H, 'rooms.json')).read()
OPEN = open(os.path.join(H, 'openings.json')).read()
JSPDF = open(os.path.join(H, 'vendor/package/dist/jspdf.umd.min.js')).read()
PLAN = os.path.join(H, 'plan.png')
N = [0]

INIT = """
(function(){
  var BASE = Date.UTC(2026, 10, 26, 2, 10, 0);   // Nov 25, 7:10 PM in Phoenix
  var RD = Date;
  function D(a,b,c,d,e,f,g){ if (!arguments.length) return new RD(BASE); return arguments.length === 1 ? new RD(a) : new RD(a,b||0,c||1,d||0,e||0,f||0,g||0); }
  D.prototype = RD.prototype; D.now = function(){ return BASE; }; D.UTC = RD.UTC; D.parse = RD.parse;
  window.Date = D;
  var s = 12345; Math.random = function(){ s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
})();
"""

def route(r):
    u = r.request.url
    if 'onrender.com/api/vision' in u:
        body = json.loads(r.request.post_data or '{}')
        txt = OPEN if 'door, doorway opening' in body.get('prompt', '') else ROOMS
        return r.fulfill(status=200, content_type='application/json', body=json.dumps({'content': [{'text': txt}]}))
    if 'jspdf' in u: return r.fulfill(status=200, content_type='application/javascript', body=JSPDF)
    if u.startswith('http://localhost') or u.startswith('http://127.0.0.1') or u.startswith('data:') or u.startswith('blob:'):
        return r.continue_()
    return r.abort()

def cap(page, name, shot=True, text=True, state=True):
    N[0] += 1
    pre = os.path.join(OUT, '%03d-%s' % (N[0], name))
    if shot: page.screenshot(path=pre + '.png')
    if text: open(pre + '.txt', 'w').write(page.evaluate("() => { var p = document.getElementById('panel'); return p ? p.innerText : ''; }"))
    if state: open(pre + '.json', 'w').write(page.evaluate(STATE_JS))

STATE_JS = """() => {
  function r(v){ return typeof v === 'number' ? Math.round(v * 100) / 100 : v; }
  function clean(o){ return JSON.parse(JSON.stringify(o, function(k, v){ return typeof v === 'number' ? r(v) : v; })); }
  return JSON.stringify(clean({ mode: state.mode, sel: state.selected, scale: state.scale && state.scale.ftPerPx,
    rooms: state.rooms.map(function(x){ return [x.name, x.bbox, x.width, x.length, x.shape || null, x.rug || null]; }),
    pieces: state.pieces, doors: state.doors, lights: state.lights, lightCfg: state.lightCfg }), null, 0);
}"""

HELP = """
window.H = {
  room: function (name) { for (var i = 0; i < state.rooms.length; i++) if (state.rooms[i].name === name) return i; return -1; },
  // add a catalog piece in a room, then move it (and its chairs) so its center is at x, y feet on the plan
  put: function (id, room, x, y, rot) {
    select(H.room(room), false);
    addPiece(FURNITURE.get(id));
    var t = state.pieces[state.pieceSel], f = state.scale.ftPerPx;
    var tx = x / f / state.W * 100, ty = y / f / state.H * 100, dx = tx - t.x, dy = ty - t.y;
    var grp = [t].concat(chairsOf(t));
    grp.forEach(function (p) { p.x += dx; p.y += dy; });
    if (rot) rotateAbout(grp, { x: t.x / 100 * state.W, y: t.y / 100 * state.H }, rot);
    return t.id;
  }
};
"""
FT0 = 2   # the plan's margin in feet

FURNISH = [
    ('sofa', 'Living Room', 7, 12.6, 180), ('coffee', 'Living Room', 7, 9.9, 0), ('media', 'Living Room', 7, 1.1, 0),
    ('armchair', 'Living Room', 13, 7, 90), ('side', 'Living Room', 2.4, 13.2, 0),
    ('dining6', 'Dining Room', 21.5, 5.2, 0), ('counter', 'Kitchen', 33.5, 1.3, 0), ('islandP', 'Kitchen', 33.5, 6.4, 0),
    ('queen', 'Bedroom', 5, 18.85, 0), ('nightstand', 'Bedroom', 1.3, 16.05, 0), ('nightstand', 'Bedroom', 8.7, 16.05, 0),
    ('dresser', 'Bedroom', 8, 26.9, 180), ('vanity', 'Bath', 16, 19.85, 180),
    ('desk', 'Office', 28.5, 21, 0), ('deskchair', 'Office', 28.5, 19.6, 0), ('bookcase', 'Office', 26, 15.85, 0),
    ('armchair', 'Flex Room', 36.5, 22, 0), ('console', 'Hall', 30, 14.15, 180), ('sink', 'Laundry', 21, 26.7, 180)]

def load(page, url):
    page.goto(url)
    page.wait_for_function("() => typeof state !== 'undefined'")
    page.set_input_files('#fileInput', PLAN)
    page.wait_for_function("() => state.rooms.length && state.scale && state.openingsDone", timeout=60000)
    page.wait_for_timeout(600)
    page.evaluate(HELP)

def export(page, which, name):
    with page.expect_download(timeout=30000) as dl:
        page.evaluate("() => document.getElementById('%s').click()" % which)
    d = dl.value
    N[0] += 1
    pre = os.path.join(OUT, '%03d-%s' % (N[0], name))
    if which == 'pngBtn': d.save_as(pre + '.png'); return
    d.save_as(pre + '.pdf')
    pages = int([l for l in subprocess.run(['pdfinfo', pre + '.pdf'], capture_output=True, text=True).stdout.splitlines() if l.startswith('Pages')][0].split()[-1])
    open(pre + '.txt', 'w').write(subprocess.run(['pdftotext', '-layout', pre + '.pdf', '-'], capture_output=True, text=True).stdout)
    subprocess.run(['pdftoppm', '-r', '50', '-png', pre + '.pdf', pre + '-page'])
    os.remove(pre + '.pdf')
    return pages

def furnish(page):
    for p in FURNISH:
        page.evaluate("([id, rm, x, y, rot]) => H.put(id, rm, x + %d, y + %d, rot)" % (FT0, FT0), list(p))
    page.evaluate("() => { deselect(); select(-1, false); renderAll(); }")

def main():
    extra = sys.argv[3] if len(sys.argv) > 3 else ''
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=['--font-render-hinting=none'])
        ctx = b.new_context(viewport={'width': 1360, 'height': 860}, accept_downloads=True, device_scale_factor=1)
        ctx.add_init_script(INIT); ctx.route('**/*', route)
        page = ctx.new_page()
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))
        load(page, BASE + '/static/tools/floor-planner.html')
        cap(page, 'measure')
        page.evaluate("() => select(H.room('Bedroom'), false)"); cap(page, 'measure-bedroom')
        page.evaluate("() => select(-1, false)")
        page.click('[data-mode=furnish]'); cap(page, 'furnish-empty')
        furnish(page)
        cap(page, 'furnished')
        for rm in ['Living Room', 'Bedroom', 'Kitchen', 'Office']:
            page.evaluate("(n) => { select(H.room(n), false); showPane(); }", rm); cap(page, 'furnish-' + rm.split()[0].lower())
        page.evaluate("() => { select(-1, false); setTab('checks'); }"); cap(page, 'checks')
        page.evaluate("() => setTab('add')")
        # drag the dresser with the mouse, then Undo
        box = page.evaluate("""() => { var k = state.pieces.findIndex(p => p.type === 'dresser'); var q = piecePx(state.pieces[k]);
            var c = document.getElementById('planCanvas').getBoundingClientRect(); var s = c.width / state.W;
            return [c.left + q.cx * s, c.top + q.cy * s, s]; }""")
        page.mouse.move(box[0], box[1]); page.mouse.down(); page.mouse.move(box[0] - 40 * box[2], box[1] - 30 * box[2], steps=8); page.mouse.up()
        page.wait_for_timeout(100); cap(page, 'dragged')
        page.evaluate("() => undo()"); cap(page, 'undo')
        export(page, 'pngBtn', 'furnish-png')
        export(page, 'pdfBtn', 'furnish-pdf')
        # Light
        page.click('[data-mode=light]'); page.wait_for_timeout(200)
        page.evaluate("() => { var go = document.querySelector('[data-lact=lightup]'); if (go) go.click(); }"); page.wait_for_timeout(300)
        cap(page, 'light')
        for rm in ['Living Room', 'Kitchen', 'Dining Room', 'Bedroom', 'Bath', 'Office', 'Closet', 'Laundry', 'Hall', 'Flex Room']:
            page.evaluate("(n) => select(H.room(n), false)", rm); cap(page, 'light-' + rm.replace(' ', '-').lower(), shot=rm in ('Kitchen', 'Bedroom'))
        page.evaluate("() => { select(H.room('Bedroom'), false); state.lightMap = true; renderLight(); draw(); }"); cap(page, 'lightmap')
        page.evaluate("() => { state.lightMap = false; select(-1, false); renderLight(); draw(); }")
        export(page, 'pdfBtn', 'light-pdf')
        if extra: exec(open(os.path.join(H, extra)).read(), globals(), locals())
        # save, reload, reopen
        page.evaluate("() => document.getElementById('saveBtn').click()"); page.wait_for_selector('[data-act=new]')
        page.click('[data-act=new]'); page.wait_for_timeout(500)
        before = page.evaluate("() => snap()")
        page.goto(BASE + '/static/tools/floor-planner.html'); page.wait_for_selector('[data-open]')
        cap(page, 'start', text=False, state=False)
        page.click('[data-open] b'); page.wait_for_function("() => state.rooms.length && document.body.classList.contains('in-plan')"); page.wait_for_timeout(500)
        page.evaluate(HELP)
        after = page.evaluate("() => snap()")
        open(os.path.join(OUT, 'zz-reopen.txt'), 'w').write('identical\n' if before == after else 'DIFFERENT\n')
        cap(page, 'reopened')
        # recovery: a change, held still, then the page closes
        page.evaluate("() => { setMode('furnish'); H.put('plantS', 'Living Room', 14.5, 2.5, 0); deselect(); renderAll(); }")
        page.wait_for_timeout(2600)
        chg = page.evaluate("() => snap()")
        page.goto(BASE + '/static/tools/floor-planner.html'); page.wait_for_selector('[data-recover]')
        cap(page, 'recover-card', text=False, state=False)
        page.click('[data-recover] b'); page.wait_for_function("() => state.rooms.length && document.body.classList.contains('in-plan')"); page.wait_for_timeout(500)
        open(os.path.join(OUT, 'zz-recover.txt'), 'w').write('identical\n' if page.evaluate("() => snap()") == chg else 'DIFFERENT\n')
        # phone
        ph = b.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, device_scale_factor=2, accept_downloads=True)
        ph.add_init_script(INIT); ph.route('**/*', route)
        pp = ph.new_page(); pp.on('pageerror', lambda e: errs.append('phone: ' + str(e)))
        load(pp, BASE + '/static/tools/floor-planner.html'); pp.evaluate(HELP)
        pp.click('[data-mode=furnish]'); furnish(pp)
        pp.evaluate("() => { select(H.room('Bedroom'), false); showPane(); setSheet(true); }"); pp.wait_for_timeout(400)
        cap(pp, 'phone-furnish')
        if extra: open(os.path.join(OUT, 'zz-phone-hook'), 'w').write('')
        # the old parser page
        op = ctx.new_page(); op.on('pageerror', lambda e: errs.append('old: ' + str(e)))
        op.goto(BASE + '/static/tools/floor-plan-parser.html'); op.set_input_files('#fileInput', PLAN)
        op.wait_for_function("() => typeof state !== 'undefined' && state.rooms && state.rooms.length", timeout=60000); op.wait_for_timeout(800)
        N[0] += 1; op.screenshot(path=os.path.join(OUT, '%03d-old-page.png' % N[0]))
        open(os.path.join(OUT, 'zz-errors.txt'), 'w').write('\n'.join(errs) + '\n')
        b.close()
    print('captures:', len(os.listdir(OUT)), 'errors:', len(errs))

if __name__ == '__main__': main()
