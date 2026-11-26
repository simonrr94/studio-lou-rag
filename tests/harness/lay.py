import sys, os, json, time
sys.argv=['x']
from run import *
OUTD = os.environ.get('OUTD', 'lay-out'); os.makedirs(OUTD, exist_ok=True)
ROOMS_TO = os.environ.get('ROOMS', 'Bedroom').split(',')
FURN = os.environ.get('FURN') == '1'
VP = (390, 844) if os.environ.get('PHONE') else (1360, 860)
with sync_playwright() as pw:
    b = pw.chromium.launch(); ctx = b.new_context(viewport={'width':VP[0],'height':VP[1]}, is_mobile=bool(os.environ.get('PHONE')), has_touch=bool(os.environ.get('PHONE'))); ctx.add_init_script(INIT); ctx.route('**/*', route)
    page = ctx.new_page(); page.on('pageerror', lambda e: print('ERR', e)); page.on('console', lambda m: print('LOG', m.text) if m.type in ('error','warning') and 'Failed to load' not in m.text else None)
    load(page, 'http://localhost:8001/static/tools/floor-planner.html'); page.click('[data-mode=furnish]')
    if FURN: furnish(page)
    pre = os.environ.get('PRE')
    if pre: page.evaluate(pre)
    for rm in ROOMS_TO:
        page.evaluate("(n) => { select(H.room(n), false); showPane(); }", rm)
        t = time.time()
        page.evaluate("() => startLayouts()")
        page.wait_for_function("() => state.layout && !state.layout.busy", timeout=60000)
        print(rm, 'took %.2fs' % (time.time() - t))
        print(json.dumps(page.evaluate("() => state.layout.list.map(o => [o.label, o.note]).concat([state.layout.why])"), indent=0))
        slug = rm.replace(' ', '-').lower()
        page.screenshot(path=f'{OUTD}/{slug}-list.png')
        n = page.evaluate("() => state.layout.list.length")
        for k in range(n):
            page.click(f'[data-lay="{k}"]'); page.wait_for_timeout(150)
            page.screenshot(path=f'{OUTD}/{slug}-opt{k}.png')
