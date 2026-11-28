# Tests for the Floor Planner (not served; for the build machine)

- `measure/`: the Measure test set. `plans/` are five real plans (studio, bedroom, cabin, two-story,
  Floor 2); `keys/<plan>.json` is the answer key (doors with swing, windows, openings, splits between
  open-plan rooms, a seed point per room), and `keys/<plan>.out.json` the room outlines worked out from
  it by `tools/keytool.py`. `tools/score.py <url> <outdir>` scores the page's Measure against the keys;
  `tools/proto.py` is the wall-first prototype.
- `harness/`: the page test harness (`run.py` regression captures, `feature.py` layout checks,
  `realplans.py` layouts on the cabin and studio, `kb.py` kitchens and baths (stools, runners, mats), `compare.py` to diff two runs). Paths inside assume
  the build sandbox (`/home/claude/...`); adjust when moving.
