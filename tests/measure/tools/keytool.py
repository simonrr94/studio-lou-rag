"""Answer keys for the Measure test plans.

A key (keys/<plan>.json) lists, in image pixels:
  ppf            pixels per foot
  thick          (optional) wall thickness threshold in px for the thick-ink mask (default 5)
  doors          [{type, a:[x,y], b:[x,y], into: room name or null (swing side), hinge: 'a'|'b'}]
  windows        [{a, b}]
  openings       [{a, b, rooms: [name, name]}]   a way through with no door
  splits         [{a, b}]   invisible lines that divide one open space between two named rooms
  rooms          [{name, seed:[x,y]}]
This tool closes every door, window, opening and split with a line, fills each room from its seed
inside the thick-wall mask, and writes the room outlines (polygons, px) back as keys/<plan>.out.json
plus an overlay picture to check by eye.
python3 keytool.py <plan>"""
import json, sys, os
import numpy as np, cv2

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
name = sys.argv[1]
key = json.load(open(os.path.join(D, 'keys', name + '.json')))
img = cv2.imread(os.path.join(D, 'plans', name + '.jpg'))
g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
dark = (g < key.get('dark', 110)).astype(np.uint8)
k = key.get('thick', 5)
walls = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
H, W = g.shape
block = walls.copy()
def seg(s, t=4, ext=4):
    a, b = np.array(s['a'], float), np.array(s['b'], float); u = (b - a) / max(1e-6, np.linalg.norm(b - a))
    cv2.line(block, tuple(map(int, a - u * ext)), tuple(map(int, b + u * ext)), 1, t)
for s in key.get('doors', []) + key.get('windows', []) + key.get('openings', []) + key.get('splits', []):
    seg(s)
for s in key.get('patches', []):   # drawing quirks (a white corner post): closed, not scored
    seg(s, 8)
# the outside: fill from the corner so each room's fill stops at the outer wall
out = {'ppf': key['ppf'], 'rooms': [], 'doors': key.get('doors', []), 'windows': key.get('windows', []), 'openings': key.get('openings', []),
       'splits': key.get('splits', [])}
vis = img.copy()
cols = [(80, 200, 80), (200, 120, 60), (60, 120, 220), (200, 60, 160), (60, 200, 200), (160, 160, 40), (120, 60, 200), (40, 140, 140), (220, 160, 120), (120, 200, 120)]
for i, r in enumerate(key['rooms']):
    m = np.zeros((H + 2, W + 2), np.uint8)
    fill = block.copy()
    cv2.floodFill(fill, m, tuple(r['seed']), 2)
    region = (fill == 2).astype(np.uint8)
    # furniture lines inside the room are thin and not in the wall mask, so the fill already covers them
    cs, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cs, key=cv2.contourArea)
    poly = cv2.approxPolyDP(c, 2.0, True)[:, 0, :].tolist()
    area_ft = region.sum() / key['ppf'] ** 2
    out['rooms'].append({'name': r['name'], 'poly': poly, 'area_sqft': round(area_ft, 1), 'printed': r.get('printed')})
    col = cols[i % len(cols)]
    ov = vis.copy(); ov[region == 1] = col
    vis = cv2.addWeighted(ov, 0.45, vis, 0.55, 0)
    cv2.polylines(vis, [np.array(poly)], True, col, 2)
    cv2.putText(vis, '%s %.0f' % (r['name'], area_ft), (r['seed'][0] - 30, r['seed'][1]), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
for s, col in [(x, (0, 140, 0)) for x in key.get('doors', [])] + [(x, (220, 120, 0)) for x in key.get('windows', [])] + \
              [(x, (0, 0, 220)) for x in key.get('openings', [])] + [(x, (160, 0, 160)) for x in key.get('splits', [])]:
    cv2.line(vis, tuple(map(int, s['a'])), tuple(map(int, s['b'])), col, 3)
json.dump(out, open(os.path.join(D, 'keys', name + '.out.json'), 'w'))
cv2.imwrite(os.path.join(D, 'keys', name + '.png'), vis)
for r in out['rooms']: print('%-18s %7.1f sq ft (printed %s) %d corners' % (r['name'], r['area_sqft'], r['printed'], len(r['poly'])))
