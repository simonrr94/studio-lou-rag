"""Fireplace pinning (zones Z1): KITCHEN.find run in Node on tests/harness/fire and fire2 with the model's box nudged
(4 sets), against the drawn geometry. python3 fire.py [fire|fire2]"""
import json, sys, subprocess, cv2, os, random
HERE = os.path.dirname(os.path.abspath(__file__)); H0 = os.path.join(HERE, '..', '..', 'harness')
TRUTH = {  # face ends (px), wall, width in, depth in (from the face)
  'fire': {'face': [[95, 130], [95, 250]], 'wall': 'W', 'w': 72, 'd': 20},
  'fire2': {'face': [[220, 375], [340, 375]], 'wall': 'S', 'w': 72, 'd': 32},
}
for name in (sys.argv[1:] or ['fire', 'fire2']):
  for jit in [0, 1, 2, 3]:
    D = os.path.join(H0, name); img = cv2.imread(D + '/plan.png'); g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); H, W = g.shape
    rooms = json.load(open(D + '/rooms.json'))['rooms']; op = json.load(open(D + '/openings.json'))
    rr = [{'name': r['name'], 'bbox': r['bbox'], 'width': r['width_ft'], 'length': r['length_ft'], 'printedArea': None, 'source': r['source']} for r in rooms]
    rnd = random.Random(jit)
    fx = [dict(f) for f in op['fixtures']]
    for f in fx:  # the model's box, nudged up to 2% of the picture per side
        if jit: 
            for k in 'xy': f[k] += rnd.uniform(-2, 2)
            for k in 'wh': f[k] += rnd.uniform(-2, 2)
    base = '/tmp/fire_' + name
    open(base + '.gray', 'wb').write(g.tobytes())
    json.dump({'w': W, 'h': H, 'rooms': rr, 'hints': {'list': [o for o in op['openings']], 'overall': {'w': op['overall']['width_ft'], 'h': op['overall']['length_ft']}, 'dims': []}, 'fixtures': fx}, open(base + '.json', 'w'))
    out = subprocess.run(['node', os.path.join(HERE, 'fire', 'run.js'), os.path.join(HERE, '..', '..', '..', 'static', 'tools', 'plan-engine.js'), base], capture_output=True, text=True)
    if out.returncode: print(out.stderr[:800]); sys.exit()
    r = json.loads(out.stdout.strip().splitlines()[-1]); t = TRUTH[name]
    if not r['fx'] or r['fx'][0].get('rough'): print(name, jit, 'NOT FOUND', r); continue
    f = r['fx'][0]; fa, fb = f['face']
    off = max(abs(fa[0] - t['face'][0][0]) + abs(fa[1] - t['face'][0][1]), abs(fb[0] - t['face'][1][0]) + abs(fb[1] - t['face'][1][1]))
    print(name, 'jitter', jit, 'wall', f['wall'], t['wall'], '| breast', f['breast'], '| width', f['widthIn'], 'of', t['w'], '| depth', f['depthIn'], 'of', t['d'], '| face ends off px', round(off, 1))
