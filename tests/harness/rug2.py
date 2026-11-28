"""Two rugs in one room (a dining zone's rug in an open living room), on the great room plan (open/).
python3 rug2.py <base_url> <outdir>"""
import sys, os, json
BASE, OUTF = sys.argv[1].rstrip('/'), sys.argv[2]
sys.argv = ['x']
import run
from run import *
H0 = os.path.dirname(os.path.abspath(__file__))
run.ROOMS = open(os.path.join(H0, 'open', 'rooms.json')).read(); run.OPEN = open(os.path.join(H0, 'open', 'openings.json')).read()
run.PLAN = os.path.join(H0, 'open', 'plan.png'); run.OUT = OUTF; os.makedirs(OUTF, exist_ok=True)
R = []
def ok(name, cond, extra=''): R.append(('PASS' if cond else 'FAIL') + '  ' + name + (('  ' + extra) if extra else ''))
RUGPX = """(which) => { var r = state.rooms[H.room('Living Room')], h = which === 2 ? rugHolder2(r) : r, q = rugPx(h);
  var c = document.getElementById('planCanvas').getBoundingClientRect(), s = c.width / state.W;
  // a spot on the rug clear of the pieces on it: halfway between the middle and an edge
  return [c.left + (q.cx + q.w * 0.42 * (which === 2 ? 0 : 1)) * s, c.top + (q.cy + q.h * 0.42) * s, s]; }"""
