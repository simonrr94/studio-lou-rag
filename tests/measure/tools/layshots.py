"""Pictures of the suggested layouts, room by room, for comparing two versions of the page.
python3 layshots.py <base_url> <outdir> [plan ...]
Plans: the five real plans (stand-in model replies; CORE=1 recommended) and 'harness' (the drawn
10-room test plan in tests/harness) 'open' (the great room in tests/harness/open, make_open.py) and 'kd' (a kitchen/dining room, tests/harness/kd). For each room it writes <plan>-<room>.png: one panel per card
(the room cropped from the plan with the card's layout previewed), with the card's label and note
under it, plus <outdir>/cards.txt."""
import json, os, re, sys, time, textwrap
import cv2
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright
import score
D = score.D
BASE, OUT = sys.argv[1].rstrip('/'), sys.argv[2]
ONLY = sys.argv[3:]
os.makedirs(OUT, exist_ok=True)
HDIR = os.path.join(os.path.dirname(D), 'harness')
ROOMS = {'studio': ['Bedroom', 'Living Room'], 'cabin': ['Sleeping', 'Living'], 'twostory': ['Bedroom', 'Living Room'],
         'floor2': ['Primary Bedroom', 'Sitting Room'], 'bedroom': ['Bedroom'],
         'harness': ['Living Room', 'Dining Room', 'Office', 'Bedroom'], 'open': ['Living Room'], 'kd': ['Kitchen/Dining']}
try: FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 15); BOLD = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 16)
except Exception: FONT = BOLD = ImageFont.load_default()

def mocked(rj, oj, extra=None):
    def route(r, *_):
        u = r.request.url
        if 'onrender.com/api/vision' in u:
            body = json.loads(r.request.post_data or '{}')
            return r.fulfill(status=200, content_type='application/json', body=json.dumps({'content': [{'text': oj if 'door, doorway opening' in body.get('prompt', '') else rj}]}))
        if extra and extra in u: return r.abort()
        if u.startswith('http://localhost') or u.startswith('data:') or u.startswith('blob:'): return r.continue_()
        return r.abort()
    return route

CROP = """(n) => {
  var r = state.rooms.find(x => x.name === n), f = state.scale.ftPerPx, b = PLAN.bounds(r.ftShape), c = document.getElementById('planCanvas');
  var rc = c.getBoundingClientRect(), k = rc.width / state.W, pad = 2.5;
  return { x: rc.left + (b.x - pad) / f * k, y: rc.top + (b.y - pad) / f * k, width: (b.w + 2 * pad) / f * k, height: (b.h + 2 * pad) / f * k };
}"""

def panel(img_path, label, note, w=380):
    im = Image.open(img_path).convert('RGB')
    k = w / im.width; im = im.resize((w, max(1, int(im.height * k))))
    lines = textwrap.wrap(label, 38)[:2] + textwrap.wrap(note, 44)[:6]
    hh = im.height + 12 + 20 * len(lines) + 10
    out = Image.new('RGB', (w + 20, hh), '#FAF9F6'); out.paste(im, (10, 10))
    dr = ImageDraw.Draw(out); y = im.height + 18
    nl = len(textwrap.wrap(label, 38)[:2])
    for i, ln in enumerate(lines):
        dr.text((10, y), ln, fill='#433E3C' if i < nl else '#6b6560', font=BOLD if i < nl else FONT); y += 20
    return out

def sheet(panels, title, path):
    if not panels:
        panels = [Image.new('RGB', (400, 60), '#FAF9F6')]
    W = sum(p.width for p in panels); H = max(p.height for p in panels) + 34
    out = Image.new('RGB', (W, H), '#FAF9F6'); dr = ImageDraw.Draw(out); dr.text((10, 8), title, fill='#582b36', font=BOLD)
    x = 0
    for p in panels: out.paste(p, (x, 34)); x += p.width
    out.save(path)

