"""python3 compare.py dirA dirB: lists captures that differ (or exist on one side only)."""
import os, sys, hashlib
A, B = sys.argv[1], sys.argv[2]
def h(p): return hashlib.md5(open(p, 'rb').read()).hexdigest()
fa, fb = set(os.listdir(A)), set(os.listdir(B))
same, diff = 0, []
for f in sorted(fa | fb):
    if f not in fa or f not in fb: diff.append(f + ' (only in ' + (A if f in fa else B) + ')'); continue
    if h(os.path.join(A, f)) == h(os.path.join(B, f)): same += 1
    else: diff.append(f)
print(same, 'identical,', len(diff), 'different')
for d in diff: print('  ', d)
