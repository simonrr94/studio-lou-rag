"""python3 runs.py plan.jpg r|c pos [pos...]  -> dark runs along rows (r) or columns (c)"""
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert('L'); W, H = im.size; px = im.load()
def runs(vals, minlen=1):
    out = []; s = None
    for i, v in enumerate(vals):
        if v and s is None: s = i
        if not v and s is not None: out.append((s, i - 1)); s = None
    if s is not None: out.append((s, len(vals) - 1))
    return [r for r in out if r[1] - r[0] + 1 >= minlen]
th = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[3] == 't' else 100
for p in sys.argv[3:]:
    p = int(p)
    if sys.argv[2] == 'r': print('row', p, runs([px[x, p] < th for x in range(W)]))
    else: print('col', p, runs([px[p, y] < th for y in range(H)]))
