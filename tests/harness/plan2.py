import sys, os, json, time
sys.argv=['x']
import run
from run import *
D=os.environ.get('PD','/home/claude/cabin')
run.ROOMS=open(D+'/rooms.json').read(); run.OPEN=open(D+'/openings.json').read(); run.PLAN=D+'/'+os.environ.get('IMG','cabin.jpg')
def load2(page, url):
    page.goto(url); page.wait_for_function("() => typeof state !== 'undefined'")
    page.set_input_files('#fileInput', run.PLAN)
    page.wait_for_function("() => state.rooms.length && state.openingsDone", timeout=60000); page.wait_for_timeout(800); page.evaluate(HELP)
with sync_playwright() as pw:
    b = pw.chromium.launch(); ctx = b.new_context(viewport={'width':1360,'height':860}); ctx.add_init_script(INIT); ctx.route('**/*', run.route)
    page = ctx.new_page(); page.on('pageerror', lambda e: print('ERR', e))
    load2(page, 'http://localhost:8001/static/tools/floor-planner.html')
    print(page.evaluate("() => JSON.stringify({scale: state.scale && [state.scale.ftPerPx, state.scale.from], rooms: state.rooms.map(r => [r.name, fmtFtIn(r.width||0), fmtFtIn(r.length||0)]), doors: state.doors.map(d => [d.type||'swing', Math.round(d.w), (roomById(d.room)||{}).name])})"))
    page.screenshot(path=D+'/measure.png')
    probe=os.environ.get('PROBE')
    if probe: print(page.evaluate(open(probe).read()))
    page.click('[data-mode=furnish]')
    page.evaluate("(n) => { select(H.room(n), false); showPane(); startLayouts(); }", os.environ.get('RM','Sleeping'))
    page.wait_for_function("() => state.layout && !state.layout.busy", timeout=60000)
    print(page.evaluate("() => JSON.stringify(state.layout.list.map(o => o.label + ' | ' + o.note).concat([state.layout.why]))"))
    page.screenshot(path=D+'/layouts.png')
    n = page.evaluate("() => state.layout.list.length")
    for k in range(n):
        page.click(f'[data-lay="{k}"]'); page.wait_for_timeout(150); page.screenshot(path=D+f'/opt{k}.png')
