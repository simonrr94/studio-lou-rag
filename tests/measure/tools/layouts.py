"""Suggested layouts on the five real plans, as Measure now reads them (stand-in model replies).
python3 layouts.py <base_url> : for every bedroom and living room, the cards it gets (or why none)."""
import json, os, sys
import cv2
from playwright.sync_api import sync_playwright
import score
D = score.D
BASE = sys.argv[1].rstrip('/')
ONLY = sys.argv[2:]
ROOMS = {'studio': ['Bedroom', 'Living Room'], 'cabin': ['Sleeping', 'Living'], 'twostory': ['Bedroom', 'Living Room'],
         'floor2': ['Primary Bedroom', 'Sitting Room'], 'bedroom': ['Bedroom']}
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for name, rooms in ROOMS.items():
        if ONLY and name not in ONLY: continue
        key = json.load(open(os.path.join(D, 'keys', name + '.json'))); out = json.load(open(os.path.join(D, 'keys', name + '.out.json')))
        rj, oj = score.mock(name, key, out, cv2.imread(os.path.join(D, 'plans', name + '.jpg')))
        ctx = b.new_context(viewport={'width': 1360, 'height': 860})
        def make(rj, oj):
          def route(r, *_):
            u = r.request.url
            if 'onrender.com/api/vision' in u:
                body = json.loads(r.request.post_data or '{}')
                return r.fulfill(status=200, content_type='application/json', body=json.dumps({'content': [{'text': oj if 'door, doorway opening' in body.get('prompt', '') else rj}]}))
            if u.startswith('http://localhost') or u.startswith('data:') or u.startswith('blob:'): return r.continue_()
            return r.abort()
          return route
        ctx.route('**/*', make(rj, oj))
        page = ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.goto(BASE + '/static/tools/floor-planner.html'); page.wait_for_function("() => typeof state !== 'undefined'")
        page.set_input_files('#fileInput', os.path.join(D, 'plans', name + '.jpg'))
        page.wait_for_function("() => state.rooms.length && (state.openingsDone || !state.scale)", timeout=60000); page.wait_for_timeout(800)
        page.evaluate("() => setMode('furnish')")
        for rm in rooms:
            i = page.evaluate("(n) => state.rooms.findIndex(r => r.name === n)", rm)
            page.evaluate("(i) => { select(i, false); startLayouts(); }", i)
            page.wait_for_function("() => state.layout && !state.layout.busy", timeout=90000)
            got = page.evaluate("() => state.layout.list.map(o => o.label).concat(state.layout.why ? ['WHY ' + state.layout.why] : [])")
            print('%-9s %-16s %s' % (name, rm, ' | '.join(got) or '(none)'))
        if errs: print('          ERR', errs[:2])
        ctx.close()
    b.close()
