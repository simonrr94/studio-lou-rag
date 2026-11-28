"""The room read drawn on plans (zones Z1). python3 readshots.py <outdir> [plan ...]
Plans: harness folders (fire, fire2, open, kd, thin, harness) or the measure plans (studio, cabin, twostory, floor2, bedroom).
Serves from localhost:8001 (tests/harness/srv.sh)."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'harness')); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run
sys.argv, args = sys.argv[:1], sys.argv[1:]
import score, cv2
from playwright.sync_api import sync_playwright
BASE, OUT = 'http://localhost:8001', args[0]; PLANS = args[1:] or ['fire', 'fire2', 'open', 'kd', 'harness', 'studio', 'twostory', 'cabin', 'floor2']
os.makedirs(OUT, exist_ok=True)
H0 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'harness'); D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
def replies(name):
    if name == 'harness': return open(H0 + '/rooms.json').read(), open(H0 + '/openings.json').read(), H0 + '/plan.png'
    if os.path.isdir(os.path.join(H0, name)): d = os.path.join(H0, name); return open(d + '/rooms.json').read(), open(d + '/openings.json').read(), d + '/plan.png'
    key = json.load(open(f'{D}/keys/{name}.json')); out = json.load(open(f'{D}/keys/{name}.out.json'))
    for r in out['rooms']:
        kr = [k for k in key['rooms'] if k['name'] == r['name']][0]; r['minor'] = kr.get('minor', False)
    img = cv2.imread(f'{D}/plans/{name}.jpg'); rj, oj = score.mock(name, key, out, img); return rj, oj, f'{D}/plans/{name}.jpg'
with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--font-render-hinting=none'])
    for name in PLANS:
        rj, oj, img = replies(name)
        ctx = b.new_context(viewport={'width': 1360, 'height': 900}); ctx.add_init_script(run.INIT)
        def make(rj, oj):
          def route(r, *_):
            u = r.request.url
            if 'onrender.com/api/vision' in u:
                body = json.loads(r.request.post_data or '{}')
                return r.fulfill(status=200, content_type='application/json', body=json.dumps({'content': [{'text': oj if 'door, doorway opening' in body.get('prompt', '') else rj}]}))
            if u.startswith('http://localhost') or u.startswith('data:') or u.startswith('blob:'): return r.continue_()
            return r.abort()
          return route
        ctx.route('**/*', make(rj, oj)); page = ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.goto(BASE + '/static/tools/floor-planner.html'); page.wait_for_function("() => typeof state !== 'undefined'")
        page.set_input_files('#fileInput', img)
        page.wait_for_function("() => state.rooms.length && state.scale && state.openingsDone", timeout=60000); page.wait_for_timeout(800)
        info = page.evaluate("""() => { state.showRead = true; draw(); return state.rooms.map(r => { var rd = roomRead(r); return rd ? r.name + ': ' + Math.round(rd.area) + ' sq ft, focal ' + (rd.focal ? rd.focal.kind : 'none') + ', ' + rd.entries.length + ' ways in' + (rd.kitchen ? ' (kitchen)' : '') + ', pockets ' + rd.pockets.map(p => p.kind + ' ' + p.size.toFixed(1)).join(' / ') + ', sliver sq ft ' + Math.round(rd.slivers.length * 0.25) : r.name + ': -'; }).join('\\n'); }""")
        page.wait_for_timeout(200)
        el = page.query_selector('#planCanvas'); el.screenshot(path=os.path.join(OUT, name + '.png'))
        print('==', name, errs); print(info)
        ctx.close()
    b.close()