with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--font-render-hinting=none'])
    ctx = b.new_context(viewport={'width': 1360, 'height': 860}, accept_downloads=True, device_scale_factor=1)
    ctx.add_init_script(INIT); ctx.route('**/*', run.route)
    page = ctx.new_page(); errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    run.load(page, BASE + '/static/tools/floor-planner.html')
    page.click('[data-mode=furnish]')
    page.evaluate("() => { select(H.room('Living Room'), false); showPane(); startLayouts(); }")
    page.wait_for_function("() => state.layout && !state.layout.busy", timeout=120000)
    k = page.evaluate("() => state.layout.list.findIndex(o => o.rug2)")
    ok('a zoned card brings a second rug', k > -1, json.dumps(page.evaluate("() => state.layout.list.map(o => [o.label, !!o.rug, !!o.rug2])")))
    page.click('[data-lay="%d"]' % k); page.wait_for_timeout(200); cap(page, 'preview')
    ok('the preview leaves the room as it was', page.evaluate("() => !state.rooms[H.room('Living Room')].rug2"))
    ok('the note counts both rugs', 'on a ' in page.evaluate("() => state.layout.list[%d].note" % k) or 'on an ' in page.evaluate("() => state.layout.list[%d].note" % k))
    s0 = page.evaluate("() => snap()")
    page.click('[data-lact=use]'); page.wait_for_timeout(300); cap(page, 'used')
    ok('Use this layout places both rugs', page.evaluate("() => { var r = state.rooms[H.room('Living Room')]; return !!(r.rug && r.rug2) && allRugs().length === 2; }"))
    page.evaluate("() => undo()")
    ok('one Undo takes both back', page.evaluate("() => snap()") == s0)
    page.evaluate("() => { select(H.room('Living Room'), false); showPane(); startLayouts(); }")
    page.wait_for_function("() => state.layout && !state.layout.busy", timeout=120000)
    page.click('[data-lay="%d"]' % k); page.click('[data-lact=use]'); page.wait_for_timeout(300)
    page.evaluate("() => { deselect(); select(H.room('Living Room'), false); renderAll(); }")
    # drag the second rug a foot; the main rug stays put
    before = page.evaluate("() => { var r = state.rooms[H.room('Living Room')]; return [r.rug.x, r.rug.y, r.rug2.x, r.rug2.y]; }")
    pt = page.evaluate(RUGPX, 2)
    page.evaluate("() => { state.pieceSel = -1; state.extra = []; }")
    hit = page.evaluate("([x, y]) => { var c = document.getElementById('planCanvas').getBoundingClientRect(), s = c.width / state.W; var h = hitRug({ x: (x - c.left) / s, y: (y - c.top) / s }); return h && h.id; }", pt[:2])
    ok('a tap on the second rug finds it', hit and hit.endswith('~2'), str(hit))
    # the rug is under its table and chairs, so pick a spot on the rug outside the chairs: its edge
    spot = page.evaluate("""() => { var r = state.rooms[H.room('Living Room')], h = rugHolder2(r), q = rugPx(h), c = document.getElementById('planCanvas').getBoundingClientRect(), s = c.width / state.W;
      for (var a = 0; a < 360; a += 15) { var rr = q.w / 2 - 4; var p = { x: q.cx + Math.cos(a * Math.PI / 180) * rr, y: q.cy + Math.sin(a * Math.PI / 180) * rr };
        if (hitPiece(p) < 0 && hitRug(p) === h) return [c.left + p.x * s, c.top + p.y * s, s]; } return null; }""")
    ok('a free spot on the second rug', spot is not None)
    if spot:
        page.mouse.move(spot[0], spot[1]); page.mouse.down(); page.mouse.move(spot[0] + 20 * spot[2], spot[1], steps=6); page.mouse.up(); page.wait_for_timeout(150)
        after = page.evaluate("() => { var r = state.rooms[H.room('Living Room')]; return [r.rug.x, r.rug.y, r.rug2.x, r.rug2.y]; }")
        ok('dragging moves the second rug only', after[:2] == before[:2] and after[2] != before[2], json.dumps([before, after]))
        cap(page, 'dragged')
        # Phase C: a tapped rug gets the floating toolbar (turn, remove); the Rugs tab is best fit and sizes only
        tb = page.evaluate("() => { var fb = document.getElementById('floatBar'); return [state.rugBar, !fb.classList.contains('hidden'), !!fb.querySelector('[data-fact=rugremove]')]; }")
        ok('the second rug gets the floating toolbar', tb[0] and str(tb[0]).endswith('~2') and tb[1] and tb[2], json.dumps(tb))
        cap(page, 'rugs-tab')
        page.keyboard.press('Delete'); page.wait_for_timeout(100)
        ok('Delete removes the second rug, not the first', page.evaluate("() => { var r = state.rooms[H.room('Living Room')]; return !!r.rug && !r.rug2; }"))
        page.evaluate("() => undo()")
        ok('Undo brings it back', page.evaluate("() => !!state.rooms[H.room('Living Room')].rug2"))
    page.evaluate("() => { deselect(); select(-1, false); renderAll(); }")
    export(page, 'pngBtn', 'png')
    pages = export(page, 'pdfBtn', 'pdf')
    txt = open([os.path.join(OUTF, f) for f in sorted(os.listdir(OUTF)) if f.endswith('-pdf.txt')][-1]).read()
    ok('the PDF lists both rugs', txt.count('Living Room') >= 2 and 'second rug' in txt)
    # save and reopen
    page.evaluate("() => document.getElementById('saveBtn').click()"); page.wait_for_selector('[data-act=new]'); page.click('[data-act=new]'); page.wait_for_timeout(500)
    s1 = page.evaluate("() => snap()")
    page.goto(BASE + '/static/tools/floor-planner.html'); page.wait_for_selector('[data-open]'); page.click('[data-open] b')
    page.wait_for_function("() => state.rooms.length && document.body.classList.contains('in-plan')"); page.wait_for_timeout(400); page.evaluate(HELP)
    ok('save and reopen keeps both rugs', page.evaluate("() => snap()") == s1 and page.evaluate("() => allRugs().length") == 2)
    cap(page, 'reopened')
    ok('no page errors', not errs, str(errs[:3]))
    # an old save (one rug per room, no rug2 anywhere) opens as before: the base page's save, opened here
    b.close()
print('\n'.join(R))