def shoot(page, plan, rooms, log):
    page.evaluate("() => setMode('furnish')")
    for rm in rooms:
        i = page.evaluate("(n) => state.rooms.findIndex(r => r.name === n)", rm)
        if i < 0: log.write('%s %s: no such room\n' % (plan, rm)); continue
        t0 = time.time()
        if not page.evaluate("(i) => !!layoutKind(state.rooms[i])", i):
            slug = '%s-%s' % (plan, re.sub('[^a-z0-9]+', '-', rm.lower())); p = os.path.join(OUT, '_%s-x.png' % slug)
            page.evaluate("(i) => { select(i, false); draw(); }", i); page.wait_for_timeout(120)
            page.screenshot(path=p, clip=page.evaluate(CROP, rm))
            sheet([panel(p, 'No layouts offered', 'Suggest a layout is not offered for this room type.')], '%s, %s' % (plan, rm), os.path.join(OUT, slug + '.png'))
            log.write('%-9s %-16s not offered\n' % (plan, rm)); continue
        page.evaluate("(i) => { select(i, false); showPane(); startLayouts(); }", i)
        page.wait_for_function("() => state.layout && !state.layout.busy", timeout=120000)
        dt = time.time() - t0
        cards = page.evaluate("() => state.layout.list.map(o => [o.label, o.note])")
        why = page.evaluate("() => state.layout.why")
        slug = '%s-%s' % (plan, re.sub('[^a-z0-9]+', '-', rm.lower()))
        log.write('%-9s %-16s (%.1fs) %s\n' % (plan, rm, dt, ' | '.join('%s [%s]' % tuple(c) for c in cards) or 'WHY ' + str(why)))
        panels = []
        for k, (label, note) in enumerate(cards):
            page.evaluate("(k) => { state.layout.pick = k; renderLayouts(); draw(); }", k)
            page.wait_for_timeout(120)
            cr = page.evaluate(CROP, rm)
            p = os.path.join(OUT, '_%s-%d.png' % (slug, k))
            page.screenshot(path=p, clip=cr)
            panels.append(panel(p, label, note))
        if not cards:
            p = os.path.join(OUT, '_%s-x.png' % slug)
            page.evaluate("() => { state.layout = null; draw(); }")
            page.screenshot(path=p, clip=page.evaluate(CROP, rm))
            panels.append(panel(p, 'No layout', why or ''))
        page.evaluate("() => closeLayouts()")
        sheet(panels, '%s, %s' % (plan, rm), os.path.join(OUT, slug + '.png'))

with sync_playwright() as pw, open(os.path.join(OUT, 'cards.txt'), 'w') as log:
    b = pw.chromium.launch()
    for plan, rooms in ROOMS.items():
        if ONLY and plan not in ONLY: continue
        ctx = b.new_context(viewport={'width': 1360, 'height': 860}, device_scale_factor=2)
        page = ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))
        if plan in ('harness', 'open', 'kd'):
            hd = HDIR if plan == 'harness' else os.path.join(HDIR, plan)
            rj, oj = open(os.path.join(hd, 'rooms.json')).read(), open(os.path.join(hd, 'openings.json')).read()
            ctx.route('**/*', mocked(rj, oj)); img = os.path.join(hd, 'plan.png')
        else:
            key = json.load(open(os.path.join(D, 'keys', plan + '.json'))); out = json.load(open(os.path.join(D, 'keys', plan + '.out.json')))
            rj, oj = score.mock(plan, key, out, cv2.imread(os.path.join(D, 'plans', plan + '.jpg')))
            ctx.route('**/*', mocked(rj, oj)); img = os.path.join(D, 'plans', plan + '.jpg')
        page.goto(BASE + '/static/tools/floor-planner.html'); page.wait_for_function("() => typeof state !== 'undefined'")
        page.set_input_files('#fileInput', img)
        page.wait_for_function("() => state.rooms.length && (state.openingsDone || !state.scale)", timeout=60000); page.wait_for_timeout(800)
        shoot(page, plan, rooms, log); log.flush()
        if errs: log.write('          ERR %s\n' % errs[:2])
        ctx.close()
    b.close()
print(open(os.path.join(OUT, 'cards.txt')).read())
