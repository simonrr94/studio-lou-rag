"""Layouts on rebuilds of Lauren's real plans (cabin and studio): python3 realplans.py"""
import subprocess, json, os
res = []
for pd, img, rm, want in [('/home/claude/cabin', 'cabin.jpg', 'Sleeping', 2), ('/home/claude/cabin', 'cabin.jpg', 'Living', 2),
                          ('/home/claude/studio', 'studio.jpg', 'Bedroom', 2)]:
    out = subprocess.run(['python3', 'plan2.py'], env=dict(os.environ, PD=pd, IMG=img, RM=rm), capture_output=True, text=True, timeout=300).stdout.strip().splitlines()[-1]
    lst = [x for x in json.loads(out) if x]
    res.append(('PASS' if len(lst) >= want and not lst[0].startswith('No ') else 'FAIL') + '  %s %s: %s' % (os.path.basename(pd), rm, json.dumps(lst)))
print('\n'.join(res))
