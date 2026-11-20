/* =====================================================================
   STUDIO LOU PLAN ENGINE
   Shared by the Floor Plan Parser and the modes built on it
   (Measure, Furnish, Light, 3D). Plain JavaScript, no build step.

   SNAP   reads the plan image: wall map, printed room names, box snapping,
          and pixels per foot.
   PLAN   measurement and scale helpers that work in real feet, plus
          converting between the wall map and the displayed plan.
   RUG    standard rug sizes, which ones fit a room, and spacing lines.
   FURNITURE  the starter catalog and the geometry of placed pieces.

   When this file changes, bump the ?v= number on its <script> tag in
   floor-plan-parser.html so browsers fetch the new copy.
   ===================================================================== */

/* =====================================================================
   BOX SNAPPING
   The vision model reads names and dimensions well but places boxes
   loosely. So the page finds each room itself:
     1. Text recognition locates where each room's name is printed.
     2. From that spot, scans outward until it hits thick wall lines.
     3. Checks each box against the room's dimensions and rebuilds any
        side that leaked through a doorway or an open plan.
   ===================================================================== */
var SNAP = (function () {
  var OCR_WORKER = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/worker.min.js';
  var OCR_CORE = 'https://cdn.jsdelivr.net/npm/tesseract.js-core@5.1.1';
  var OCR_LANG = 'https://cdn.jsdelivr.net/npm/@tesseract.js-data/eng@1.0.0/4.0.0_best_int';
  var ANALYZE_SIZE = 1400; // longest side of the working copy, in px

  /* ---------- Image analysis ---------- */
  function analyze(img) {
    var s = ANALYZE_SIZE / Math.max(img.naturalWidth, img.naturalHeight);
    var w = Math.round(img.naturalWidth * s), h = Math.round(img.naturalHeight * s);
    var c = document.createElement('canvas');
    c.width = w; c.height = h;
    var ctx = c.getContext('2d');
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, w, h);
    ctx.drawImage(img, 0, 0, w, h);
    var px = ctx.getImageData(0, 0, w, h).data;

    // Dark pixel mask
    var dark = new Uint8Array(w * h);
    for (var i = 0, j = 0; i < dark.length; i++, j += 4) {
      var lum = 0.299 * px[j] + 0.587 * px[j + 1] + 0.114 * px[j + 2];
      dark[i] = lum < 110 ? 1 : 0;
    }
    // Integral image for fast box sums
    var W1 = w + 1, I = new Uint32Array(W1 * (h + 1));
    for (var y = 0; y < h; y++) {
      var row = 0;
      for (var x = 0; x < w; x++) {
        row += dark[y * w + x];
        I[(y + 1) * W1 + x + 1] = I[y * W1 + x + 1] + row;
      }
    }
    function full(x, y, k) { // is the k x k box centered here entirely dark?
      var r = k >> 1, x0 = x - r, y0 = y - r, x1 = x0 + k, y1 = y0 + k;
      if (x0 < 0 || y0 < 0 || x1 > w || y1 > h) return false;
      return I[y1 * W1 + x1] - I[y0 * W1 + x1] - I[y1 * W1 + x0] + I[y0 * W1 + x0] === k * k;
    }

    // Wall thickness: the largest box size that still fits inside a meaningful
    // amount of dark ink. Text and fixtures are thin, so they drop out first.
    var minCount = Math.max(60, Math.round(w * h * 0.0012 / 9)); // sampled every 3px
    var kMax = 0;
    for (var k = 3; k <= 60; k += 1) {
      var count = 0;
      for (var yy = 0; yy < h; yy += 3) for (var xx = 0; xx < w; xx += 3) if (dark[yy * w + xx] && full(xx, yy, k)) count++;
      if (count >= minCount) kMax = k; else break;
    }
    var kUse = Math.max(6, Math.round(kMax * 0.35));
    var wall = new Uint8Array(w * h);
    for (var y2 = 0; y2 < h; y2++) for (var x2 = 0; x2 < w; x2++) {
      if (dark[y2 * w + x2] && full(x2, y2, kUse)) wall[y2 * w + x2] = 1;
    }
    return { w: w, h: h, scale: s, wall: wall, k: kUse, kMax: kMax, canvas: c };
  }

  /* ---------- Text recognition ---------- */
  function ocr(canvas) {
    if (typeof Tesseract === 'undefined') return Promise.resolve([]);
    var worker;
    return Tesseract.createWorker('eng', 1, { workerPath: OCR_WORKER, corePath: OCR_CORE, langPath: OCR_LANG, gzip: true })
      .then(function (wk) { worker = wk; return worker.setParameters({ tessedit_pageseg_mode: '11' }); })
      .then(function () { return worker.recognize(canvas); })
      .then(function (res) {
        worker.terminate();
        return (res.data.words || []).filter(function (wd) { return wd.confidence > 30 && /[a-z]{3,}/i.test(wd.text); })
          .map(function (wd) {
            return { text: wd.text.replace(/[^a-z]/gi, '').toLowerCase(), x: (wd.bbox.x0 + wd.bbox.x1) / 2, y: (wd.bbox.y0 + wd.bbox.y1) / 2 };
          });
      })
      .catch(function () { try { worker && worker.terminate(); } catch (e) {} return []; });
  }

  function similarity(a, b) {
    if (a === b) return 1;
    var m = a.length, n = b.length, d = [];
    for (var i = 0; i <= m; i++) { d[i] = [i]; }
    for (var j = 1; j <= n; j++) d[0][j] = j;
    for (i = 1; i <= m; i++) for (j = 1; j <= n; j++) {
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    return 1 - d[m][n] / Math.max(m, n);
  }

  var GENERIC = { vaulted: 1, room: 1, the: 1, and: 1, sq: 1, ft: 1 };
  // Find where this room's name is printed. Ties go to the word closest to the model's guess.
  function findLabel(room, words, guess) {
    var tokens = String(room.label || room.name).toLowerCase().split(/[^a-z]+/).filter(function (t) { return t.length >= 3 && !GENERIC[t]; });
    var best = null, bestScore = -1;
    tokens.forEach(function (t) {
      words.forEach(function (wd) {
        if (wd.used) return;
        var sim = similarity(t, wd.text);
        if (sim < 0.7) return;
        var dist = Math.hypot(wd.x - guess.x, wd.y - guess.y) / Math.hypot(guess.w, guess.h);
        var score = sim * 2 + t.length / 10 - dist;
        if (score > bestScore) { bestScore = score; best = wd; }
      });
    });
    return best;
  }

  /* ---------- Wall scanning ---------- */
  function isWall(a, x, y) { return a.wall[(y | 0) * a.w + (x | 0)] === 1; }

  // Walk from (x,y) in direction (dx,dy). Returns the inner face of the first wall, or null.
  function ray(a, x, y, dx, dy) {
    var r = Math.ceil(a.k / 2);
    while (true) {
      x += dx; y += dy;
      if (x < 0 || y < 0 || x >= a.w || y >= a.h) return null;
      if (isWall(a, x, y)) return dx ? x - dx * r : y - dy * r;
    }
  }
  // Rays that pass through a window or doorway land somewhere else (or nowhere).
  // The wall is where a solid group of rays agree, even if it's only a third of them.
  function agree(arr, tol, seedPos) {
    var v = arr.filter(function (n) { return n != null; }).sort(function (p, q) { return p - q; });
    var best = null, bestN = 0, bestD = Infinity;
    for (var i = 0; i < v.length; i++) {
      var grp = v.filter(function (n) { return Math.abs(n - v[i]) <= tol; });
      var d = Math.abs(v[i] - seedPos);
      if (grp.length > bestN || (grp.length === bestN && d < bestD)) { best = grp; bestN = grp.length; bestD = d; }
    }
    if (!best || bestN < Math.max(2, Math.ceil(arr.length * 0.25))) return null;
    return best[Math.floor(best.length / 2)];
  }
  // Several parallel rays per side, so a doorway or window in one spot can't throw the box off.
  function scanSide(a, rect, side, seed) {
    var hits = [], n = 13, tol = Math.max(4, a.k);
    for (var i = 0; i < n; i++) {
      var f = 0.15 + 0.7 * i / (n - 1);
      if (side === 'l' || side === 'r') {
        var yy = rect.t + (rect.b - rect.t) * f;
        hits.push(ray(a, seed.x, yy, side === 'l' ? -1 : 1, 0));
      } else {
        var xx = rect.l + (rect.r - rect.l) * f;
        hits.push(ray(a, xx, seed.y, 0, side === 't' ? -1 : 1));
      }
    }
    return agree(hits, tol, side === 'l' || side === 'r' ? seed.x : seed.y);
  }
  function snapFrom(a, seed) {
    // Step off any wall pixel the seed landed on
    if (isWall(a, seed.x, seed.y)) {
      var found = false;
      for (var rad = 2; rad < 40 && !found; rad += 2) {
        for (var ang = 0; ang < 8 && !found; ang++) {
          var nx = seed.x + Math.cos(ang * Math.PI / 4) * rad, ny = seed.y + Math.sin(ang * Math.PI / 4) * rad;
          if (nx > 0 && ny > 0 && nx < a.w && ny < a.h && !isWall(a, nx, ny)) { seed = { x: nx, y: ny }; found = true; }
        }
      }
      if (!found) return null;
    }
    var rect = {
      l: ray(a, seed.x, seed.y, -1, 0), r: ray(a, seed.x, seed.y, 1, 0),
      t: ray(a, seed.x, seed.y, 0, -1), b: ray(a, seed.x, seed.y, 0, 1)
    };
    for (var pass = 0; pass < 3; pass++) {
      var cur = { l: rect.l == null ? seed.x - 1 : rect.l, r: rect.r == null ? seed.x + 1 : rect.r,
                  t: rect.t == null ? seed.y - 1 : rect.t, b: rect.b == null ? seed.y + 1 : rect.b };
      rect = { l: scanSide(a, cur, 'l', seed), r: scanSide(a, cur, 'r', seed), t: scanSide(a, cur, 't', seed), b: scanSide(a, cur, 'b', seed) };
    }
    return rect;
  }

  /* ---------- Putting it together ---------- */
  // rooms: parsed rooms with bbox in percent. Returns the same rooms with improved bboxes.
  function place(rooms, a, words) {
    var toPx = function (r) { return { x: (r.bbox.x + r.bbox.w / 2) / 100 * a.w, y: (r.bbox.y + r.bbox.h / 2) / 100 * a.h, w: r.bbox.w / 100 * a.w, h: r.bbox.h / 100 * a.h }; };
    var work = rooms.map(function (r) {
      var guess = toPx(r);
      var lab = words.length ? findLabel(r, words, guess) : null;
      if (lab) lab.used = true;
      var seed = lab ? { x: lab.x, y: lab.y } : { x: guess.x, y: guess.y };
      return { room: r, guess: guess, seed: seed, anchored: !!lab, rect: snapFrom(a, seed) };
    });

    // Pixels per foot, from rooms whose snapped box agrees with their own dimensions
    var cands = [], voters = 0;
    work.forEach(function (it) {
      var r = it.room, q = it.rect;
      if (!q || q.l == null || q.r == null || q.t == null || q.b == null || !r.width || !r.length) return;
      var pw = q.r - q.l, ph = q.b - q.t;
      var before = cands.length;
      [[r.width, r.length], [r.length, r.width]].forEach(function (d) {
        var sx = pw / d[0], sy = ph / d[1];
        if (Math.abs(sx / sy - 1) < 0.12) cands.push((sx + sy) / 2);
      });
      if (cands.length > before) voters++; // rooms that agreed on the scale
    });
    // Printed areas beat dimension lines when the plan has them: a box's size
    // against its printed sq ft isn't thrown off by dimension lines that measure
    // outside the walls or only part of an L-shaped room. Rooms whose printed
    // area agrees with their own dimensions are trusted first; if none agree,
    // every room with a printed area votes.
    var trusted = [], all = [];
    work.forEach(function (it) {
      var r = it.room, q = it.rect;
      if (!r.printedArea || !q || q.l == null || q.r == null || q.t == null || q.b == null) return;
      var c = Math.sqrt((q.r - q.l) * (q.b - q.t) / r.printedArea);
      all.push(c);
      if (!r.width || !r.length || Math.abs(r.width * r.length / r.printedArea - 1) <= 0.10) trusted.push(c);
    });
    var areaCands = trusted.length ? trusted : all;
    if (areaCands.length) { cands = areaCands; voters = areaCands.length; }
    var ppfFrom = areaCands.length ? 'area' : 'dims';

    cands.sort(function (p, q) { return p - q; });
    var ppf = cands.length ? cands[Math.floor(cands.length / 2)] : null;

    work.forEach(function (it) {
      var r = it.room, q = it.rect, g = it.guess;
      if (!q) return; // could not scan at all: keep the model's box
      // If the drawing is rotated relative to how the model reported width/length, swap them
      if (ppf && r.width && r.length && q.l != null && q.r != null && q.t != null && q.b != null) {
        var pw = q.r - q.l, ph = q.b - q.t;
        var errA = Math.abs(pw / (r.width * ppf) - 1) + Math.abs(ph / (r.length * ppf) - 1);
        var errB = Math.abs(pw / (r.length * ppf) - 1) + Math.abs(ph / (r.width * ppf) - 1);
        if (errB < 0.25 && errB + 0.15 < errA) { var tmp = r.width; r.width = r.length; r.length = tmp; }
      }
      var yLo = q.t != null ? q.t : g.y - g.h / 2, yHi = q.b != null ? q.b : g.y + g.h / 2;
      var x = fixAxis(q.l, q.r, it.seed.x, r.width, ppf, g.x - g.w / 2, g.x + g.w / 2, a.w,
        function (pos) { return wallNear(a, pos, yLo, yHi, true); });
      var y = fixAxis(q.t, q.b, it.seed.y, r.length, ppf, g.y - g.h / 2, g.y + g.h / 2, a.h,
        function (pos) { return wallNear(a, pos, x[0], x[1], false); });
      r.bbox = { x: x[0] / a.w * 100, y: y[0] / a.h * 100, w: (x[1] - x[0]) / a.w * 100, h: (y[1] - y[0]) / a.h * 100 };
      r.snapped = true;
    });
    return { rooms: rooms, ppf: ppf, ppfRooms: ppf ? voters : 0, ppfFrom: ppf ? ppfFrom : null, wallPx: a.k };
  }

  // Share of a box edge that sits on a wall: samples along the edge, looking a few px either side.
  function wallNear(a, pos, from, to, vertical) {
    var n = 15, hit = 0, tol = Math.max(4, a.k);
    if (pos < 0 || (vertical ? pos >= a.w : pos >= a.h)) return 0;
    for (var i = 0; i < n; i++) {
      var u = from + (to - from) * (0.1 + 0.8 * i / (n - 1));
      for (var d = -tol; d <= tol + a.k; d++) {
        var p1 = pos + d, p2 = pos - d;
        if ((vertical ? (isWall(a, p1, u) || isWall(a, p2, u)) : (isWall(a, u, p1) || isWall(a, u, p2)))) { hit++; break; }
      }
    }
    return hit / n;
  }

  // One axis of a box: keep both scanned walls if they match the room's dimension.
  // Otherwise measure the dimension out from one wall, choosing the side whose
  // far edge actually lands on a wall (open plans and doorways leak on the other).
  function fixAxis(lo, hi, seed, ft, ppf, gLo, gHi, max, probe) {
    var want = ft && ppf ? ft * ppf : null;
    if (lo != null && hi != null) {
      if (!want || Math.abs((hi - lo) / want - 1) < 0.2) return [lo, hi];
    }
    if (want) {
      var opts = [];
      if (lo != null && lo + want <= max + 2) opts.push({ span: [lo, Math.min(max, lo + want)], score: probe(lo + want), dist: seed - lo });
      if (hi != null && hi - want >= -2) opts.push({ span: [Math.max(0, hi - want), hi], score: probe(hi - want), dist: hi - seed });
      if (opts.length) {
        opts.sort(function (p, q) { return (q.score - p.score) || (p.dist - q.dist); });
        return opts[0].span;
      }
      if (lo != null) return [lo, Math.min(max, lo + want)];
      if (hi != null) return [Math.max(0, hi - want), hi];
      return [Math.max(0, seed - want / 2), Math.min(max, seed + want / 2)];
    }
    // No scale to check against: use whatever walls were found, the model's guess for the rest
    return [lo != null ? lo : Math.max(0, gLo), hi != null ? hi : Math.min(max, gHi)];
  }

  return { analyze: analyze, ocr: ocr, place: place };
})();

/* =====================================================================
   PLAN: measurement and scale
   Room boxes stay in percent of the image, as before. The scale is one
   number, feet per pixel of the displayed plan canvas (state.W x state.H),
   so any box can be turned into feet with boxFt().
   ===================================================================== */
var PLAN = (function () {
  var MISMATCH = 0.10; // flag rooms whose box and plan dimensions differ by more than 10%

  /* ---------- Feet and inches ---------- */
  function fmtFtIn(ft) {
    if (ft == null || isNaN(ft)) return '';
    var total = Math.round(ft * 12);
    var f = Math.floor(total / 12), i = total % 12;
    return i ? f + "'" + i + '"' : f + "'";
  }
  function parseFtIn(str) {
    if (str == null) return null;
    var s = String(str).trim().toLowerCase()
      .replace(/[’′]/g, "'").replace(/[”″]/g, '"')
      .replace(/feet|foot|ft/g, "'").replace(/inches|inch|in/g, '"').replace(/-/g, ' ');
    if (!s) return null;
    var m = s.match(/^(\d+(?:\.\d+)?)\s*'?\s*(?:(\d+(?:\.\d+)?)\s*"?)?$/);
    if (m) {
      var ft = parseFloat(m[1]), inch = m[2] ? parseFloat(m[2]) : 0;
      if (inch >= 12) return null;
      return ft + inch / 12;
    }
    m = s.match(/^(\d+(?:\.\d+)?)\s*"$/);  // inches only, e.g. 150"
    if (m) return parseFloat(m[1]) / 12;
    return null;
  }
  // Which number is the room's sq ft, in order:
  //   1. the plan's printed area, until the person edits the dimensions
  //   2. dimensions the person typed
  //   3. the shape the person drew (needs a scale; see syncGeometry on the page)
  //   4. width x length from the plan
  function area(r) {
    if (r.printedArea && !r.dimsEdited) return r.printedArea;
    if (r.dimsEdited) return dimsArea(r);
    if (r.shape && r.shapeArea) return r.shapeArea;
    return dimsArea(r);
  }
  function dimsArea(r) { return (r.width && r.length) ? r.width * r.length : 0; }
  // Width x length vs the printed area, when they disagree by more than 10%
  function areaConflict(r) {
    if (!r.printedArea || r.dimsEdited || !dimsArea(r)) return null;
    var d = dimsArea(r);
    return Math.abs(d / r.printedArea - 1) > MISMATCH ? { printed: r.printedArea, dims: d } : null;
  }
  function fmtArea(a) { return Math.round(a).toLocaleString() + ' sq ft'; }

  /* ---------- Scale ---------- */
  // ppf is measured on SNAP's working copy (analysisW px wide). The displayed
  // canvas is displayW px wide, so convert to feet per displayed pixel.
  function scaleFromAnalysis(ppf, analysisW, displayW) {
    if (!ppf || !analysisW || !displayW) return null;
    return analysisW / (ppf * displayW);
  }
  // A line drawn on the plan (displayed canvas px) and its real length in feet
  function scaleFromLine(p1, p2, feet) {
    var len = Math.hypot(p2.x - p1.x, p2.y - p1.y);
    if (!len || !feet || feet <= 0) return null;
    return feet / len;
  }

  /* ---------- Boxes in feet ---------- */
  // bbox in percent of the image -> feet, measured from the image's top left corner
  function boxFt(bbox, ftPerPx, W, H) {
    if (!bbox || !ftPerPx) return null;
    return {
      x: bbox.x / 100 * W * ftPerPx, y: bbox.y / 100 * H * ftPerPx,
      w: bbox.w / 100 * W * ftPerPx, h: bbox.h / 100 * H * ftPerPx
    };
  }
  // The box is the truth for placing things. Returns null when the box agrees
  // with the room's plan dimensions (either way round), otherwise the box size.
  function mismatch(room, ftBox) {
    if (!ftBox || !room.width || !room.length) return null;
    function off(a, b) { return Math.abs(a / b - 1); }
    var same = Math.max(off(ftBox.w, room.width), off(ftBox.h, room.length));
    var turned = Math.max(off(ftBox.w, room.length), off(ftBox.h, room.width));
    if (Math.min(same, turned) <= MISMATCH) return null;
    return { w: ftBox.w, h: ftBox.h };
  }

  /* ---------- Room shapes ----------
     A room is a rectangle (its bbox) until the person adds a corner. Then it
     carries shape: a list of corner points in percent of the image, in order
     around the room. bbox always stays the shape's bounding box. */
  function rectPoints(b) {
    return [{ x: b.x, y: b.y }, { x: b.x + b.w, y: b.y }, { x: b.x + b.w, y: b.y + b.h }, { x: b.x, y: b.y + b.h }];
  }
  function bounds(pts) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    pts.forEach(function (p) { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y); });
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  // Four corners lined up with the image: a plain rectangle again
  function isRect(pts) {
    if (pts.length !== 4) return false;
    var b = bounds(pts), e = 0.05;
    return pts.every(function (p) {
      return (Math.abs(p.x - b.x) < e || Math.abs(p.x - b.x - b.w) < e) && (Math.abs(p.y - b.y) < e || Math.abs(p.y - b.y - b.h) < e);
    }) && b.w > 0 && b.h > 0 && pts[0].x !== pts[2].x;
  }
  function pointInPoly(p, pts) {
    var inside = false;
    for (var i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      var a = pts[i], b = pts[j];
      if ((a.y > p.y) !== (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) inside = !inside;
    }
    return inside;
  }
  // Points in percent -> points in feet from the image's top left corner
  function shapeFt(pts, ftPerPx, W, H) {
    if (!pts || !ftPerPx) return null;
    return pts.map(function (p) { return { x: p.x / 100 * W * ftPerPx, y: p.y / 100 * H * ftPerPx }; });
  }
  // Area of a polygon (points in feet), shoelace formula
  function polyArea(ft) {
    if (!ft || ft.length < 3) return 0;
    var s = 0;
    for (var i = 0, j = ft.length - 1; i < ft.length; j = i++) s += (ft[j].x + ft[i].x) * (ft[j].y - ft[i].y);
    return Math.abs(s / 2);
  }
  // A drawn shape against the plan's printed area, when they disagree by more than 10%
  function shapeConflict(r) {
    if (!r.shape || !r.shapeArea || !r.printedArea || r.dimsEdited) return null;
    return Math.abs(r.shapeArea / r.printedArea - 1) > MISMATCH ? { printed: r.printedArea, shape: r.shapeArea } : null;
  }

  /* ---------- Wall map in plan coordinates ----------
     SNAP's wall map is measured on a working copy 1400px on its longest side,
     while everything else is measured on the displayed plan (state.W px wide).
     It's the same image at a different size, so one ratio converts between them.
     walls is state.walls ({ map, words }). */
  function wallRatio(walls, displayW) { return walls && walls.map && displayW ? walls.map.w / displayW : null; }
  // Is there wall ink at this point on the displayed plan?
  function wallAt(walls, x, y, displayW) {
    var k = wallRatio(walls, displayW);
    if (!k) return false;
    var a = walls.map, wx = Math.floor(x * k), wy = Math.floor(y * k);
    if (wx < 0 || wy < 0 || wx >= a.w || wy >= a.h) return false;
    return a.wall[wy * a.w + wx] === 1;
  }
  // Points between the two systems
  function toWallPx(p, walls, displayW) { var k = wallRatio(walls, displayW); return k ? { x: p.x * k, y: p.y * k } : null; }
  function fromWallPx(p, walls, displayW) { var k = wallRatio(walls, displayW); return k ? { x: p.x / k, y: p.y / k } : null; }

  return {
    MISMATCH: MISMATCH,
    rectPoints: rectPoints, bounds: bounds, isRect: isRect, pointInPoly: pointInPoly,
    shapeFt: shapeFt, polyArea: polyArea, shapeConflict: shapeConflict,
    fmtFtIn: fmtFtIn, parseFtIn: parseFtIn, area: area, dimsArea: dimsArea, areaConflict: areaConflict, fmtArea: fmtArea,
    scaleFromAnalysis: scaleFromAnalysis, scaleFromLine: scaleFromLine,
    boxFt: boxFt, mismatch: mismatch,
    wallRatio: wallRatio, wallAt: wallAt, toWallPx: toWallPx, fromWallPx: fromWallPx
  };
})();

/* =====================================================================
   RUG: which standard rug sizes fit a room, and where
   Everything here works in feet, on a room's outline (r.ftShape), so it
   handles L-shaped and other drawn shapes, not only boxes. The code only
   measures and reports; the person decides where the rug goes.
   ===================================================================== */
var RUG = (function () {
  var SIZES = [
    { id: '5x8', label: "5' x 8'", w: 5, h: 8 },
    { id: '6x9', label: "6' x 9'", w: 6, h: 9 },
    { id: '8x10', label: "8' x 10'", w: 8, h: 10 },
    { id: '9x12', label: "9' x 12'", w: 9, h: 12 },
    { id: '10x14', label: "10' x 14'", w: 10, h: 14 },
    { id: '6r', label: "6' round", d: 6 },
    { id: '8r', label: "8' round", d: 8 }
  ];
  var COMFORT = 1;   // 12" of floor between rug and walls
  var TIGHT = 0.5;   // 6" or more still works, just tight
  var EPS = 1e-6;

  function get(id) { for (var i = 0; i < SIZES.length; i++) if (SIZES[i].id === id) return SIZES[i]; return null; }
  function sizeArea(s) { return s.d ? Math.PI * s.d * s.d / 4 : s.w * s.h; }
  // Footprint in feet on the plan: rot 90 turns a rectangle on its side
  function footprint(s, rot) {
    if (s.d) return { w: s.d, h: s.d, round: true };
    return ((rot || 0) % 180 + 180) % 180 === 90 ? { w: s.h, h: s.w } : { w: s.w, h: s.h };
  }
  // A rug turned to any angle (not just straight or a quarter turn), the way it sits in a
  // turned seating group: true when the rug is square to the plan, so the exact boxed math applies
  function square(rot) { return ((rot || 0) % 90 + 90) % 90 === 0; }
  // Its outline in feet, corners going clockwise
  function outline(s, rot, cx, cy) {
    if (s.d) { var o = []; for (var i = 0; i < 32; i++) { var a = i / 32 * Math.PI * 2; o.push({ x: cx + Math.cos(a) * s.d / 2, y: cy + Math.sin(a) * s.d / 2 }); } return o; }
    return GEO.place([{ x: -s.w / 2, y: -s.h / 2 }, { x: s.w / 2, y: -s.h / 2 }, { x: s.w / 2, y: s.h / 2 }, { x: -s.w / 2, y: s.h / 2 }], cx, cy, rot || 0, 1);
  }

  // Room type from its name, for the advice shown with the sizes
  function roomType(name) {
    var n = String(name || '').toLowerCase();
    if (/bath|powder|closet|wic|laundry|pantry|kitchen|hall|garage|stair|utility|mud/.test(n)) return 'other';
    if (/dining|breakfast/.test(n)) return 'dining';
    if (/bed|primary|master|sleep|guest|nursery|kid/.test(n)) return 'bedroom';
    if (/living|family|great|den|lounge|sitting|media|bonus|rec\b|loft/.test(n)) return 'living';
    return 'other';
  }

  /* ---------- Geometry (feet) ---------- */
  function ptSegDist(p, a, b) {
    var dx = b.x - a.x, dy = b.y - a.y, L = dx * dx + dy * dy;
    var t = L ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / L)) : 0;
    return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
  }
  function ptRectDist(p, r) {
    var dx = Math.max(r.x0 - p.x, 0, p.x - r.x1), dy = Math.max(r.y0 - p.y, 0, p.y - r.y1);
    return Math.hypot(dx, dy);
  }
  function cross(o, a, b) { return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x); }
  function segsCross(a, b, c, d) {
    var d1 = cross(c, d, a), d2 = cross(c, d, b), d3 = cross(a, b, c), d4 = cross(a, b, d);
    return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
  }
  function rectCorners(r) { return [{ x: r.x0, y: r.y0 }, { x: r.x1, y: r.y0 }, { x: r.x1, y: r.y1 }, { x: r.x0, y: r.y1 }]; }
  // Shortest distance between a rectangle and a wall segment (0 if they touch)
  function rectSegDist(r, a, b) {
    var inA = a.x > r.x0 && a.x < r.x1 && a.y > r.y0 && a.y < r.y1;
    var inB = b.x > r.x0 && b.x < r.x1 && b.y > r.y0 && b.y < r.y1;
    if (inA || inB) return 0;
    var cs = rectCorners(r);
    for (var i = 0; i < 4; i++) if (segsCross(a, b, cs[i], cs[(i + 1) % 4])) return 0;
    var d = Math.min(ptRectDist(a, r), ptRectDist(b, r));
    cs.forEach(function (c) { d = Math.min(d, ptSegDist(c, a, b)); });
    return d;
  }

  // Floor left between the rug and the nearest wall, in feet, with the rug
  // centered at (cx, cy). Negative when the rug runs past the room's outline.
  function clearanceAt(poly, s, rot, cx, cy) {
    var f = footprint(s, rot), n = poly.length, d = Infinity, i;
    if (f.round) {
      var c = { x: cx, y: cy }, r = f.w / 2;
      if (!PLAN.pointInPoly(c, poly)) return -r;
      for (i = 0; i < n; i++) d = Math.min(d, ptSegDist(c, poly[i], poly[(i + 1) % n]));
      return d - r;
    }
    if (!square(rot)) {
      // Turned: the rug's corners against the room's walls, and the room's corners against the rug's edges
      var rp = outline(s, rot, cx, cy), out = rp.some(function (p) { return !PLAN.pointInPoly(p, poly); }) ||
        poly.some(function (v) { return PLAN.pointInPoly(v, rp); });
      rp.forEach(function (p) { d = Math.min(d, GEO.edgeDist(p, poly)); });
      poly.forEach(function (v) { d = Math.min(d, GEO.edgeDist(v, rp)); });
      return out ? -Math.max(d, 0.01) : d;
    }
    var rect = { x0: cx - f.w / 2, y0: cy - f.h / 2, x1: cx + f.w / 2, y1: cy + f.h / 2 };
    var outside = rectCorners(rect).some(function (p) { return !PLAN.pointInPoly(p, poly); });
    for (i = 0; i < n; i++) d = Math.min(d, rectSegDist(rect, poly[i], poly[(i + 1) % n]));
    return outside ? -Math.max(d, 0.01) : d;
  }

  // Where this rug leaves the most floor at the walls. Ties go to the spot
  // closest to the middle of the room, so the rug doesn't hug one end.
  function bestSpot(poly, s) {
    var b = PLAN.bounds(poly), mid = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
    var rots = s.d ? [0] : [0, 90], best = null;
    function consider(rot, x, y) {
      var c = clearanceAt(poly, s, rot, x, y);
      var dm = Math.hypot(x - mid.x, y - mid.y);
      if (!best || c > best.clearance + 0.005 || (Math.abs(c - best.clearance) <= 0.005 && dm < best.dm)) {
        best = { rot: rot, cx: x, cy: y, clearance: c, dm: dm };
      }
    }
    // Coarse grid over the room, then zoom in on the best spot down to about
    // a quarter inch. Fast enough to check every size on a phone.
    var step = Math.max(0.5, Math.max(b.w, b.h) / 24);
    rots.forEach(function (rot) {
      for (var x = b.x + step / 2; x < b.x + b.w; x += step)
        for (var y = b.y + step / 2; y < b.y + b.h; y += step) consider(rot, x, y);
    });
    if (!best) return null;
    for (var st = step / 2; st > 0.02; st /= 2) {
      var bx = best.cx, by = best.cy, br = best.rot;
      for (var i = -2; i <= 2; i++) for (var j = -2; j <= 2; j++) if (i || j) consider(br, bx + i * st, by + j * st);
    }
    return { rot: best.rot, cx: best.cx, cy: best.cy, clearance: best.clearance };
  }

  // Judged on whole inches, the same number the person sees on the plan
  function status(c) { var inch = Math.round(c * 12); return inch >= COMFORT * 12 ? 'fits' : inch >= TIGHT * 12 ? 'tight' : 'big'; }

  // Every standard size checked against one room outline (feet).
  // best: the largest size that leaves at least 12" of floor all around.
  function check(poly) {
    if (!poly || poly.length < 3) return null;
    var list = SIZES.map(function (s) {
      var spot = bestSpot(poly, s);
      return { size: s, spot: spot, status: spot ? status(spot.clearance) : 'big' };
    });
    var best = null;
    list.forEach(function (it) { if (it.status === 'fits' && (!best || sizeArea(it.size) > sizeArea(best.size))) best = it; });
    return { list: list, best: best ? best.size.id : null };
  }

  /* ---------- Spacing lines ---------- */
  // Distance from p along direction (dx, dy) to the first wall of the outline
  function rayToPoly(p, dx, dy, poly) {
    var best = Infinity, n = poly.length;
    for (var i = 0; i < n; i++) {
      var a = poly[i], b = poly[(i + 1) % n];
      var ex = b.x - a.x, ey = b.y - a.y, den = dx * ey - dy * ex;
      if (Math.abs(den) < 1e-9) continue;
      var t = ((a.x - p.x) * ey - (a.y - p.y) * ex) / den;   // along the ray
      var u = ((a.x - p.x) * dy - (a.y - p.y) * dx) / den;   // along the wall
      if (t >= -1e-9 && u >= -1e-9 && u <= 1 + 1e-9 && t < best) best = t;
    }
    return best === Infinity ? null : best;
  }
  // One line per side of the rug, from the rug's edge to the nearest wall on
  // that side. Each side is sampled along its length so a jog in an L-shaped
  // room is caught. Returns [{ from, to, gap }] in feet.
  function gaps(poly, s, rot, cx, cy) {
    var f = footprint(s, rot), out = [];
    if (!f.round && !square(rot)) {
      // Turned: straight out from each side, square to it
      [[-1, 0], [1, 0], [0, -1], [0, 1]].forEach(function (n) {
        var bestG = null, bestP = null, dir = GEO.turn({ x: n[0], y: n[1] }, rot);
        [0, -0.2, 0.2, -0.45, 0.45].forEach(function (t) {
          var loc = n[0] ? { x: n[0] * s.w / 2, y: t * s.h } : { x: t * s.w, y: n[1] * s.h / 2 };
          var p = GEO.place([loc], cx, cy, rot, 1)[0];
          if (!PLAN.pointInPoly(p, poly)) return;
          var g = rayToPoly(p, dir.x, dir.y, poly);
          if (g != null && (bestG == null || g < bestG)) { bestG = g; bestP = p; }
        });
        if (bestG != null) out.push({ from: bestP, to: { x: bestP.x + dir.x * bestG, y: bestP.y + dir.y * bestG }, gap: bestG });
      });
      return out;
    }
    var dirs = [[-1, 0], [1, 0], [0, -1], [0, 1]];
    dirs.forEach(function (dir) {
      var bestG = null, bestP = null, samples = f.round ? [0] : [0, -0.2, 0.2, -0.45, 0.45]; // middle first, so it wins ties
      samples.forEach(function (t) {
        var p;
        if (f.round) p = { x: cx + dir[0] * f.w / 2, y: cy + dir[1] * f.h / 2 };
        else if (dir[0]) p = { x: cx + dir[0] * f.w / 2, y: cy + t * f.h };
        else p = { x: cx + t * f.w, y: cy + dir[1] * f.h / 2 };
        if (!PLAN.pointInPoly(p, poly)) return;
        var g = rayToPoly(p, dir[0], dir[1], poly);
        if (g != null && (bestG == null || g < bestG)) { bestG = g; bestP = p; }
      });
      if (bestG != null) out.push({ from: bestP, to: { x: bestP.x + dir[0] * bestG, y: bestP.y + dir[1] * bestG }, gap: bestG });
    });
    return out;
  }

  return {
    SIZES: SIZES, COMFORT: COMFORT, TIGHT: TIGHT,
    get: get, footprint: footprint, square: square, outline: outline, roomType: roomType,
    clearanceAt: clearanceAt, bestSpot: bestSpot, status: status, check: check, gaps: gaps
  };
})();

/* =====================================================================
   GEO: small shape helpers shared by the furniture, spacing, rug style
   and door code. Points are { x, y } in whatever units the caller uses.
   ===================================================================== */
var GEO = (function () {
  function segDist(p, a, b) {
    var dx = b.x - a.x, dy = b.y - a.y, L = dx * dx + dy * dy;
    var t = L ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / L)) : 0;
    return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
  }
  function cross(o, a, b) { return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x); }
  function segsCross(a, b, c, d) {
    var d1 = cross(c, d, a), d2 = cross(c, d, b), d3 = cross(a, b, c), d4 = cross(a, b, d);
    return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
  }
  // Distance along a ray from p in direction (dx, dy) to segment a-b, or null if it misses
  function raySeg(p, dx, dy, a, b) {
    var ex = b.x - a.x, ey = b.y - a.y, den = dx * ey - dy * ex;
    if (Math.abs(den) < 1e-12) return null;
    var t = ((a.x - p.x) * ey - (a.y - p.y) * ex) / den;
    var u = ((a.x - p.x) * dy - (a.y - p.y) * dx) / den;
    return (t >= -1e-9 && u >= -1e-9 && u <= 1 + 1e-9) ? Math.max(0, t) : null;
  }
  // Distance along a ray to the outline of a polygon, or null
  function rayPoly(p, dx, dy, poly) {
    var best = null;
    for (var i = 0, n = poly.length; i < n; i++) {
      var t = raySeg(p, dx, dy, poly[i], poly[(i + 1) % n]);
      if (t != null && (best == null || t < best)) best = t;
    }
    return best;
  }
  // Shortest distance from a point to a polygon's outline
  function edgeDist(p, poly) {
    var d = Infinity;
    for (var i = 0, n = poly.length; i < n; i++) d = Math.min(d, segDist(p, poly[i], poly[(i + 1) % n]));
    return d;
  }
  // Shortest distance between two polygons, 0 when they touch or overlap
  function polyDist(A, B) {
    var i, j, n = A.length, m = B.length;
    for (i = 0; i < n; i++) if (PLAN.pointInPoly(A[i], B)) return 0;
    for (j = 0; j < m; j++) if (PLAN.pointInPoly(B[j], A)) return 0;
    for (i = 0; i < n; i++) for (j = 0; j < m; j++) if (segsCross(A[i], A[(i + 1) % n], B[j], B[(j + 1) % m])) return 0;
    var d = Infinity;
    for (i = 0; i < n; i++) d = Math.min(d, edgeDist(A[i], B));
    for (j = 0; j < m; j++) d = Math.min(d, edgeDist(B[j], A));
    return d;
  }
  // Points in a shape's own frame, turned rot degrees clockwise, scaled by k, moved to (cx, cy)
  function place(pts, cx, cy, rot, k) {
    var a = (rot || 0) * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    return pts.map(function (p) { return { x: cx + (p.x * c - p.y * s) * k, y: cy + (p.x * s + p.y * c) * k }; });
  }
  // A direction in a shape's own frame, turned to the plan
  function turn(v, rot) {
    var a = (rot || 0) * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    return { x: v.x * c - v.y * s, y: v.x * s + v.y * c };
  }
  return { segDist: segDist, segsCross: segsCross, raySeg: raySeg, rayPoly: rayPoly, edgeDist: edgeDist,
           polyDist: polyDist, place: place, turn: turn };
})();

/* =====================================================================
   FURNITURE: the catalog and the geometry of a placed piece
   Sizes in inches: w is the width (side to side, as you face the piece),
   d the depth (front to back), h the height (for the 3D view later).
   Beds are listed with the frame. At rot 0 a piece faces down the plan:
   its back is at the top. The code only measures; the person places.

   kind  'seat', 'bed', 'table' or 'decor' (FURNART draws each piece by its id)
   role  what it is for, which decides its spacing checks and rug styles:
         seat, coffee, side, console (behind a sofa), media, storage, dresser
         (drawers), bed, nightstand, dining, chair, desk, decor (no spacing lines)
   shape 'rect' (default), 'round' (an oval when w and d differ), or 'L'
         (a sectional: back along the top, the return down the left side,
         arm deep; flip mirrors it)
   chairs  dining tables only: [chairs per long side, chairs per end], or
           { around: n } for n chairs spaced evenly around a round table
   ===================================================================== */
var FURNITURE = (function () {
  var CATALOG = [
    { group: 'Living', items: [
      { id: 'sofa', name: 'Sofa', w: 84, d: 38, h: 34, kind: 'seat', role: 'seat' },
      { id: 'loveseat', name: 'Loveseat', w: 64, d: 36, h: 34, kind: 'seat', role: 'seat' },
      { id: 'sectional', name: 'Sectional', w: 112, d: 84, h: 34, kind: 'seat', role: 'seat', shape: 'L', arm: 38 },
      { id: 'armchair', name: 'Armchair', w: 32, d: 34, h: 32, kind: 'seat', role: 'seat' },
      { id: 'coffee', name: 'Coffee table', w: 48, d: 24, h: 18, kind: 'table', role: 'coffee' },
      { id: 'coffeeR', name: 'Round coffee table', w: 36, d: 36, h: 18, kind: 'table', role: 'coffee', shape: 'round' },
      { id: 'ottoman', name: 'Round ottoman', w: 30, d: 30, h: 17, kind: 'table', role: 'coffee', shape: 'round' },
      { id: 'side', name: 'Side table', w: 20, d: 20, h: 24, kind: 'table', role: 'side' },
      { id: 'sideR', name: 'Round side table', w: 20, d: 20, h: 24, kind: 'table', role: 'side', shape: 'round' },
      { id: 'media', name: 'Media console', w: 70, d: 18, h: 24, kind: 'table', role: 'media' },
      { id: 'console', name: 'Console table', w: 60, d: 14, h: 30, kind: 'table', role: 'console' }
    ] },
    { group: 'Bedroom', items: [
      { id: 'full', name: 'Full bed', w: 58, d: 80, h: 24, kind: 'bed', role: 'bed' },
      { id: 'queen', name: 'Queen bed', w: 64, d: 86, h: 24, kind: 'bed', role: 'bed' },
      { id: 'king', name: 'King bed', w: 80, d: 86, h: 24, kind: 'bed', role: 'bed' },
      { id: 'nightstand', name: 'Nightstand', w: 24, d: 18, h: 26, kind: 'table', role: 'nightstand' },
      { id: 'dresser', name: 'Dresser', w: 60, d: 20, h: 34, kind: 'table', role: 'dresser' }
    ] },
    { group: 'Dining', items: [
      { id: 'dining4r', name: 'Round table for 4', w: 48, d: 48, h: 30, kind: 'table', role: 'dining', shape: 'round', chairs: { around: 4 } },
      { id: 'dining6r', name: 'Round table for 6', w: 60, d: 60, h: 30, kind: 'table', role: 'dining', shape: 'round', chairs: { around: 6 } },
      { id: 'dining6o', name: 'Oval table for 6', w: 78, d: 42, h: 30, kind: 'table', role: 'dining', shape: 'round', chairs: [2, 1] },
      { id: 'dining4', name: 'Table for 4', w: 60, d: 36, h: 30, kind: 'table', role: 'dining', chairs: [2, 0] },
      { id: 'dining6', name: 'Table for 6', w: 72, d: 38, h: 30, kind: 'table', role: 'dining', chairs: [2, 1] },
      { id: 'dining8', name: 'Table for 8', w: 96, d: 40, h: 30, kind: 'table', role: 'dining', chairs: [3, 1] },
      { id: 'chair', name: 'Dining chair', w: 20, d: 22, h: 36, kind: 'seat', role: 'chair' }
    ] },
    { group: 'Office', items: [
      { id: 'desk', name: 'Desk', w: 60, d: 30, h: 30, kind: 'table', role: 'desk' },
      { id: 'deskchair', name: 'Desk chair', w: 26, d: 26, h: 38, kind: 'seat', role: 'chair' },
      { id: 'bookcase', name: 'Bookcase', w: 36, d: 14, h: 72, kind: 'table', role: 'storage' }
    ] },
    // Kitchen: counters, appliances and islands, checked against the NKBA kitchen planning guidelines
    // (work aisles 42" for one cook, 48" for two; walkways 36"; seating clearance 32" / 36" / 44").
    // Counters, the range, the fridge and the pantry stand with their backs to a wall and their fronts
    // to the room. An island with seating brings its stools, tucked under the overhang on its front.
    { group: 'Kitchen', items: [
      { id: 'counter', name: 'Counter', w: 96, d: 25, h: 36, kind: 'kitchen', role: 'counter' },
      { id: 'sink', name: 'Sink', w: 36, d: 25, h: 36, kind: 'kitchen', role: 'counter' },
      { id: 'range', name: 'Range', w: 30, d: 26, h: 36, kind: 'kitchen', role: 'counter' },
      { id: 'fridge', name: 'Refrigerator', w: 36, d: 30, h: 70, kind: 'kitchen', role: 'counter' },
      { id: 'pantry', name: 'Pantry cabinet', w: 30, d: 24, h: 84, kind: 'kitchen', role: 'counter' },
      { id: 'island', name: 'Island with seating', w: 72, d: 40, h: 36, kind: 'kitchen', role: 'island', chairs: { front: 3 }, seat: 'stool', tuck: 8, overhang: 12 },
      { id: 'islandP', name: 'Island', w: 60, d: 30, h: 36, kind: 'kitchen', role: 'island' },
      { id: 'stool', name: 'Counter stool', w: 17, d: 17, h: 26, kind: 'seat', role: 'chair', shape: 'round' }
    ] },
    // Decor: plants, lamps and a pouf. They block walking routes and door swings and are
    // flagged when they run into a wall or a piece, but they make no spacing lines of their own
    // and don't count as blocking a window.
    { group: 'Decor', items: [
      { id: 'plant', name: 'Fiddle leaf fig', w: 26, d: 26, h: 60, kind: 'decor', role: 'decor', shape: 'round' },
      { id: 'palm', name: 'Palm', w: 32, d: 32, h: 60, kind: 'decor', role: 'decor', shape: 'round' },
      { id: 'tree', name: 'Olive tree', w: 34, d: 34, h: 72, kind: 'decor', role: 'decor', shape: 'round' },
      { id: 'plantS', name: 'Snake plant', w: 16, d: 16, h: 30, kind: 'decor', role: 'decor', shape: 'round' },
      { id: 'lamp', name: 'Floor lamp', w: 18, d: 18, h: 62, kind: 'decor', role: 'decor', shape: 'round' },
      { id: 'pouf', name: 'Pouf', w: 20, d: 20, h: 16, kind: 'decor', role: 'decor', shape: 'round' }
    ] }
  ];
  function get(id) {
    for (var g = 0; g < CATALOG.length; g++) for (var i = 0; i < CATALOG[g].items.length; i++) if (CATALOG[g].items[i].id === id) return CATALOG[g].items[i];
    return null;
  }
  // Width or depth as typed: a plain number is inches (how furniture is listed);
  // anything with ' or " goes through the feet-and-inches reader.
  function parseInches(str) {
    var s = String(str || '').trim();
    if (!s) return null;
    if (/^\d+(\.\d+)?$/.test(s)) return parseFloat(s);
    var ft = PLAN.parseFtIn(s);
    return ft ? ft * 12 : null;
  }
  function fmtIn(n) { return Math.round(n) + '"'; }

  // The piece's outline in its own frame, in inches, going clockwise on the plan
  function outline(pc) {
    var w = pc.w, d = pc.d, i;
    if (pc.shape === 'round') {
      var pts = [];
      for (i = 0; i < 48; i++) { var a = i / 48 * Math.PI * 2; pts.push({ x: Math.cos(a) * w / 2, y: Math.sin(a) * d / 2 }); }
      return pts;
    }
    if (pc.shape === 'L') {
      var t = Math.min(pc.arm || 38, w / 2, d / 2);
      var L = [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, -d / 2 + t], [-w / 2 + t, -d / 2 + t], [-w / 2 + t, d / 2], [-w / 2, d / 2]];
      var out = L.map(function (p) { return { x: pc.flip ? -p[0] : p[0], y: p[1] }; });
      return pc.flip ? out.reverse() : out;   // a mirror image runs the other way round
    }
    return [{ x: -w / 2, y: -d / 2 }, { x: w / 2, y: -d / 2 }, { x: w / 2, y: d / 2 }, { x: -w / 2, y: d / 2 }];
  }
  // Leg positions in the piece's own frame (inches), 2" in from the edges.
  // front: the legs nearest the front edge (where you sit), back: the rest.
  function legs(pc) {
    var w = pc.w, d = pc.d, k = 2, f = pc.flip ? -1 : 1;
    function m(p) { return { x: p[0] * f, y: p[1] }; }
    if (pc.shape === 'L') {
      var t = Math.min(pc.arm || 38, w / 2, d / 2);
      return { front: [[w / 2 - k, -d / 2 + t - k], [-w / 2 + t - k, -d / 2 + t - k], [-w / 2 + t - k, d / 2 - k]].map(m),
               back: [[-w / 2 + k, -d / 2 + k], [w / 2 - k, -d / 2 + k], [-w / 2 + k, d / 2 - k]].map(m) };
    }
    return { front: [{ x: -w / 2 + k, y: d / 2 - k }, { x: w / 2 - k, y: d / 2 - k }],
             back: [{ x: -w / 2 + k, y: -d / 2 + k }, { x: w / 2 - k, y: -d / 2 + k }] };
  }

  // Where a dining table's chairs go, in inches from the table's center at rot 0,
  // and which way each one is turned. Chairs face the table with their seats
  // TUCK inches under its edge, the way they sit when pushed in.
  var TUCK = 4;
  // The seat a table or island takes: dining chairs, or counter stools
  function seatFor(t) { return get((t && t.seat) || 'chair'); }
  // Pieces that bring their own seats (and take them along when moved)
  function seated(pc) { return pc && (pc.role === 'dining' || pc.role === 'island'); }
  function chairLayout(t) {
    if (!t || !t.chairs) return [];
    var c = seatFor(t), off = c.d / 2 - (t.tuck || TUCK), out = [];
    if (t.chairs.front) {
      // A row along the front edge (an island's seating side), facing in
      var nf = t.chairs.front, stepF = t.w / nf;
      for (var f = 0; f < nf; f++) out.push({ x: -t.w / 2 + stepF * (f + 0.5), y: t.d / 2 + off, rot: 180 });
      return out;
    }
    if (t.chairs.around) {
      // Evenly around, starting at the top, each chair facing the middle
      var R = Math.max(t.w, t.d) / 2 + off;
      for (var k = 0; k < t.chairs.around; k++) {
        var a = k / t.chairs.around * Math.PI * 2 - Math.PI / 2;
        out.push({ x: Math.cos(a) * R, y: Math.sin(a) * R, rot: ((a * 180 / Math.PI + 90) % 360 + 360) % 360 });
      }
      return out;
    }
    var n = t.chairs[0], step = t.w / n;
    for (var i = 0; i < n; i++) {
      var x = -t.w / 2 + step * (i + 0.5);
      // An oval table's edge curves in toward the ends, so its side chairs sit closer
      var edge = t.shape === 'round' ? t.d / 2 * Math.sqrt(Math.max(0, 1 - Math.pow(x / (t.w / 2), 2))) : t.d / 2;
      out.push({ x: x, y: -(edge + off), rot: 0 });
      out.push({ x: x, y: edge + off, rot: 180 });
    }
    if (t.chairs[1]) {
      out.push({ x: -(t.w / 2 + off), y: 0, rot: 270 });
      out.push({ x: t.w / 2 + off, y: 0, rot: 90 });
    }
    return out;
  }

  // How many chairs a dining table of this size takes, in the same form as
  // a catalog item's chairs. Rectangles and ovals: about 24" of edge per seat
  // along each long side, less 6" at each corner when there are end chairs
  // (so the end chairs and the side chairs don't knock knees); the end chairs
  // stay as the table came. Round tables follow the usual seating guide
  // (48" seats 4, 60" seats 6, 72" seats 8). Catalog sizes come out as listed.
  var SEAT = 24, CORNER = 6;
  function fitChairs(t) {
    if (!t || !t.chairs) return null;
    if (t.chairs.front) return { front: Math.max(1, Math.floor(t.w / SEAT)) };   // 24" of counter per stool (NKBA)
    if (t.chairs.around) {
      var D = Math.max(t.w, t.d);
      var n = D < 36 ? 2 : D < 42 ? 3 : D < 54 ? 4 : D < 60 ? 5 : D < 66 ? 6 : D < 72 ? 7 : D < 84 ? 8 : Math.floor(Math.PI * D / 30);
      return { around: n };
    }
    var ends = t.chairs[1] || 0;
    return [Math.max(1, Math.floor((t.w - (ends ? 2 * CORNER : 0)) / SEAT)), ends];
  }

  // The outline split into pieces with no inward corners (a sectional is two boxes),
  // in the piece's own frame, inches. Used to measure how much two pieces overlap.
  function parts(pc) {
    if (pc.shape !== 'L') return [outline(pc)];
    var w = pc.w, d = pc.d, t = Math.min(pc.arm || 38, w / 2, d / 2), f = pc.flip ? -1 : 1;
    function box(x0, y0, x1, y1) { return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(function (p) { return { x: p[0] * f, y: p[1] }; }); }
    return [box(-w / 2, -d / 2, w / 2, -d / 2 + t), box(-w / 2, -d / 2 + t, -w / 2 + t, d / 2)];
  }
  // The outline on the plan: cx, cy and the result share units, k is those units per inch
  function shapeAt(pc, cx, cy, k) { return GEO.place(outline(pc), cx, cy, pc.rot, k); }
  // A point in the piece's own frame: x across its width, y from back (-) to front (+)
  function toLocal(p, cx, cy, rot) {
    var a = -(rot || 0) * Math.PI / 180, dx = p.x - cx, dy = p.y - cy;
    return { x: dx * Math.cos(a) - dy * Math.sin(a), y: dx * Math.sin(a) + dy * Math.cos(a) };
  }
  // Is point p (same units as cx, cy; k units per inch) on the piece?
  function contains(p, cx, cy, pc, k) {
    var q = toLocal(p, cx, cy, pc.rot);
    return PLAN.pointInPoly({ x: q.x / k, y: q.y / k }, outline(pc));
  }
  // Bounding box of the piece on the plan, same units as cx, cy
  function bounds(pc, cx, cy, k) { return PLAN.bounds(shapeAt(pc, cx, cy, k)); }

  return { CATALOG: CATALOG, get: get, parseInches: parseInches, fmtIn: fmtIn, outline: outline, legs: legs, parts: parts,
           chairLayout: chairLayout, fitChairs: fitChairs, seatFor: seatFor, seated: seated, shapeAt: shapeAt, toLocal: toLocal, contains: contains, bounds: bounds };
})();

/* =====================================================================
   FURNART: the furniture drawings, top-down, in brand colors (cream
   fills, taupe lines, sage greenery). Each drawing sits exactly inside
   the piece's footprint (FURNITURE.outline), so it changes how a piece
   looks and nothing it measures.

   draw(ctx, pc, k, o) draws pc centred on (0, 0), unturned: back toward
   -y, front toward +y. Turn and place the context first.
     k  canvas pixels per inch
     o  { ratio: canvas px per screen px (line widths and shadows scale with it),
          detail: true for the fine lines (seams, folds, grain), shadow: false to skip it }
   The fine lines are for pieces big enough on screen to show them.
   ===================================================================== */
var FURNART = (function () {
  var C = {
    line: '#8a7e72',      // taupe outline
    fine: '#b5a999',      // taupe detail lines
    frame: '#ebe3d6',     // sofa frames and arms, headboards
    cushion: '#FAF9F6',   // seat cushions, sheets, lamp shades
    back: '#f3ede3',      // back cushions, duvets
    accent: '#e4d9c7',    // throw pillows, throws, chair backs, books
    wood: '#efe6d8',      // table and case tops
    pillow: '#ffffff',
    screen: '#6b6560',    // a TV seen from above
    leaf: '#b9c983', leafDark: '#9db25a', vein: '#7f9433',
    pot: '#e4d9c7', soil: '#d9cdb9'
  };
  var K = 1, LW = 1, FINE = true;

  /* ---------- Small drawing helpers (inches; K turns them into pixels) ---------- */
  function rr(ctx, x, y, w, h, r) {
    w = Math.max(w, 0.01); h = Math.max(h, 0.01);
    r = Math.max(0, Math.min(r, w / 2, h / 2));
    x *= K; y *= K; w *= K; h *= K; r *= K;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function ell(ctx, x, y, rx, ry) { ctx.beginPath(); ctx.ellipse(x * K, y * K, Math.max(rx, 0.01) * K, Math.max(ry, 0.01) * K, 0, 0, Math.PI * 2); }
  function circ(ctx, x, y, r) { ell(ctx, x, y, r, r); }
  function poly(ctx, pts) {
    ctx.beginPath();
    pts.forEach(function (p, i) { if (i) ctx.lineTo(p[0] * K, p[1] * K); else ctx.moveTo(p[0] * K, p[1] * K); });
    ctx.closePath();
  }
  function paint(ctx, fill, stroke, lw) {
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = (lw || 1) * LW; ctx.lineJoin = 'round'; ctx.stroke(); }
  }
  function line(ctx, x1, y1, x2, y2, col, lw) {
    ctx.beginPath(); ctx.moveTo(x1 * K, y1 * K); ctx.lineTo(x2 * K, y2 * K);
    ctx.strokeStyle = col || C.fine; ctx.lineWidth = (lw || 0.55) * LW; ctx.lineCap = 'round'; ctx.stroke();
  }
  function turned(ctx, x, y, deg, fn) {
    ctx.save(); ctx.translate(x * K, y * K); ctx.rotate(deg * Math.PI / 180); fn(); ctx.restore();
  }

  // A plump pillow: a square with softly pinched sides
  function pillow(ctx, cx, cy, w, h, rot, fill) {
    turned(ctx, cx, cy, rot, function () {
      var a = w / 2 * K, b = h / 2 * K, p = Math.min(w, h) * 0.09 * K;
      ctx.beginPath();
      ctx.moveTo(-a, -b);
      ctx.quadraticCurveTo(0, -b + p, a, -b);
      ctx.quadraticCurveTo(a - p, 0, a, b);
      ctx.quadraticCurveTo(0, b - p, -a, b);
      ctx.quadraticCurveTo(-a + p, 0, -a, -b);
      ctx.closePath();
      paint(ctx, fill || C.pillow, C.line, 0.8);
      if (FINE) {   // a soft crease
        ctx.beginPath(); ctx.moveTo(-a * 0.55, -b * 0.5); ctx.quadraticCurveTo(0, 0, a * 0.5, b * 0.55);
        ctx.strokeStyle = C.fine; ctx.lineWidth = 0.5 * LW; ctx.stroke();
      }
    });
  }
  // A leaf from (x, y) pointing at angle ang (degrees)
  function leaf(ctx, x, y, ang, len, wid, fill) {
    turned(ctx, x, y, ang, function () {
      var L = len * K, W = wid * K;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.bezierCurveTo(L * 0.3, -W, L * 0.75, -W * 0.85, L, 0);
      ctx.bezierCurveTo(L * 0.75, W * 0.85, L * 0.3, W, 0, 0);
      ctx.closePath();
      ctx.fillStyle = fill; ctx.fill();
      ctx.strokeStyle = C.vein; ctx.lineWidth = 0.55 * LW; ctx.lineJoin = 'round'; ctx.stroke();
      if (FINE && len * K > 9) { ctx.beginPath(); ctx.moveTo(L * 0.1, 0); ctx.quadraticCurveTo(L * 0.55, -W * 0.08, L * 0.92, 0); ctx.stroke(); }
    });
  }
  // A shallow bowl, and a candle: table-top styling without greenery
  function bowl(ctx, x, y, r) {
    circ(ctx, x, y, r); paint(ctx, C.cushion, C.line, 0.7);
    if (FINE) { circ(ctx, x, y, r * 0.62); paint(ctx, null, C.fine, 0.5); }
  }
  function candle(ctx, x, y, r) {
    circ(ctx, x, y, r); paint(ctx, C.pillow, C.line, 0.6);
    circ(ctx, x, y, Math.max(r * 0.22, 0.3)); paint(ctx, C.line, null);
  }
  // A lamp shade seen from above
  function shade(ctx, x, y, r) {
    circ(ctx, x, y, r); paint(ctx, C.cushion, C.line, 0.8);
    circ(ctx, x, y, r * 0.45); paint(ctx, C.frame, C.fine, 0.5);
    circ(ctx, x, y, Math.max(r * 0.12, 0.6)); paint(ctx, C.line, null);
  }
  // A short stack of books, turned a little
  function books(ctx, x, y, w, h, rot) {
    turned(ctx, x, y, rot, function () {
      rr(ctx, -w / 2, -h / 2, w, h, 0.6); paint(ctx, C.accent, C.line, 0.6);
      rr(ctx, -w / 2 + 1, -h / 2 + 0.8, w - 1.6, h - 1.8, 0.5); paint(ctx, C.cushion, C.fine, 0.5);
    });
  }
  // A plain top with a soft bevel line just inside the edge
  function top(ctx, w, d, fill, r) {
    rr(ctx, -w / 2, -d / 2, w, d, r == null ? 1.5 : r); paint(ctx, fill || C.wood, C.line, 1);
    var e = Math.min(1.4, w * 0.06, d * 0.06);
    if (FINE) { rr(ctx, -w / 2 + e, -d / 2 + e, w - 2 * e, d - 2 * e, Math.max(0, (r == null ? 1.5 : r) - 0.5)); paint(ctx, null, C.fine, 0.5); }
  }
  function roundTop(ctx, w, d, fill) {
    ell(ctx, 0, 0, w / 2, d / 2); paint(ctx, fill || C.wood, C.line, 1);
    var e = Math.min(2, w * 0.05, d * 0.05);
    if (FINE) { ell(ctx, 0, 0, w / 2 - e, d / 2 - e); paint(ctx, null, C.fine, 0.5); }
  }

  /* ---------- Seating ---------- */
  // Sofa, loveseat and armchair: arms, back cushions, seat cushions and pillows
  function seat(ctx, w, d) {
    var arm = Math.min(Math.max(w * 0.085, 4), 7.5, w * 0.2), back = Math.min(d * 0.24, 9);
    var inner = w - arm * 2, n = Math.max(1, Math.min(4, Math.round(inner / 24)));
    if (w < 50) n = 1;
    rr(ctx, -w / 2, -d / 2, w, d, 4); paint(ctx, C.frame, null);
    var gap = 0.8, bw = (inner - gap * (n - 1)) / n, i;
    for (i = 0; i < n; i++) { rr(ctx, -w / 2 + arm + i * (bw + gap), -d / 2 + 1.5, bw, back + 2.5, 3); paint(ctx, C.back, C.line, 0.75); }
    var sy = -d / 2 + back + 2.2, sh = d / 2 - 1.2 - sy;
    for (i = 0; i < n; i++) {
      var x0 = -w / 2 + arm + i * (bw + gap);
      rr(ctx, x0, sy, bw, sh, 2.6); paint(ctx, C.cushion, C.line, 0.75);
      if (FINE) line(ctx, x0 + 2, d / 2 - 3.6, x0 + bw - 2, d / 2 - 3.6);   // front welt
    }
    [-1, 1].forEach(function (s) {
      rr(ctx, s < 0 ? -w / 2 : w / 2 - arm, -d / 2, arm, d, Math.min(arm / 2, 3.2)); paint(ctx, C.frame, C.line, 0.75);
      if (FINE) line(ctx, s * (w / 2 - arm / 2), -d / 2 + back + 2, s * (w / 2 - arm / 2), d / 2 - 3);
    });
    if (w >= 50) {
      var ps = Math.min(15, w * 0.17);
      pillow(ctx, -w / 2 + arm + ps * 0.62, -d / 2 + back + ps * 0.5, ps, ps * 0.9, -14, C.accent);
      pillow(ctx, w / 2 - arm - ps * 0.62, -d / 2 + back + ps * 0.5, ps, ps * 0.9, 14, C.accent);
    } else if (inner > 12) {
      pillow(ctx, 0, -d / 2 + back + 3.5, Math.min(14, inner * 0.6), 7, 0, C.accent);   // lumbar
    }
    rr(ctx, -w / 2, -d / 2, w, d, 4); paint(ctx, null, C.line, 1);
  }
  // Sectional: back along the top, the return down the left (mirrored for flip)
  function sectional(ctx, w, d, pc) {
    var t = Math.min(pc.arm || 38, w / 2, d / 2), arm = Math.min(7, t * 0.2), back = Math.min(t * 0.24, 9);
    ctx.save();
    if (pc.flip) ctx.scale(-1, 1);
    var L = [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, -d / 2 + t], [-w / 2 + t, -d / 2 + t], [-w / 2 + t, d / 2], [-w / 2, d / 2]];
    poly(ctx, L); paint(ctx, C.frame, null);
    var X0 = -w / 2, Y0 = -d / 2, gap = 0.8, i;
    // back cushions: along the top run (past the corner) and down the return
    var runA = w - arm - t, nA = Math.max(1, Math.round(runA / 26)), bwA = (runA - gap * (nA - 1)) / nA;
    for (i = 0; i < nA; i++) { rr(ctx, X0 + t + i * (bwA + gap), Y0 + 1.5, bwA, back + 2.5, 3); paint(ctx, C.back, C.line, 0.75); }
    rr(ctx, X0 + 1.5, Y0 + 1.5, t - 1.5, back + 2.5, 3); paint(ctx, C.back, C.line, 0.75);     // corner back
    rr(ctx, X0 + 1.5, Y0 + 1.5, back + 2.5, t - 1.5, 3); paint(ctx, C.back, C.line, 0.75);
    var runB = d - arm - t, nB = Math.max(1, Math.round(runB / 26)), bwB = (runB - gap * (nB - 1)) / nB;
    for (i = 0; i < nB; i++) { rr(ctx, X0 + 1.5, Y0 + t + i * (bwB + gap), back + 2.5, bwB, 3); paint(ctx, C.back, C.line, 0.75); }
    // seat cushions: the corner square, then each run
    var s0 = back + 2.2, depth = t - 1.2 - s0;
    rr(ctx, X0 + s0, Y0 + s0, depth, depth, 2.6); paint(ctx, C.cushion, C.line, 0.75);
    for (i = 0; i < nA; i++) {
      var xa = X0 + t + i * (bwA + gap);
      rr(ctx, xa, Y0 + s0, bwA, depth, 2.6); paint(ctx, C.cushion, C.line, 0.75);
      if (FINE) line(ctx, xa + 2, Y0 + t - 3.6, xa + bwA - 2, Y0 + t - 3.6);
    }
    for (i = 0; i < nB; i++) {
      var yb = Y0 + t + i * (bwB + gap);
      rr(ctx, X0 + s0, yb, depth, bwB, 2.6); paint(ctx, C.cushion, C.line, 0.75);
      if (FINE) line(ctx, X0 + t - 3.6, yb + 2, X0 + t - 3.6, yb + bwB - 2);
    }
    // arms at the two open ends
    rr(ctx, w / 2 - arm, Y0, arm, t, Math.min(arm / 2, 3.2)); paint(ctx, C.frame, C.line, 0.75);
    rr(ctx, X0, d / 2 - arm, t, arm, Math.min(arm / 2, 3.2)); paint(ctx, C.frame, C.line, 0.75);
    // pillows in the corner and at the far end
    var ps = Math.min(15, t * 0.4);
    pillow(ctx, X0 + s0 + ps * 0.55, Y0 + s0 + ps * 0.55, ps, ps * 0.92, -40, C.accent);
    pillow(ctx, w / 2 - arm - ps * 0.62, Y0 + s0 + ps * 0.45, ps, ps * 0.9, 14, C.accent);
    poly(ctx, L); paint(ctx, null, C.line, 1);
    ctx.restore();
  }
  function diningChair(ctx, w, d) {
    rr(ctx, -w / 2 + 1, -d / 2 + 2.5, w - 2, d - 3, 4); paint(ctx, C.cushion, C.line, 0.85);
    if (FINE) { rr(ctx, -w / 2 + 3, -d / 2 + 5, w - 6, d - 8.5, 3); paint(ctx, null, C.fine, 0.5); }
    ctx.beginPath();
    ctx.moveTo((-w / 2) * K, (-d / 2 + 3.5) * K);
    ctx.quadraticCurveTo(0, (-d / 2 - 1.5) * K, (w / 2) * K, (-d / 2 + 3.5) * K);
    ctx.lineTo((w / 2 - 0.5) * K, (-d / 2 + 6) * K);
    ctx.quadraticCurveTo(0, (-d / 2 + 1.5) * K, (-w / 2 + 0.5) * K, (-d / 2 + 6) * K);
    ctx.closePath();
    paint(ctx, C.accent, C.line, 0.85);
  }
  // Desk chair: a five-star base peeking out, the seat, arms and a curved back
  function deskChair(ctx, w, d) {
    var R = Math.min(w, d) / 2;
    for (var i = 0; i < 5; i++) {
      var a = (i / 5 * 360 + 90) * Math.PI / 180, ex = Math.cos(a) * (R - 1.2), ey = Math.sin(a) * (R - 1.2);
      line(ctx, 0, 0, ex, ey, C.line, 1.4);
      circ(ctx, ex, ey, 1.1); paint(ctx, C.frame, C.line, 0.6);
    }
    var sw = w * 0.7, sd = d * 0.66;
    rr(ctx, -sw / 2, -d / 2 + d * 0.2, sw, sd, 5); paint(ctx, C.cushion, C.line, 0.85);
    if (FINE) { rr(ctx, -sw / 2 + 2, -d / 2 + d * 0.2 + 2, sw - 4, sd - 4, 4); paint(ctx, null, C.fine, 0.5); }
    [-1, 1].forEach(function (s) { rr(ctx, s * (sw / 2 + 0.4) - (s < 0 ? 2.6 : 0), -d / 2 + d * 0.3, 2.6, sd * 0.62, 1.3); paint(ctx, C.accent, C.line, 0.7); });
    ctx.beginPath();
    ctx.moveTo((-w * 0.4) * K, (-d / 2 + d * 0.22) * K);
    ctx.quadraticCurveTo(0, (-d / 2 - 1) * K, (w * 0.4) * K, (-d / 2 + d * 0.22) * K);
    ctx.lineTo((w * 0.37) * K, (-d / 2 + d * 0.22 + 3) * K);
    ctx.quadraticCurveTo(0, (-d / 2 + 2.2) * K, (-w * 0.37) * K, (-d / 2 + d * 0.22 + 3) * K);
    ctx.closePath();
    paint(ctx, C.accent, C.line, 0.85);
  }

  /* ---------- Bedroom ---------- */
  function bed(ctx, w, d) {
    var hb = Math.min(3.5, d * 0.05);
    rr(ctx, -w / 2, -d / 2, w, d, 2.5); paint(ctx, C.cushion, null);
    rr(ctx, -w / 2, -d / 2, w, hb, 1.5); paint(ctx, C.frame, C.line, 0.75);
    var big = w >= 76, pw = big ? (w - 8) / 2 : Math.min(26, (w - 6) / 2), ph = Math.min(big ? 19 : 17, d * 0.2), py = -d / 2 + hb + 1.5 + ph / 2;
    if (w < 46) { pw = Math.min(26, w - 6); pillow(ctx, 0, py, pw, ph, 0, C.pillow); }   // a twin takes one
    else { pillow(ctx, -pw / 2 - 0.8, py, pw, ph, 0, C.pillow); pillow(ctx, pw / 2 + 0.8, py, pw, ph, 0, C.pillow); }
    pillow(ctx, 0, py + ph / 2 + 2, Math.min(22, w * 0.34), 8, 0, C.accent);
    var dy = -d / 2 + d * 0.39;
    rr(ctx, -w / 2 + 0.6, dy, w - 1.2, d / 2 - dy - 0.6, 2); paint(ctx, C.back, C.line, 0.75);
    rr(ctx, -w / 2 + 0.6, dy, w - 1.2, 7, 1.5); paint(ctx, C.cushion, C.line, 0.75);
    if (FINE) {
      [0.28, 0.62].forEach(function (f, i) {
        var y = dy + 10 + (d / 2 - dy - 10) * f;
        ctx.beginPath();
        ctx.moveTo((-w / 2 + 6) * K, y * K);
        ctx.bezierCurveTo((-w / 6) * K, (y - 2.5 + i * 4) * K, (w / 6) * K, (y + 2.5 - i * 4) * K, (w / 2 - 8) * K, (y - 1) * K);
        ctx.strokeStyle = C.fine; ctx.lineWidth = 0.5 * LW; ctx.stroke();
      });
    }
    var ty = d / 2 - 17;
    rr(ctx, -w / 2 + 0.6, ty, w - 1.2, 13, 1.5); paint(ctx, C.accent, C.line, 0.75);
    if (FINE) { line(ctx, -w / 2 + 2, ty + 3, w / 2 - 2, ty + 3); line(ctx, -w / 2 + 2, ty + 10, w / 2 - 2, ty + 10); }
    rr(ctx, -w / 2, -d / 2, w, d, 2.5); paint(ctx, null, C.line, 1);
  }
  function nightstand(ctx, w, d) {
    top(ctx, w, d);
    var r = Math.min(w, d) * 0.3;
    books(ctx, w / 2 - Math.min(6, w * 0.25), d / 2 - Math.min(5, d * 0.28), Math.min(8, w * 0.33), Math.min(5.6, d * 0.3), -12);
    shade(ctx, -w / 2 + r + Math.min(2.5, w * 0.08), -d / 2 + r + Math.min(2, d * 0.08), r);
  }
  // Dresser: a lamp and a tray on top, and the drawer fronts along the front edge
  function dresser(ctx, w, d) {
    top(ctx, w, d);
    var n = w >= 48 ? 3 : w >= 30 ? 2 : 1, fy = d / 2 - Math.min(2.6, d * 0.14);
    line(ctx, -w / 2 + 0.8, fy, w / 2 - 0.8, fy, C.line, 0.6);
    for (var i = 0; i <= n; i++) {
      var x = -w / 2 + w * i / n;
      if (i > 0 && i < n) line(ctx, x, fy, x, d / 2, C.line, 0.6);
      if (i < n) { var cx = -w / 2 + w * (i + 0.5) / n; line(ctx, cx - 2, (fy + d / 2) / 2, cx + 2, (fy + d / 2) / 2, C.line, 1); }
    }
    var r = Math.min(d * 0.32, 7);
    shade(ctx, -w / 2 + r + 2.5, -d / 2 + r + 1.5, r);
    if (w >= 36) {   // a tray with a small vase
      rr(ctx, w / 2 - 16, -d / 2 + 3, 12, Math.min(8, d - 8), 1.5); paint(ctx, C.accent, C.line, 0.6);
      bowl(ctx, w / 2 - 10, -d / 2 + 3 + Math.min(8, d - 8) / 2, Math.min(2.6, d * 0.14));
    }
  }

  /* ---------- Living tables ---------- */
  function coffee(ctx, w, d) {
    top(ctx, w, d, null, 2);
    books(ctx, -w * 0.22, 0, Math.min(11, w * 0.28), Math.min(8, d * 0.4), -8);
    bowl(ctx, w * 0.2, -d * 0.05, Math.min(4, d * 0.17));
  }
  function roundCoffee(ctx, w, d) {
    roundTop(ctx, w, d);
    books(ctx, -w * 0.12, d * 0.1, Math.min(10, w * 0.3), Math.min(7.5, d * 0.22), 12);
    bowl(ctx, w * 0.16, -d * 0.16, Math.min(3.6, w * 0.11));
  }
  // An upholstered ottoman or pouf: piping round the edge and buttons
  function ottoman(ctx, w, d) {
    ell(ctx, 0, 0, w / 2, d / 2); paint(ctx, C.cushion, C.line, 1);
    ell(ctx, 0, 0, w / 2 - 1.6, d / 2 - 1.6); paint(ctx, null, C.fine, 0.6);
    var n = w >= 26 ? 6 : 4;
    for (var i = 0; i < n; i++) {
      var a = i / n * Math.PI * 2, bx = Math.cos(a) * w * 0.24, by = Math.sin(a) * d * 0.24;
      if (FINE) line(ctx, 0, 0, bx, by, C.fine, 0.5);
      circ(ctx, bx, by, 0.6); paint(ctx, C.line, null);
    }
    circ(ctx, 0, 0, 0.7); paint(ctx, C.line, null);
  }
  // Side tables carry a table lamp
  function side(ctx, w, d) { top(ctx, w, d); shade(ctx, 0, 0, Math.min(w, d) * 0.3); }
  function roundSide(ctx, w, d) { roundTop(ctx, w, d); shade(ctx, 0, 0, Math.min(w, d) * 0.3); }
  // Media console: door panels, a TV seen from above, a small plant at one end
  function media(ctx, w, d) {
    top(ctx, w, d);
    var n = w >= 56 ? 3 : 2;
    if (FINE) for (var i = 1; i < n; i++) line(ctx, -w / 2 + w * i / n, -d / 2 + 1.4, -w / 2 + w * i / n, d / 2 - 1.4);
    var tw = Math.min(w * 0.72, 58), tx = -w / 2 + Math.max(4, (w - tw) / 2 - 4);
    rr(ctx, tx, -d / 2 + d * 0.3, tw, Math.max(1.6, d * 0.12), 0.6); paint(ctx, C.screen, null);
    rr(ctx, tx + tw / 2 - tw * 0.15, -d / 2 + d * 0.42, tw * 0.3, Math.max(2, d * 0.18), 0.8); paint(ctx, C.frame, C.line, 0.6);   // its stand
    if (w >= 44) books(ctx, w / 2 - Math.min(7, w * 0.1), d * 0.12, Math.min(8, w * 0.12), Math.min(5.5, d * 0.32), -6);
  }
  // Console table: a lamp at one end, books and a bowl
  function consoleTable(ctx, w, d) {
    top(ctx, w, d);
    var r = Math.min(d * 0.4, 6.5);
    shade(ctx, -w / 2 + r + 2.5, 0, r);
    if (w >= 36) books(ctx, w * 0.08, 0, Math.min(10, w * 0.2), Math.min(7, d * 0.55), 6);
    if (w >= 48) { circ(ctx, w / 2 - r - 3, 0, Math.min(d * 0.32, 5)); paint(ctx, C.cushion, C.line, 0.7); if (FINE) { circ(ctx, w / 2 - r - 3, 0, Math.min(d * 0.32, 5) * 0.6); paint(ctx, null, C.fine, 0.5); } }
  }

  /* ---------- Dining ---------- */
  function roundTable(ctx, w, d) { roundTop(ctx, w, d); bowl(ctx, 0, 0, Math.min(w, d) * 0.12); }
  function rectTable(ctx, w, d) {
    top(ctx, w, d, null, 2);
    if (w > 30) { rr(ctx, -w / 2 + 8, -d * 0.16, w - 16, d * 0.32, 0.5); paint(ctx, C.cushion, C.fine, 0.6); }   // a runner
    bowl(ctx, 0, 0, Math.min(w, d) * 0.13);
    if (w >= 56) { candle(ctx, -w * 0.22, 0, 1.6); candle(ctx, w * 0.22, 0, 1.6); }
  }

  /* ---------- Office ---------- */
  function desk(ctx, w, d) {
    top(ctx, w, d);
    var lw = Math.min(14, w * 0.3), ld = Math.min(9.5, d * 0.36);   // an open laptop
    rr(ctx, -lw / 2, d * 0.02, lw, ld, 0.8); paint(ctx, C.cushion, C.line, 0.7);
    rr(ctx, -lw / 2, d * 0.02 - Math.min(1.2, ld * 0.15), lw, Math.min(1.2, ld * 0.15), 0.4); paint(ctx, C.screen, null);
    if (FINE) { rr(ctx, -lw / 2 + 1, d * 0.02 + 1, lw - 2, ld * 0.5, 0.3); paint(ctx, null, C.fine, 0.5); }
    var r = Math.min(d * 0.2, 6);
    shade(ctx, -w / 2 + r + 2.5, -d / 2 + r + 2, r);
    if (w >= 40) books(ctx, w / 2 - 8, -d / 2 + 6, Math.min(9, w * 0.15), Math.min(6.5, d * 0.22), -8);
    circ(ctx, w * 0.3, d * 0.18, Math.min(1.8, d * 0.06)); paint(ctx, C.pillow, C.line, 0.6);   // a mug
  }
  // Bookcase from above: the top, and a row of book spines along the shelves' front
  function bookcase(ctx, w, d) {
    top(ctx, w, d, null, 1);
    var x = -w / 2 + 1.6, end = w / 2 - 1.6, i = 0, widths = [1.4, 1.1, 1.8, 1, 1.3, 2.2, 1.2, 1.6, 0.9, 1.5];
    var cols = [C.accent, C.cushion, C.frame, C.accent, C.back];
    while (x < end - 1) {
      var bw = Math.min(widths[i % widths.length], end - x), lean = i % 7 === 5;
      rr(ctx, x, d / 2 - 1.6 - d * 0.42 * (lean ? 0.8 : 1), bw, d * 0.42 * (lean ? 0.8 : 1), 0.2); paint(ctx, cols[i % cols.length], C.fine, 0.5);
      x += bw + 0.15; i++;
      if (i % 9 === 0) x += Math.min(4, w * 0.08);   // a gap between runs
    }
  }

  /* ---------- Kitchen ---------- */
  var STONE = '#f4efe6', STEEL = '#e3ddd3', BURNER = '#8a7e72';
  // A countertop: a backsplash line along the back, the nosing along the front, and a few soft veins
  function countertop(ctx, w, d, x0, y0) {
    x0 = x0 || 0; y0 = y0 || 0;
    rr(ctx, x0 - w / 2, y0 - d / 2, w, d, 0.8); paint(ctx, STONE, C.line, 1);
    line(ctx, x0 - w / 2 + 0.6, y0 - d / 2 + 1.2, x0 + w / 2 - 0.6, y0 - d / 2 + 1.2, C.fine, 0.6);
    if (FINE) {
      line(ctx, x0 - w / 2 + 0.6, y0 + d / 2 - 1.2, x0 + w / 2 - 0.6, y0 + d / 2 - 1.2, C.fine, 0.45);
      for (var i = 0; i < Math.floor(w / 30); i++) {   // a few veins in the stone
        var vx = x0 - w / 2 + 12 + i * 30 + (i % 2) * 7;
        ctx.beginPath(); ctx.moveTo(vx * K, (y0 - d / 2 + 4) * K);
        ctx.bezierCurveTo((vx + 6) * K, (y0 - d * 0.1) * K, (vx - 3) * K, (y0 + d * 0.1) * K, (vx + 9) * K, (y0 + d / 2 - 4) * K);
        ctx.strokeStyle = '#e4dccf'; ctx.lineWidth = 0.6 * LW; ctx.stroke();
      }
    }
  }
  function counter(ctx, w, d) {
    countertop(ctx, w, d);
    if (w >= 60) { rr(ctx, -w / 2 + 6, -d / 2 + 3, Math.min(14, w * 0.15), Math.min(9, d * 0.36), 1); paint(ctx, C.wood, C.line, 0.6); }   // a cutting board
    if (w >= 84) bowl(ctx, w / 2 - 10, -d / 2 + 7, 4);
  }
  // Sink: an undermount basin and a faucet at the back
  function sink(ctx, w, d) {
    countertop(ctx, w, d);
    var bw = Math.min(w - 8, 30), bd = Math.min(d - 9, 17), by = -d / 2 + 4.5;
    rr(ctx, -bw / 2, by, bw, bd, 2.5); paint(ctx, STEEL, C.line, 0.8);
    if (FINE) { rr(ctx, -bw / 2 + 1, by + 1, bw - 2, bd - 2, 2); paint(ctx, null, C.fine, 0.5); }
    circ(ctx, 0, by + bd * 0.62, 0.9); paint(ctx, C.line, null);   // the drain
    circ(ctx, 0, -d / 2 + 2.6, 1.1); paint(ctx, C.frame, C.line, 0.7);   // the faucet, reaching over the basin
    rr(ctx, -0.5, -d / 2 + 2.6, 1, 6, 0.5); paint(ctx, C.frame, C.line, 0.6);
  }
  // Range: four burners with grates, the controls along the front
  function range(ctx, w, d) {
    rr(ctx, -w / 2, -d / 2, w, d, 0.8); paint(ctx, STEEL, C.line, 1);
    rr(ctx, -w / 2 + 1.2, -d / 2 + 1.2, w - 2.4, d - 5.5, 0.6); paint(ctx, '#d9d2c7', C.line, 0.6);
    var bx = w * 0.22, top = -d / 2 + 1.2 + (d - 5.5) * 0.28, bot = -d / 2 + 1.2 + (d - 5.5) * 0.72;
    [[-bx, top, 4.6], [bx, top, 3.8], [-bx, bot, 3.8], [bx, bot, 4.6]].forEach(function (b) {
      circ(ctx, b[0], b[1], b[2]); paint(ctx, null, BURNER, 0.8);
      circ(ctx, b[0], b[1], b[2] * 0.45); paint(ctx, BURNER, null);
      if (FINE) { line(ctx, b[0] - b[2] - 0.8, b[1], b[0] + b[2] + 0.8, b[1], BURNER, 0.5); line(ctx, b[0], b[1] - b[2] - 0.8, b[0], b[1] + b[2] + 0.8, BURNER, 0.5); }
    });
    for (var i = 0; i < 4; i++) { circ(ctx, -w / 2 + w * (i + 0.5) / 4, d / 2 - 2.1, 0.9); paint(ctx, C.cushion, C.line, 0.6); }   // knobs
  }
  // Refrigerator: two doors meeting in the middle, handles at the front
  function fridge(ctx, w, d) {
    rr(ctx, -w / 2, -d / 2, w, d, 1); paint(ctx, STEEL, C.line, 1);
    if (FINE) { rr(ctx, -w / 2 + 1.2, -d / 2 + 1.2, w - 2.4, d - 4.6, 0.6); paint(ctx, null, C.fine, 0.5); }
    line(ctx, 0, d / 2 - 3.4, 0, d / 2, C.line, 0.7);
    line(ctx, -w / 2, d / 2 - 3.4, w / 2, d / 2 - 3.4, C.line, 0.7);   // the door fronts
    [-1, 1].forEach(function (sg) { rr(ctx, sg * 2.2 - (sg < 0 ? 1 : 0), d / 2 - 0.4, 1, 1.6, 0.4); paint(ctx, C.line, null); });   // handles
  }
  function pantry(ctx, w, d) {
    rr(ctx, -w / 2, -d / 2, w, d, 0.8); paint(ctx, C.wood, C.line, 1);
    if (FINE) { rr(ctx, -w / 2 + 1.2, -d / 2 + 1.2, w - 2.4, d - 4, 0.5); paint(ctx, null, C.fine, 0.5); }
    line(ctx, -w / 2, d / 2 - 2.6, w / 2, d / 2 - 2.6, C.line, 0.6);
    if (w >= 24) line(ctx, 0, d / 2 - 2.6, 0, d / 2, C.line, 0.6);
  }
  // Island: the cabinet base under a stone top; on a seating island the overhang shows as a dashed line
  function island(ctx, w, d, pc) {
    var spec = FURNITURE.get(pc && pc.type), over = spec && spec.chairs ? Math.min(spec.overhang || 12, d * 0.35) : 0;
    countertop(ctx, w, d);
    if (over) {
      ctx.save(); ctx.setLineDash([2 * K, 1.5 * K]);
      line(ctx, -w / 2 + 1, d / 2 - over, w / 2 - 1, d / 2 - over, C.line, 0.6);
      ctx.restore();
    }
    if (w >= 48) bowl(ctx, w * 0.2, -d / 2 + (d - over) / 2, Math.min(5, d * 0.13));
  }
  // Counter stool: a round seat with a footrest ring below
  function stool(ctx, w, d) {
    var R = Math.min(w, d) / 2;
    circ(ctx, 0, 0, R); paint(ctx, null, C.line, 0.7);   // footrest
    circ(ctx, 0, 0, R * 0.74); paint(ctx, C.accent, C.line, 0.85);
    if (FINE) { circ(ctx, 0, 0, R * 0.5); paint(ctx, null, C.fine, 0.5); }
  }

  /* ---------- Decor: four plants, each with its own leaf ---------- */
  function pot(ctx, R, f) {
    circ(ctx, 0, 0, R * f); paint(ctx, C.pot, C.line, 0.8);
    circ(ctx, 0, 0, R * f * 0.8); paint(ctx, C.soil, null);
  }
  // Fiddle leaf fig: a few big, broad, round-tipped leaves at uneven angles
  function broadLeaf(ctx, x, y, ang, len, wid, fill) {
    turned(ctx, x, y, ang, function () {
      var L = len * K, W = wid * K;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.bezierCurveTo(L * 0.15, -W * 0.7, L * 0.7, -W * 1.05, L * 0.97, -W * 0.25);
      ctx.quadraticCurveTo(L * 1.03, 0, L * 0.97, W * 0.25);
      ctx.bezierCurveTo(L * 0.7, W * 1.05, L * 0.15, W * 0.7, 0, 0);
      ctx.closePath();
      ctx.fillStyle = fill; ctx.fill();
      ctx.strokeStyle = C.vein; ctx.lineWidth = 0.55 * LW; ctx.lineJoin = 'round'; ctx.stroke();
      if (FINE && len * K > 9) {
        ctx.beginPath(); ctx.moveTo(L * 0.08, 0); ctx.lineTo(L * 0.9, 0);
        [0.35, 0.55, 0.75].forEach(function (t) {   // side veins
          ctx.moveTo(L * t, 0); ctx.lineTo(L * (t + 0.12), -W * 0.5);
          ctx.moveTo(L * t, 0); ctx.lineTo(L * (t + 0.12), W * 0.5);
        });
        ctx.lineWidth = 0.45 * LW; ctx.stroke();
      }
    });
  }
  function fiddle(ctx, w, d) {
    var R = Math.min(w, d) / 2;
    pot(ctx, R, 0.48);
    [[20, 0.98, C.leafDark], [105, 0.9, C.leafDark], [200, 0.96, C.leafDark], [290, 0.88, C.leafDark],
     [62, 0.78, C.leaf], [158, 0.74, C.leaf], [245, 0.8, C.leaf], [335, 0.72, C.leaf]].forEach(function (l) {
      broadLeaf(ctx, 0, 0, l[0], R * l[1], R * 0.34, l[2]);
    });
  }
  // Snake plant: stiff, narrow, pointed blades with a pale edge
  function snake(ctx, w, d) {
    var R = Math.min(w, d) / 2;
    pot(ctx, R, 0.62);
    [[10, 0.95], [55, 0.8], [100, 1], [148, 0.85], [190, 0.96], [235, 0.78], [280, 0.98], [325, 0.84]].forEach(function (b, i) {
      turned(ctx, 0, 0, b[0], function () {
        var L = R * b[1] * K, W = R * 0.13 * K;
        ctx.beginPath();
        ctx.moveTo(0, -W * 0.6);
        ctx.quadraticCurveTo(L * 0.55, -W * 1.1, L, 0);
        ctx.quadraticCurveTo(L * 0.55, W * 1.1, 0, W * 0.6);
        ctx.closePath();
        ctx.fillStyle = i % 2 ? '#8fa552' : C.leafDark; ctx.fill();
        ctx.strokeStyle = '#d3d99b'; ctx.lineWidth = 1.1 * LW; ctx.stroke();   // the pale band at the edge
        ctx.strokeStyle = C.vein; ctx.lineWidth = 0.5 * LW; ctx.stroke();
        if (FINE && L > 12) {   // cross bands
          ctx.beginPath();
          [0.3, 0.5, 0.7].forEach(function (t) { ctx.moveTo(L * t, -W * 0.5); ctx.lineTo(L * (t + 0.04), W * 0.5); });
          ctx.strokeStyle = '#7f9445'; ctx.lineWidth = 0.4 * LW; ctx.stroke();
        }
      });
    });
  }
  // Palm: arching fronds, a midrib with fine leaflets either side
  function palm(ctx, w, d) {
    var R = Math.min(w, d) / 2;
    pot(ctx, R, 0.4);
    [0, 60, 120, 180, 240, 300, 30, 150, 270].forEach(function (a, i) {
      var outer = i < 6, len = R * (outer ? 0.97 : 0.62);
      turned(ctx, 0, 0, a + (outer ? 0 : 8), function () {
        var L = len * K, bend = L * 0.12, n = Math.max(5, Math.round(len / 1.6));
        ctx.strokeStyle = outer ? C.leafDark : C.leaf;
        ctx.lineCap = 'round';
        ctx.lineWidth = Math.max(0.8 * LW, Math.min(0.45 * K, 1.6 * LW));
        for (var k = 1; k < n; k++) {   // leaflets: thin lines angled toward the tip
          var t = k / n, x = L * t, y = bend * t * t, ln = L * 0.24 * Math.sin(Math.PI * Math.min(1, t * 1.1)) + 0.5 * K;
          ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + ln * 0.45, y - ln); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + ln * 0.45, y + ln); ctx.stroke();
        }
        ctx.beginPath(); ctx.moveTo(0, 0); ctx.quadraticCurveTo(L * 0.5, bend * 0.2, L, bend);
        ctx.strokeStyle = C.vein; ctx.lineWidth = 0.8 * LW; ctx.stroke();
      });
    });
  }
  // Olive tree: a basket and a full canopy of small, narrow, silvery leaves
  function olive(ctx, w, d) {
    var R = Math.min(w, d) / 2, grey = '#aab489', greyDark = '#8f9b6c';
    circ(ctx, 0, 0, R * 0.42); paint(ctx, C.pot, C.line, 0.8);
    if (FINE) { circ(ctx, 0, 0, R * 0.36); paint(ctx, null, C.fine, 0.5); }
    var rings = [[0.95, 18, 0.16, greyDark, 0], [0.75, 15, 0.15, grey, 12], [0.52, 11, 0.14, greyDark, 5], [0.3, 7, 0.13, grey, 25]];
    rings.forEach(function (rg) {
      for (var i = 0; i < rg[1]; i++) {
        var a = i / rg[1] * 360 + rg[4], rad = a * Math.PI / 180, base = R * rg[0] * 0.5;
        leaf(ctx, Math.cos(rad) * base, Math.sin(rad) * base, a + (i % 2 ? 22 : -22), R * rg[0] * 0.5, R * rg[2] * 0.5, rg[3]);
      }
    });
    circ(ctx, 0, 0, R * 0.06); paint(ctx, C.line, null);
  }
  // Floor lamp: a weighted base just visible round a wide shade
  function floorLamp(ctx, w, d) {
    var R = Math.min(w, d) / 2;
    circ(ctx, 0, 0, R); paint(ctx, C.frame, C.line, 0.7);
    shade(ctx, 0, 0, R * 0.82);
    if (FINE) { circ(ctx, 0, 0, R * 0.64); paint(ctx, null, C.fine, 0.5); }
  }

  var BY_ID = {
    sofa: seat, loveseat: seat, armchair: seat, sectional: sectional,
    coffee: coffee, coffeeR: roundCoffee, ottoman: ottoman, side: side, sideR: roundSide, media: media, console: consoleTable,
    full: bed, queen: bed, king: bed, nightstand: nightstand, dresser: dresser,
    chair: diningChair, desk: desk, deskchair: deskChair, bookcase: bookcase,
    counter: counter, sink: sink, range: range, fridge: fridge, pantry: pantry, island: island, islandP: island, stool: stool,
    plant: fiddle, palm: palm, plantS: snake, tree: olive, lamp: floorLamp, pouf: ottoman
  };
  // Pieces of your own, and anything not in the catalog, draw by what they are
  function pick(pc) {
    if (BY_ID[pc.type]) return BY_ID[pc.type];
    if (pc.shape === 'L') return sectional;
    if (pc.role === 'dining') return pc.shape === 'round' ? roundTable : rectTable;
    if (pc.role === 'bed') return bed;
    if (pc.role === 'seat') return seat;
    if (pc.role === 'chair') return diningChair;
    if (pc.role === 'island') return island;
    if (pc.role === 'counter') return counter;
    return pc.shape === 'round' ? function (ctx, w, d) { roundTop(ctx, w, d, C.cushion); } : function (ctx, w, d) { top(ctx, w, d, C.cushion); };
  }

  function draw(ctx, pc, k, o) {
    o = o || {};
    var ratio = o.ratio || 1;
    K = k; FINE = o.detail !== false;
    LW = Math.max(0.9, Math.min(1.6, (k / ratio) * 0.55)) * ratio;
    var fn = pick(pc), round = pc.shape === 'round';
    ctx.save();
    // a soft shadow under the footprint (not under chairs, plants and lamps, whose drawings are smaller than their outline)
    if (o.shadow !== false && ['chair', 'deskchair', 'stool', 'plant', 'palm', 'plantS', 'tree', 'lamp'].indexOf(pc.type) < 0) {
      ctx.save();
      ctx.shadowColor = 'rgba(67,62,60,0.18)'; ctx.shadowBlur = 5 * ratio; ctx.shadowOffsetY = 1.5 * ratio;
      if (round) ell(ctx, 0, 0, pc.w / 2, pc.d / 2);
      else if (pc.shape === 'L') {
        var t = Math.min(pc.arm || 38, pc.w / 2, pc.d / 2), f = pc.flip ? -1 : 1, w = pc.w, d = pc.d;
        poly(ctx, [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, -d / 2 + t], [-w / 2 + t, -d / 2 + t], [-w / 2 + t, d / 2], [-w / 2, d / 2]].map(function (p) { return [p[0] * f, p[1]]; }));
      } else rr(ctx, -pc.w / 2, -pc.d / 2, pc.w, pc.d, 2);
      ctx.fillStyle = C.frame; ctx.fill();
      ctx.restore();
    }
    fn(ctx, pc.w, pc.d, pc);
    ctx.restore();
  }
  // A thumbnail of a catalog item (with a dining table's chairs) as an image URL
  var thumbs = {};
  function thumb(spec, cssW, cssH) {
    var key = (spec.id || spec.type) + '|' + cssW + 'x' + cssH;
    if (thumbs[key]) return thumbs[key];
    var dpr = 2, cv = document.createElement('canvas'), ctx = cv.getContext('2d');
    cv.width = cssW * dpr; cv.height = cssH * dpr;
    var parts = [{ pc: Object.assign({ type: spec.id }, spec), x: 0, y: 0, rot: 0 }], all = [], chair = FURNITURE.seatFor(spec);
    FURNITURE.chairLayout(spec).forEach(function (c) { parts.unshift({ pc: Object.assign({ type: chair.id }, chair), x: c.x, y: c.y, rot: c.rot }); });
    parts.forEach(function (p) { all = all.concat(GEO.place(FURNITURE.outline(p.pc), p.x, p.y, p.rot, 1)); });
    var b = PLAN.bounds(all), pad = 3, k = Math.min((cv.width - 2 * pad * dpr) / b.w, (cv.height - 2 * pad * dpr) / b.h);
    ctx.translate(cv.width / 2 - (b.x + b.w / 2) * k, cv.height / 2 - (b.y + b.h / 2) * k);
    parts.forEach(function (p) {
      ctx.save(); ctx.translate(p.x * k, p.y * k); ctx.rotate(p.rot * Math.PI / 180);
      draw(ctx, p.pc, k, { ratio: dpr * 0.75, detail: k / dpr >= 1.1 });
      ctx.restore();
    });
    return (thumbs[key] = cv.toDataURL('image/png'));
  }
  return { draw: draw, thumb: thumb, COLORS: C };
})();

/* =====================================================================
   SPACE: live spacing checks between placed pieces and the walls
   Everything here is in feet. Each piece comes in as
     { role, group, shape, flip, arm, w, d (inches), rot, cx, cy, poly }
   where poly is its outline on the plan in feet (FURNITURE.shapeAt), and
   walls is a list of room outlines in feet. Lines run straight out from
   each side of a piece, square to that side, so turned pieces (15° steps)
   are measured the same way as straight ones. The code only measures;
   the person decides where things go.
   ===================================================================== */
var SPACE = (function () {
  var RANGE = 8;          // feet: anything farther counts as open floor
  var AGAINST = 4;        // inches: closer than this, the piece is set against it on purpose
  var PASSAGE = 12;       // inches: walkway gaps from here up to 36" are flagged on the plan
  var COFFEE_PAIR = 36;   // inches: a coffee table farther than this from a seat is not part of its group
  var WALL_PATH = { seat: 1, bed: 1, dining: 1, desk: 1, storage: 1, dresser: 1, media: 1, console: 1, other: 1, counter: 1, island: 1 };
  var KITCHEN = { counter: 1, island: 1 };   // the pieces a work aisle runs between   // pieces whose gap to a wall can be a walkway
  // Pieces set out together on purpose. A gap between them is part of the group, not a walkway:
  // seating with its coffee, side, and console tables; seats side by side; a bed and its nightstands.
  function grouped(a, b) {
    function pair(x, y) {
      return (x.role === 'seat' && (y.role === 'coffee' || y.role === 'side' || y.role === 'console' || y.role === 'seat')) ||
             (x.role === 'bed' && y.role === 'nightstand');
    }
    return pair(a, b) || pair(b, a);
  }
  var SIDE_PATH = { seat: 1, bed: 1, other: 1 };   // pieces whose ends can face a walkway
  function seatConsole(a, b) { return (a.role === 'seat' && b.role === 'console') || (a.role === 'console' && b.role === 'seat'); }
  // Does a dining table have chairs on this side? (A chair of its own beyond this edge.)
  function chairsOnSide(t, sd, pieces) {
    return pieces.some(function (o) {
      if (o.role !== 'chair' || o.group !== t.id) return false;
      var q = FURNITURE.toLocal({ x: o.cx, y: o.cy }, t.cx, t.cy, t.rot), n = GEO.turn(sd.dir, -t.rot);
      var along = q.x * 12 * n.x + q.y * 12 * n.y, half = Math.abs(n.x) * t.w / 2 + Math.abs(n.y) * t.d / 2;
      return along > half * 0.75;
    });
  }
  function seatCoffee(a, b) { return (a.role === 'seat' && b.role === 'coffee') || (a.role === 'coffee' && b.role === 'seat'); }
  // ok: comfortable from this many inches; tight: still works from here
  // Each from published designer and planning guidance (see the plan doc)
  var RULES = {
    walk: { ok: 36, tight: 30 },        // main walkway
    dining: { ok: 36, tight: 30 },      // around a dining table, on a side with chairs
    diningWalk: { ok: 44, tight: 36 },  // a side with chairs that people walk behind (on a route)
    diningOpen: { ok: 24, tight: 18 },  // a side of the table with no chairs (against a wall, say)
    bed: { ok: 24, tight: 18 },         // beside a bed
    bedFoot: { ok: 30, tight: 24 },     // at the foot of a bed
    desk: { ok: 36, tight: 30 },        // behind a desk, where the chair rolls out
    drawers: { ok: 36, tight: 30 },     // in front of a dresser, to open drawers and stand
    // Kitchens (NKBA Kitchen Planning Guidelines 6 to 8)
    aisle: { ok: 48, tight: 42 },       // work aisle: 48" for two cooks, 42" for one
    seat: { ok: 36, tight: 32 },        // behind island stools: 32" if nobody passes, 36" to edge past
    seatWalk: { ok: 44, tight: 36 }     // behind island stools on a walking route: 44" to walk past
  };
  var CONSOLE_PAIR = 12;  // inches: a console table this close behind a seat belongs to it
  var CONSOLE_OK = 8;     // inches: a few inches behind the sofa back is the norm
  var TALK = { ok: 8, tight: 10 };          // feet between seats facing each other
  var TV = { near: 0.8, lo: 1.0, hi: 1.7, far: 2.5 };   // viewing distance as a multiple of the screen size
  // Seat to coffee table, from published designer guidance: 14" to 18" is the
  // usual range, 12" works in a small room, past 20" is a stretch to reach.
  var COFFEE = { min: 12, ok: 14, max: 18, reach: 20 };
  // Judged on whole inches, the number the person sees on the plan
  function status(rule, inch) {
    if (rule === 'coffee') return inch < COFFEE.min ? 'close' : inch < COFFEE.ok ? 'tight' : inch <= COFFEE.max ? 'ok' : inch <= COFFEE.reach ? 'tight' : 'close';
    if (rule === 'console') return inch <= CONSOLE_OK ? 'ok' : 'tight';
    var r = RULES[rule];
    return inch >= r.ok ? 'ok' : inch >= r.tight ? 'tight' : 'close';
  }

  // Is there a real wall where a line meets a room outline? Room outlines can
  // meet along an open edge (a living room open to an entrance), so the line
  // only counts as reaching a wall if the plan has wall ink just beyond the
  // outline, or on both sides of the spot (a window or doorway in a real wall,
  // up to 5 feet wide). wallTest(p) says whether point p (feet) is wall ink.
  function realWall(p, dir, wallTest) {
    var t, s, u = { x: -dir.y, y: dir.x };
    function ink(q) { return wallTest(q); }
    for (t = 0; t <= 10; t += 1) if (ink({ x: p.x + dir.x * t / 12, y: p.y + dir.y * t / 12 })) return true;
    function side(sg) {
      for (s = 3; s <= 30; s += 3) for (t = 0; t <= 10; t += 2)
        if (ink({ x: p.x + (u.x * sg * s + dir.x * t) / 12, y: p.y + (u.y * sg * s + dir.y * t) / 12 })) return true;
      return false;
    }
    return side(1) && side(-1);
  }
  // Nearest wall or piece straight out from p, within RANGE feet
  function cast(p, dir, walls, pieces, skip, wallTest) {
    var best = null;
    pieces.forEach(function (o, j) {
      if (skip(o, j)) return;
      if (PLAN.pointInPoly(p, o.poly)) { best = { gap: 0, hit: { type: 'piece', i: j } }; return; }
      var t = GEO.rayPoly(p, dir.x, dir.y, o.poly);
      if (t != null && (!best || t < best.gap)) best = { gap: t, hit: { type: 'piece', i: j } };
    });
    walls.forEach(function (poly) {
      var t = GEO.rayPoly(p, dir.x, dir.y, poly);
      if (t == null || t > RANGE || (best && t >= best.gap)) return;
      if (wallTest && !realWall({ x: p.x + dir.x * t, y: p.y + dir.y * t }, dir, wallTest)) return;   // open floor, not a wall
      best = { gap: t, hit: { type: 'wall' } };
    });
    return best && best.gap <= RANGE ? best : null;
  }

  // The sides of a piece: { name, pts: sample points (feet, on the plan), dir }
  // name is back, front, left or right in the piece's own frame. A round piece
  // gets four lines, one each way; other shapes get one per edge.
  function sides(pc) {
    var k = 1 / 12, out = [];
    function nameOf(n) { return n.y < -0.7 ? 'back' : n.y > 0.7 ? 'front' : n.x < 0 ? 'left' : 'right'; }
    if (pc.shape === 'round') {
      [{ x: 0, y: -1 }, { x: 1, y: 0 }, { x: 0, y: 1 }, { x: -1, y: 0 }].forEach(function (n) {
        var p = GEO.place([{ x: n.x * pc.w / 2, y: n.y * pc.d / 2 }], pc.cx, pc.cy, pc.rot, k)[0];
        out.push({ name: nameOf(n), pts: [p], dir: GEO.turn(n, pc.rot) });
      });
      return out;
    }
    var loc = FURNITURE.outline(pc);
    for (var i = 0; i < loc.length; i++) {
      var a = loc[i], b = loc[(i + 1) % loc.length], ex = b.x - a.x, ey = b.y - a.y, len = Math.hypot(ex, ey);
      if (len < 6) continue;
      var n = { x: ey / len, y: -ex / len }, name = nameOf(n), ts = [0.5, 0.3, 0.7, 0.12, 0.88];
      // Beside a bed, measure the lower part, below the nightstands
      if (pc.role === 'bed' && (name === 'left' || name === 'right')) {
        ts = [0.5, 0.35, 0.65, 0.2, 0.8, 0.05, 0.95].filter(function (t) {
          var fh = (a.y + t * ey + pc.d / 2) / pc.d;
          return fh >= 0.35 && fh <= 0.95;
        });
      }
      var pts = ts.map(function (t) { return { x: a.x + t * ex, y: a.y + t * ey }; });
      out.push({ name: name, pts: GEO.place(pts, pc.cx, pc.cy, pc.rot, k), dir: GEO.turn(n, pc.rot) });
    }
    return out;
  }

  // Every spacing line: [{ piece, side, from, to, gap (ft), inch, rule, status, hit, show }]
  //   rule   coffee (seat front to its coffee table), bed (beside a bed),
  //          dining (out from a dining table, chairs ignored), walk (the rest)
  //   show   'always' for the room checks and narrow walkways,
  //          'selected' for lines drawn only while that piece is picked,
  //          false for pieces set against something
  // wallTest (optional): checks lines that end on a room outline against the plan's real walls.
  // A piece may carry walkBehind { side: true } for dining sides a walking route passes behind.
  function check(pieces, walls, wallTest) {
    var lines = [];
    pieces.forEach(function (pc, i) {
      if (pc.role === 'decor') return;   // plants, lamps and poufs get no spacing lines
      var skip = function (o, j) {
        if (j === i) return true;
        if (o.role === 'decor') return true;
        if ((pc.role === 'dining' || pc.role === 'desk' || pc.role === 'island') && o.role === 'chair') return true;   // chairs and stools pull out
        if (pc.group && o.group === pc.group) return true;                      // a chair and its own table or neighbors
        if (pc.role === 'chair' && pc.group && o.id === pc.group) return true;
        return false;
      };
      sides(pc).forEach(function (sd) {
        var best = null;
        sd.pts.forEach(function (p) {
          var r = cast(p, sd.dir, walls, pieces, skip, wallTest);
          if (r && (!best || r.gap < best.gap)) best = { gap: r.gap, hit: r.hit, from: p };
        });
        if (!best) return;
        var inch = Math.round(best.gap * 12), other = best.hit.type === 'piece' ? pieces[best.hit.i] : null;
        var rule = 'walk';
        // A seat and its coffee table are one group, measured from whichever piece finds the gap
        if (other && seatCoffee(pc, other) && inch <= COFFEE_PAIR) rule = 'coffee';
        else if (other && seatConsole(pc, other) && inch <= CONSOLE_PAIR) rule = 'console';
        else if (pc.role === 'bed' && (sd.name === 'left' || sd.name === 'right')) rule = 'bed';
        else if (pc.role === 'bed' && sd.name === 'front') rule = 'bedFoot';
        else if (pc.role === 'dining') rule = chairsOnSide(pc, sd, pieces) ? (pc.walkBehind && pc.walkBehind[sd.name] ? 'diningWalk' : 'dining') : 'diningOpen';
        // Kitchen: behind an island's stools, and the work aisle between counters, appliances and islands
        else if (pc.role === 'island' && chairsOnSide(pc, sd, pieces)) rule = pc.walkBehind && pc.walkBehind[sd.name] ? 'seatWalk' : 'seat';
        else if (other && inch >= PASSAGE && KITCHEN[pc.role] && KITCHEN[other.role] && (pc.role === 'island' || sd.name === 'front')) rule = 'aisle';   // closer: counters meeting at a corner
        else if (pc.role === 'desk' && sd.name === 'front') rule = 'desk';
        else if (pc.role === 'dresser' && sd.name === 'front') rule = 'drawers';
        // A bed set right against a wall on a side nobody uses is on purpose (a kids' room, a daybed)
        // (Room outlines sit just inside the drawn walls, so up to 6" still counts as against it.)
        var against = !other && inch <= 6 && (rule === 'bed' || rule === 'bedFoot' || rule === 'diningOpen');
        // A narrow walkway is flagged between two pieces, or between a wall and a piece big enough
        // to make a path (36" or more across, and not a nightstand or side table). Chairs at a table are covered by the dining check.
        // Off the ends of a dresser, desk or console, a gap to the wall is a corner, not a path
        var sideOk = (sd.name !== 'left' && sd.name !== 'right') || SIDE_PATH[pc.role];
        var passage = inch >= PASSAGE && inch < RULES.walk.ok && !(pc.role === 'chair' && pc.group) && (other || (WALL_PATH[pc.role] && sideOk && Math.max(pc.w, pc.d) >= 36));
        var show = against ? false : rule === 'console' ? (status(rule, inch) === 'ok' ? 'selected' : 'always')
          : rule !== 'walk' ? 'always' : inch < AGAINST ? false : (passage && !(other && grouped(pc, other))) ? 'always' : 'selected';
        lines.push({ piece: i, side: sd.name, from: best.from, gap: best.gap, inch: inch, rule: rule, against: against,
                     status: against ? 'ok' : status(rule, inch),
                     to: { x: best.from.x + sd.dir.x * best.gap, y: best.from.y + sd.dir.y * best.gap },
                     hit: best.hit, show: show });
      });
    });
    // Two pieces facing each other measure the same gap twice: keep one line.
    // A room check (coffee, bed, dining) wins over a plain walkway line.
    lines.forEach(function (a, ia) {
      if (a.hit.type !== 'piece' || a.dup) return;
      lines.forEach(function (b, ib) {
        if (ib === ia || b.dup || b.hit.type !== 'piece' || b.piece !== a.hit.i || b.hit.i !== a.piece) return;
        var sameGroup = a.rule === 'coffee' && b.rule === 'coffee';
        // Pieces at an angle measure the gap a little differently from each side; a group keeps one line either way
        if (!sameGroup && Math.abs(a.gap - b.gap) > 1.5 / 12) return;
        var drop;
        if (sameGroup) drop = pieces[a.piece].role === 'seat' ? b : a;     // keep the seat's line
        else if (a.rule === 'walk' && b.rule !== 'walk') drop = a;
        else if (b.rule === 'walk' && a.rule !== 'walk') drop = b;
        else drop = (PRIORITY[a.rule] || 9) <= (PRIORITY[b.rule] || 9) ? b : a;   // the more specific check wins
        drop.dup = true;
      });
    });
    lines = lines.filter(function (l) { return !l.dup; });
    return lines.concat(talkLines(pieces), tvLines(pieces));
  }
  var PRIORITY = { coffee: 0, console: 1, drawers: 2, desk: 3, dining: 4, diningWalk: 4, diningOpen: 4, seat: 4, seatWalk: 4, aisle: 4, bedFoot: 5, bed: 6 };

  /* ---------- Seats facing each other, and the TV ---------- */
  // Where someone sits: the middle of a seat's front edge (a sectional's long run), in feet
  function seatPoint(pc) {
    var p = { x: 0, y: pc.d / 2 };
    if (pc.shape === 'L') { var t = Math.min(pc.arm || 38, pc.w / 2, pc.d / 2); p = { x: (pc.flip ? -1 : 1) * t / 2, y: -pc.d / 2 + t }; }
    return GEO.place([p], pc.cx, pc.cy, pc.rot, 1 / 12)[0];
  }
  function front(pc) { return GEO.turn({ x: 0, y: 1 }, pc.rot); }
  // Does a face b? b sits ahead of a, within 60 degrees of straight on
  function faces(a, pa, pb) {
    var d = { x: pb.x - pa.x, y: pb.y - pa.y }, L = Math.hypot(d.x, d.y), f = front(a);
    return L > 0 && (f.x * d.x + f.y * d.y) / L > 0.5;
  }
  // Seats in the same room that face each other: past 8 feet, conversation gets hard
  function talkLines(pieces) {
    var out = [];
    for (var i = 0; i < pieces.length; i++) for (var j = i + 1; j < pieces.length; j++) {
      var a = pieces[i], b = pieces[j];
      if (a.role !== 'seat' || b.role !== 'seat' || a.room !== b.room) continue;
      var pa = seatPoint(a), pb = seatPoint(b);
      if (!faces(a, pa, pb) || !faces(b, pb, pa)) continue;
      var ft = Math.hypot(pb.x - pa.x, pb.y - pa.y), st = ft <= TALK.ok ? 'ok' : ft <= TALK.tight ? 'tight' : 'close';
      out.push({ piece: i, side: 'front', from: pa, to: pb, gap: ft, inch: Math.round(ft * 12), rule: 'talk', status: st,
                 hit: { type: 'piece', i: j }, show: st === 'ok' ? 'selected' : 'always' });
    }
    return out;
  }
  // A media console with a TV size set: viewing distance to the main seat facing it
  function tvLines(pieces) {
    var out = [];
    pieces.forEach(function (m, i) {
      if (m.role !== 'media' || !m.tv) return;
      var pm = GEO.place([{ x: 0, y: 0 }], m.cx, m.cy, m.rot, 1)[0], best = null;
      pieces.forEach(function (s, j) {
        if (s.role !== 'seat' || s.room !== m.room) return;
        var ps = { x: s.cx, y: s.cy };
        if (!faces(m, pm, ps) || !faces(s, seatPoint(s), pm)) return;
        if (!best || s.w * s.d > pieces[best.j].w * pieces[best.j].d) best = { j: j, ps: ps };
      });
      if (!best) return;
      var ft = Math.hypot(best.ps.x - pm.x, best.ps.y - pm.y), ratio = ft * 12 / m.tv;
      var st = ratio >= TV.lo && ratio <= TV.hi ? 'ok' : ratio >= TV.near && ratio <= TV.far ? 'tight' : 'close';
      out.push({ piece: i, side: 'front', from: pm, to: best.ps, gap: ft, inch: Math.round(ft * 12), rule: 'tv', status: st, ratio: ratio,
                 near: ratio < TV.lo, hit: { type: 'piece', i: best.j }, show: 'selected' });
    });
    return out;
  }

  // One row per check, for the panel and the PDF:
  //   { type: 'coffee', a, b, inch, status }
  //   { type: 'bed', a, inches: [..], status }             both sides of a bed
  //   { type: 'dining', a, inch, status }                  the tightest side of a table
  //   { type: 'walk', a, b (or -1 for a wall), inch, status }  walkways under 36"
  var RANK = { ok: 0, tight: 1, close: 2 };
  function report(lines) {
    var rows = [], beds = {}, tables = {};
    function worse(p, q) { return RANK[p.status] - RANK[q.status] || q.inch - p.inch; }   // > 0 when p is the bigger problem
    lines.forEach(function (l) {
      var b = l.hit.type === 'piece' ? l.hit.i : -1;
      if (l.rule === 'coffee') rows.push({ type: 'coffee', a: l.piece, b: b, inch: l.inch, status: l.status });
      else if (l.rule === 'bed') (beds[l.piece] = beds[l.piece] || []).push(l);
      else if (l.rule === 'dining' || l.rule === 'diningWalk' || l.rule === 'diningOpen') { if (!tables[l.piece] || worse(l, tables[l.piece]) > 0) tables[l.piece] = l; }
      else if (l.rule === 'bedFoot' && !l.against) rows.push({ type: 'bedFoot', a: l.piece, b: b, inch: l.inch, status: l.status });
      else if (l.rule === 'aisle') rows.push({ type: 'aisle', a: l.piece, b: b, inch: l.inch, status: l.status });
      else if (l.rule === 'seat' || l.rule === 'seatWalk') rows.push({ type: 'seating', a: l.piece, b: b, inch: l.inch, walk: l.rule === 'seatWalk', status: l.status });
      else if (l.rule === 'desk' || l.rule === 'drawers') rows.push({ type: l.rule, a: l.piece, b: b, inch: l.inch, status: l.status });
      else if (l.rule === 'console' && l.status !== 'ok') rows.push({ type: 'console', a: l.piece, b: b, inch: l.inch, status: l.status });
      else if (l.rule === 'talk') rows.push({ type: 'talk', a: l.piece, b: b, inch: l.inch, ft: l.gap, status: l.status });
      else if (l.rule === 'tv') rows.push({ type: 'tv', a: l.piece, b: b, inch: l.inch, ft: l.gap, ratio: l.ratio, near: l.near, status: l.status });
      else if (l.rule === 'walk' && l.show === 'always') rows.push({ type: 'walk', a: l.piece, b: b, inch: l.inch, status: l.status });
    });
    Object.keys(beds).forEach(function (k) {
      var ls = beds[k].sort(function (p, q) { return (p.against ? 1 : 0) - (q.against ? 1 : 0) || p.inch - q.inch; });
      var open = ls.filter(function (l) { return !l.against; });
      rows.push({ type: 'bed', a: +k, sides: ls.map(function (l) { return { inch: l.inch, against: !!l.against }; }),
                  inches: ls.map(function (l) { return l.inch; }), status: open.length ? open[0].status : 'ok' });
    });
    Object.keys(tables).forEach(function (k) { var l = tables[k]; rows.push({ type: 'dining', a: +k, inch: l.inch, open: l.rule === 'diningOpen', walk: l.rule === 'diningWalk', status: l.status }); });
    var ORDER = { coffee: 0, talk: 1, tv: 2, console: 3, dining: 4, aisle: 4.5, seating: 4.6, desk: 5, drawers: 6, bed: 7, bedFoot: 8, walk: 9 };
    return rows.sort(function (p, q) { return (ORDER[p.type] - ORDER[q.type]) || (RANK[q.status] - RANK[p.status]) || (p.a - q.a); });
  }

  /* ---------- Pieces in the wrong place ----------
     A piece that runs into a wall, or into another piece. Walls here are the
     plan's real wall lines (SNAP's wall map), not the room outlines, so a sofa
     can sit across the line between two rooms of an open plan. */
  var WALL_MIN = 2;      // inches: less than this into a wall is drawing slop
  var OVERLAP_MIN = 1;   // inches
  // How far into the wall ink the piece reaches (feet): sample the piece every
  // 1.5" and keep the wall point farthest in from the piece's edge.
  function intoWall(pc, wallTest) {
    var bb = PLAN.bounds(pc.poly), step = 1.5 / 12, deep = 0;
    for (var x = bb.x + step / 2; x < bb.x + bb.w; x += step) {
      for (var y = bb.y + step / 2; y < bb.y + bb.h; y += step) {
        var p = { x: x, y: y };
        if (!wallTest(p) || !PLAN.pointInPoly(p, pc.poly)) continue;
        deep = Math.max(deep, GEO.edgeDist(p, pc.poly));
      }
    }
    return deep;
  }
  // How far one shape with no inward corners would have to move to clear the other (feet)
  function sat(A, B) {
    var best = Infinity, sets = [A, B];
    for (var s = 0; s < 2; s++) {
      var P = sets[s];
      for (var i = 0; i < P.length; i++) {
        var a = P[i], b = P[(i + 1) % P.length], ex = b.x - a.x, ey = b.y - a.y, L = Math.hypot(ex, ey);
        if (L < 1e-9) continue;
        var nx = -ey / L, ny = ex / L;
        var pa = proj(A, nx, ny), pb = proj(B, nx, ny), ov = Math.min(pa[1], pb[1]) - Math.max(pa[0], pb[0]);
        if (ov <= 0) return 0;
        best = Math.min(best, ov);
      }
    }
    return best;
  }
  function proj(P, nx, ny) {
    var lo = Infinity, hi = -Infinity;
    P.forEach(function (p) { var v = p.x * nx + p.y * ny; lo = Math.min(lo, v); hi = Math.max(hi, v); });
    return [lo, hi];
  }
  function overlap(a, b) {
    var A = FURNITURE.parts(a).map(function (q) { return GEO.place(q, a.cx, a.cy, a.rot, 1 / 12); });
    var B = FURNITURE.parts(b).map(function (q) { return GEO.place(q, b.cx, b.cy, b.rot, 1 / 12); });
    var deep = 0;
    A.forEach(function (pa) { B.forEach(function (pb) { deep = Math.max(deep, sat(pa, pb)); }); });
    return deep;
  }
  // Chairs are meant to tuck under dining tables and desks
  function tucked(c, t) { return c.role === 'chair' && (t.role === 'dining' || t.role === 'desk' || t.role === 'island'); }
  // [{ type: 'wall', a, inch }] and [{ type: 'overlap', a, b, inch }].
  // wallTest(p) says whether point p (feet) is wall ink; pass null when the plan has no wall map.
  function conflicts(pieces, wallTest) {
    var out = [];
    pieces.forEach(function (a, i) {
      if (wallTest) {
        var w = Math.round(intoWall(a, wallTest) * 12);
        if (w >= WALL_MIN) out.push({ type: 'wall', a: i, inch: w });
      }
      for (var j = i + 1; j < pieces.length; j++) {
        var b = pieces[j];
        if (tucked(a, b) || tucked(b, a)) continue;
        var o = Math.round(overlap(a, b) * 12);
        if (o >= OVERLAP_MIN) out.push({ type: 'overlap', a: i, b: j, inch: o });
      }
    });
    return out;
  }

  return { RULES: RULES, COFFEE: COFFEE, TALK: TALK, TV: TV, AGAINST: AGAINST, PASSAGE: PASSAGE, grouped: grouped, status: status, sides: sides, check: check, report: report,
           conflicts: conflicts, overlap: overlap, intoWall: intoWall };
})();

/* =====================================================================
   DOOR: a door the person marks on a wall, and the space it swings through
   A door in feet: { cx, cy (middle of the opening), ux, uy (along the
   wall), nx, ny (the way it swings open), w (inches), hinge (+1 or -1,
   which end of the opening the hinge is at) }.
   ===================================================================== */
var DOOR = (function () {
  // Door types, and windows (marked the same way, on a wall). Widths are inches.
  var TYPES = {
    swing:  { name: 'Single swing', widths: [24, 28, 30, 32, 36] },
    double: { name: 'Double (French)', widths: [48, 60, 72] },
    pocket: { name: 'Pocket', widths: [24, 28, 30, 32, 36] },
    barn:   { name: 'Barn', widths: [30, 32, 36, 42] },
    bypass: { name: 'Sliding (bypass)', widths: [48, 60, 72, 96] },
    bifold: { name: 'Bifold', widths: [24, 30, 36, 48, 60, 72] },
    window: { name: 'Window', widths: [24, 30, 36, 48, 60, 72, 96] }
  };
  var ORDER = ['swing', 'double', 'pocket', 'barn', 'bypass', 'bifold'];
  var WIDTHS = TYPES.swing.widths;
  var BARN_GAP = 5;      // inches off the wall a barn door hangs and slides (door and track)
  var WINDOW_FRONT = 12; // inches in front of a window that count as standing in front of it
  var WINDOW_TALL = 40;  // inches: a piece this tall in front of a window blocks it
  // One leaf swinging on hinge h from closed (toward dir e) to open (toward the room, n), radius r feet
  function leaf(h, e, n, r) {
    var arc = [];
    for (var k = 0; k <= 12; k++) {
      var t = k / 12 * Math.PI / 2, c = Math.cos(t), s = Math.sin(t);
      arc.push({ x: h.x + (e.x * c + n.x * s) * r, y: h.y + (e.y * c + n.y * s) * r });
    }
    return { hinge: h, open: arc[arc.length - 1], arc: arc, sector: [h].concat(arc) };
  }
  // The shape of a door on the plan, in feet. d: { cx, cy, ux, uy (along the wall), nx, ny (into the
  // room it opens into), w (inches), hinge (+1/-1, the end it hinges, slides or folds toward), type }.
  //   jambs   the two ends of the opening, hinge end first
  //   leaves  swinging leaves (swing, double, bifold), each with its arc
  //   zones   the space the door needs clear: swing sectors, or a barn door's run along the wall
  //   slabs   straight door panels to draw: [[from, to], ...]
  function geom(d) {
    var type = d.type || 'swing', r = d.w / 12, hs = d.hinge || 1, u = { x: d.ux * hs, y: d.uy * hs }, n = { x: d.nx, y: d.ny };
    var a = { x: d.cx + u.x * r / 2, y: d.cy + u.y * r / 2 }, b = { x: d.cx - u.x * r / 2, y: d.cy - u.y * r / 2 };
    var back = { x: -u.x, y: -u.y }, out = { type: type, jambs: [a, b], leaves: [], zones: [], slabs: [], dashed: [] };
    function off(p, k) { return { x: p.x + n.x * k / 12, y: p.y + n.y * k / 12 }; }
    function along(p, k) { return { x: p.x + u.x * k, y: p.y + u.y * k }; }
    if (type === 'swing') out.leaves.push(leaf(a, back, n, r));
    else if (type === 'double') { out.leaves.push(leaf(a, back, n, r / 2)); out.leaves.push(leaf(b, u, n, r / 2)); }
    else if (type === 'bifold') {
      // Panels fold back against the jamb: a pair (48" and up) folds to both sides
      if (d.w >= 48) { out.leaves.push(leaf(a, back, n, r / 4)); out.leaves.push(leaf(b, u, n, r / 4)); }
      else out.leaves.push(leaf(a, back, n, r / 2));
      out.leaves.forEach(function (l) {
        // Drawn half folded: two panels in a V, the far one's end sliding along the opening
        var R = Math.hypot(l.arc[0].x - l.hinge.x, l.arc[0].y - l.hinge.y), e = { x: (l.arc[0].x - l.hinge.x) / R, y: (l.arc[0].y - l.hinge.y) / R }, k = Math.SQRT1_2;
        var apex = { x: l.hinge.x + (e.x * k + n.x * k) * R / 2, y: l.hinge.y + (e.y * k + n.y * k) * R / 2 };
        var foot = { x: l.hinge.x + e.x * R * k, y: l.hinge.y + e.y * R * k };
        out.slabs.push([l.hinge, apex], [apex, foot]);
      });
    }
    else if (type === 'pocket') {
      out.slabs.push([off(b, -2), off(a, -2)]);                  // the door, closed, in the doorway
      out.dashed.push([off(a, -2), off(along(a, r), -2)]);       // its pocket, inside the wall beside the hinge end
    }
    else if (type === 'barn') {
      // Hangs on the room side and slides past the hinge end: that stretch of wall must be clear
      out.slabs.push([off(b, 2), off(a, 2)]);
      out.dashed.push([off(a, 2), off(along(a, r), 2)]);
      out.zones.push([a, along(a, r), off(along(a, r), BARN_GAP), off(a, BARN_GAP)]);
    }
    else if (type === 'bypass') {
      // Two panels on two tracks, overlapping a little in the middle
      var c = { x: d.cx, y: d.cy };
      out.slabs.push([off(a, -1), off(along(c, -r * 0.06), -1)]);
      out.slabs.push([off(b, 1), off(along(c, r * 0.06), 1)]);
    }
    else if (type === 'window') {
      out.zones.push([a, b, off(b, WINDOW_FRONT), off(a, WINDOW_FRONT)]);
    }
    out.leaves.forEach(function (l) { out.zones.push(l.sector); });
    // The single-swing fields the older page reads
    if (type === 'swing') { var L = out.leaves[0]; out.hinge = L.hinge; out.latch = b; out.open = L.open; out.arc = L.arc; out.sector = L.sector; }
    return out;
  }
  // Does the door hit anything as it opens (swings, folds, or slides)? pieces: [{ poly, h }] in feet.
  // A window's 'hits' are tall pieces standing in front of it; 'under' are low ones (a bed, a desk).
  // Returns { hits: [indices], under: [indices], nearest: { i, gap (ft) } or null, moves: false for doors with nothing to hit }
  function check(d, pieces) {
    var g = geom(d), hits = [], under = [], nearest = null, win = g.type === 'window';
    if (!g.zones.length) return { hits: hits, under: under, nearest: null, moves: false };
    pieces.forEach(function (pc, j) {
      var dist = Math.min.apply(null, g.zones.map(function (z) { return GEO.polyDist(z, pc.poly); }));
      if (dist <= 1e-6) { if (win && !(pc.h >= WINDOW_TALL)) under.push(j); else hits.push(j); }
      else if (!nearest || dist < nearest.gap) nearest = { i: j, gap: dist };
    });
    return { hits: hits, under: under, nearest: nearest, moves: true };
  }
  return { TYPES: TYPES, ORDER: ORDER, WIDTHS: WIDTHS, WINDOW_TALL: WINDOW_TALL, geom: geom, check: check };
})();

/* =====================================================================
   RUGSTYLE: rug sizes judged against the furniture in a room
   Builds on RUG (which only looks at the walls). Each style turns into a
   few measurements, each with a comfortable amount (comfy) in feet:
   fits when every measurement reaches its comfy amount, tight when every
   one is at least zero, too big (or too small) otherwise. The rug also
   still needs RUG's floor at the walls.
     allOn      every leg of the seating and the coffee table on the rug, 6" in
     frontLegs  the front legs of each seat 6" onto the rug, coffee table on it
     floating   only the coffee table on the rug; the seating stays off it
     bed        rug runs 18" past each side of the bed (12" is tight) and past
                the foot, under the lower two thirds, clear of the nightstands
     dining     rug reaches 24" past the table on every side (18" is tight)
   group: the room's pieces in feet, as SPACE takes them.
   ===================================================================== */
var RUGSTYLE = (function () {
  var NAMES = { walls: 'By the walls', allOn: 'All legs on', frontLegs: 'Front legs on', floating: 'Floating', bed: 'Under the bed', dining: 'Under the table' };
  function role(group, r) { return group.filter(function (p) { return p.role === r; }); }
  function biggest(list) { return list.slice().sort(function (p, q) { return q.w * q.d - p.w * p.d; })[0] || null; }

  // Which styles make sense for the pieces in this room
  function available(group) {
    var out = ['walls'], seats = role(group, 'seat'), coffee = role(group, 'coffee');
    if (seats.length) out.push('allOn', 'frontLegs');
    if (seats.length && coffee.length) out.push('floating');
    if (role(group, 'bed').length) out.push('bed');
    if (role(group, 'dining').length) out.push('dining');
    return out;
  }

  // The rug on the plan in feet: { round, cx, cy, r } or a rectangle, plus its outline
  function rugAt(s, rot, cx, cy) {
    var f = RUG.footprint(s, rot), poly = [];
    if (f.round) {
      for (var i = 0; i < 32; i++) { var a = i / 32 * Math.PI * 2; poly.push({ x: cx + Math.cos(a) * f.w / 2, y: cy + Math.sin(a) * f.w / 2 }); }
      return { round: true, cx: cx, cy: cy, r: f.w / 2, poly: poly };
    }
    if (!RUG.square(rot)) return { turned: true, cx: cx, cy: cy, rot: rot, hw: s.w / 2, hh: s.h / 2, poly: RUG.outline(s, rot, cx, cy) };
    var x0 = cx - f.w / 2, y0 = cy - f.h / 2, x1 = cx + f.w / 2, y1 = cy + f.h / 2;
    return { x0: x0, y0: y0, x1: x1, y1: y1, poly: [{ x: x0, y: y0 }, { x: x1, y: y0 }, { x: x1, y: y1 }, { x: x0, y: y1 }] };
  }
  // How far inside the rug a point is (feet); negative when it's off the rug
  function inside(rg, p) {
    if (rg.round) return rg.r - Math.hypot(p.x - rg.cx, p.y - rg.cy);
    if (rg.turned) { var q = FURNITURE.toLocal(p, rg.cx, rg.cy, rg.rot); return Math.min(rg.hw - Math.abs(q.x), rg.hh - Math.abs(q.y)); }
    return Math.min(p.x - rg.x0, rg.x1 - p.x, p.y - rg.y0, rg.y1 - p.y);
  }
  function onPlan(pc, pts) { return GEO.place(pts, pc.cx, pc.cy, pc.rot, 1 / 12); }
  function minInside(rg, pts) { return pts.reduce(function (m, p) { return Math.min(m, inside(rg, p)); }, Infinity); }
  function legsOf(pc, which) {
    if (pc.shape === 'round' || pc.role !== 'seat') return onPlan(pc, FURNITURE.outline(pc));
    var L = FURNITURE.legs(pc);
    return onPlan(pc, which === 'front' ? L.front : L.front.concat(L.back));
  }
  // How far the rug runs past point p going in direction dir (feet). Negative when p is off the rug.
  function reach(rg, p, dir) {
    if (!PLAN.pointInPoly(p, rg.poly)) return -GEO.edgeDist(p, rg.poly);
    return GEO.rayPoly(p, dir.x, dir.y, rg.poly) || 0;
  }

  // The measurements for one style with the rug at one spot: [{ name, m, comfy, val }]
  // m is measured against "tight" (0 means just tight), val is the number to show.
  function terms(style, rg, group) {
    var out = [], seats = role(group, 'seat'), coffee = role(group, 'coffee');
    if (style === 'allOn') {
      var m = Infinity;
      seats.concat(coffee).forEach(function (pc) { m = Math.min(m, minInside(rg, legsOf(pc, 'all'))); });
      out.push({ name: 'allOn', m: m, comfy: 0.5, val: m });
    } else if (style === 'frontLegs') {
      var mf = Infinity;
      seats.forEach(function (pc) { mf = Math.min(mf, minInside(rg, legsOf(pc, 'front'))); });
      out.push({ name: 'front', m: mf, comfy: 0.5, val: mf });
      coffee.forEach(function (pc) { var mc = minInside(rg, legsOf(pc)); out.push({ name: 'coffee', m: mc, comfy: 0.5, val: mc }); });
    } else if (style === 'floating') {
      coffee.forEach(function (pc) { var mc = minInside(rg, legsOf(pc)); out.push({ name: 'coffee', m: mc, comfy: 0.5, val: mc }); });
      seats.forEach(function (pc) {
        var gap = GEO.polyDist(rg.poly, pc.poly);
        // On the rug: how far the seat reaches onto it (at least a little, so it never reads as zero)
        if (gap <= 0) gap = -Math.max(0.05, Math.max.apply(null, pc.poly.map(function (p) { return inside(rg, p); })));
        out.push({ name: 'seatOff', m: gap, comfy: 0.25, val: gap });
      });
    } else if (style === 'bed') {
      var bd = biggest(role(group, 'bed'));
      if (bd) {
        var w = bd.w, d = bd.d;
        [-1, 1].forEach(function (sgn) {
          var ext = Infinity, dir = GEO.turn({ x: sgn, y: 0 }, bd.rot);
          [1 / 3, 0.6, 0.9].forEach(function (f) { ext = Math.min(ext, reach(rg, onPlan(bd, [{ x: sgn * w / 2, y: -d / 2 + f * d }])[0], dir)); });
          out.push({ name: 'bedSide', m: ext - 1, comfy: 0.5, val: ext });
        });
        var foot = reach(rg, onPlan(bd, [{ x: 0, y: d / 2 }])[0], GEO.turn({ x: 0, y: 1 }, bd.rot));
        out.push({ name: 'bedFoot', m: foot, comfy: 1, val: foot });
        // From a third of the way down the bed, the rug should stop short of the headboard
        var third = onPlan(bd, [{ x: 0, y: -d / 2 + d / 3 }])[0];
        var up = reach(rg, third, GEO.turn({ x: 0, y: -1 }, bd.rot));
        out.push({ name: 'bedHead', m: (d / 3) / 12 - up, comfy: 0, val: up });
      }
    } else if (style === 'dining') {
      var tb = biggest(role(group, 'dining'));
      if (tb) { var mt = minInside(rg, onPlan(tb, FURNITURE.outline(tb))); out.push({ name: 'dining', m: mt - 1.5, comfy: 0.5, val: mt }); }
    }
    return out;
  }
  function norm(t) { return t.comfy ? t.m / t.comfy : (t.m >= -1e-6 ? 1 : t.m * 12); }

  // A rug size at one spot, judged on the style and the walls together
  //   score  1 or more fits, 0 to 1 tight, under 0 doesn't work
  //   worst  the measurement holding it back (or null when the walls are)
  function evalAt(poly, style, s, rot, cx, cy, group) {
    var c = RUG.clearanceAt(poly, s, rot, cx, cy), span = RUG.COMFORT - RUG.TIGHT;
    // judged on whole inches, the same numbers the person sees
    var score = Math.min(1, (Math.round(c * 12) / 12 - RUG.TIGHT) / span), worst = null;
    if (style && style !== 'walls') {
      terms(style, rugAt(s, rot, cx, cy), group).forEach(function (t) {
        var sc = norm({ m: Math.round(t.m * 12) / 12, comfy: t.comfy });
        if (sc < score) { score = sc; worst = t; }
      });
    }
    return { score: score, raw: Math.min(1, (c - RUG.TIGHT) / span, rawStyle(style, s, rot, cx, cy, group)), clearance: c, worst: worst,
             status: score >= 1 ? 'fits' : score >= 0 ? 'tight' : 'big' };
  }
  // Same as evalAt's score without rounding, so the search can feel its way
  function rawStyle(style, s, rot, cx, cy, group) {
    if (!style || style === 'walls') return Infinity;
    var rg = rugAt(s, rot, cx, cy);
    return terms(style, rg, group).reduce(function (m, t) { return Math.min(m, norm(t)); }, Infinity);
  }

  // Where this size works best for the style: a coarse grid over the room, then
  // zoom in. Ties go to the spot closest to the middle of the furniture.
  function bestSpot(poly, style, s, group) {
    var b = PLAN.bounds(poly), mid = groupMid(group) || { x: b.x + b.w / 2, y: b.y + b.h / 2 };
    var rots = s.d ? [0] : [0, 90], best = null;
    function consider(rot, x, y) {
      var e = evalAt(poly, style, s, rot, x, y, group), sc = Math.min(1, e.raw), dm = Math.hypot(x - mid.x, y - mid.y);
      if (!best || sc > best.sc + 1e-4 || (Math.abs(sc - best.sc) <= 1e-4 && dm < best.dm)) best = { rot: rot, cx: x, cy: y, sc: sc, dm: dm };
    }
    var step = Math.max(0.25, Math.max(b.w, b.h) / 32);
    rots.forEach(function (rot) {
      for (var x = b.x + step / 2; x < b.x + b.w; x += step)
        for (var y = b.y + step / 2; y < b.y + b.h; y += step) consider(rot, x, y);
    });
    if (!best) return null;
    for (var st = step / 2; st > 0.02; st /= 2) {
      var bx = best.cx, by = best.cy, br = best.rot;
      for (var i = -2; i <= 2; i++) for (var j = -2; j <= 2; j++) if (i || j) consider(br, bx + i * st, by + j * st);
    }
    var e = evalAt(poly, style, s, best.rot, best.cx, best.cy, group);
    return { rot: best.rot, cx: best.cx, cy: best.cy, clearance: e.clearance, score: e.score, worst: e.worst, status: e.status };
  }
  function groupMid(group) {
    if (!group || !group.length) return null;
    var all = []; group.forEach(function (p) { all = all.concat(p.poly); });
    var bb = PLAN.bounds(all);
    return { x: bb.x + bb.w / 2, y: bb.y + bb.h / 2 };
  }
  // Pieces that matter to a style (the rest of the room's furniture is ignored)
  function relevant(style, group) {
    var keep = { allOn: ['seat', 'coffee'], frontLegs: ['seat', 'coffee'], floating: ['seat', 'coffee'], bed: ['bed'], dining: ['dining'] }[style];
    if (!keep) return [];
    var g = group.filter(function (p) { return keep.indexOf(p.role) > -1; });
    if (style === 'bed' || style === 'dining') { var big = biggest(g); return big ? [big] : []; }
    return g;
  }

  // Every standard size for a style. Same shape as RUG.check's result.
  function check(poly, style, group) {
    if (!style || style === 'walls') return RUG.check(poly);
    if (!poly || poly.length < 3) return null;
    var g = relevant(style, group || []);
    var list = RUG.SIZES.map(function (s) {
      var spot = bestSpot(poly, style, s, g);
      return { size: s, spot: spot, status: spot ? spot.status : 'big' };
    });
    var best = null;
    list.forEach(function (it) { if (it.status === 'fits' && (!best || sizeArea(it.size) > sizeArea(best.size))) best = it; });
    return { list: list, best: best ? best.size.id : null };
  }
  function sizeArea(s) { return s.d ? Math.PI * s.d * s.d / 4 : s.w * s.h; }
  // The rug where the person left it, judged on the style
  function judge(poly, style, s, rot, cx, cy, group) {
    return evalAt(poly, style, s, rot, cx, cy, relevant(style, group || []));
  }

  return { NAMES: NAMES, available: available, relevant: relevant, terms: terms, evalAt: evalAt, bestSpot: bestSpot, check: check, judge: judge };
})();

/* =====================================================================
   WALK: the real walking routes through a plan
   Lays a fine grid (2") over the rooms. Wall ink and furniture are blocked;
   everything else inside a room (or within a foot of one, so routes can pass
   through openings and doorways) is floor. For every open floor square it
   works out how wide the clear space is there, then finds, from each marked
   door, the widest way to each place people need to reach: the other doors,
   each open side of a bed, the front of each seat, the desk, and the front of
   each dresser. A route's width is its narrowest point (the pinch). Doorways
   themselves, and the last stretch at the place being reached (a bed side,
   the space at a sofa), are left out of the pinch: those have their own checks.
   Input, all in feet:
     pieces    as for SPACE (role, rot, w, d, cx, cy, poly, ...)
     rooms     room outlines
     doors     { cx, cy, w (inches) }
     wallTest  p -> true when p is wall ink
   The code only measures; the person decides where things go.
   ===================================================================== */
var WALK = (function () {
  var CELL = 2;          // inches per grid square
  var CAP = 48;          // inches: wider than this is all the same (open floor)
  var REACH = 36;        // inches: the space at a bed side, a seat, a desk or a dresser (judged by its own check)
  var DOOR_PAD = 4;      // inches past each end of a doorway that count as the opening itself
  var EDGE_PAD = 12;     // inches outside a room outline still counted as floor (walls, openings)
  var BEHIND = [18, 60]; // inches out from a dining table edge where a route passes behind the chairs
  var RULE = { ok: 36, tight: 30 };
  function status(inch) { return inch >= RULE.ok ? 'ok' : inch >= RULE.tight ? 'tight' : 'close'; }

  function nameOf(n) { return n.y < -0.7 ? 'back' : n.y > 0.7 ? 'front' : n.x < 0 ? 'left' : 'right'; }
  // The sides of a piece on the plan: { name, a, b (ends, feet), n (outward), along: [lo, hi] share of the edge }
  function edges(pc) {
    var out = [];
    if (pc.shape === 'round') {
      [{ x: 0, y: -1 }, { x: 1, y: 0 }, { x: 0, y: 1 }, { x: -1, y: 0 }].forEach(function (n) {
        // a straight stand-in for the curve: the tangent at that point, as wide as the piece
        var half = (n.x ? pc.d : pc.w) / 2, rad = (n.x ? pc.w : pc.d) / 2, t = { x: -n.y, y: n.x };
        var pts = GEO.place([{ x: n.x * rad + t.x * half, y: n.y * rad + t.y * half }, { x: n.x * rad - t.x * half, y: n.y * rad - t.y * half }], pc.cx, pc.cy, pc.rot, 1 / 12);
        out.push({ name: nameOf(n), a: pts[0], b: pts[1], n: GEO.turn(n, pc.rot) });
      });
      return out;
    }
    var loc = FURNITURE.outline(pc), pl = GEO.place(loc, pc.cx, pc.cy, pc.rot, 1 / 12);
    for (var i = 0; i < loc.length; i++) {
      var a = loc[i], b = loc[(i + 1) % loc.length], ex = b.x - a.x, ey = b.y - a.y, len = Math.hypot(ex, ey);
      if (len < 6) continue;
      var n = { x: ey / len, y: -ex / len };
      out.push({ name: nameOf(n), a: pl[i], b: pl[(i + 1) % loc.length], n: GEO.turn(n, pc.rot), local: { a: a, b: b } });
    }
    return out;
  }
  // Where a point sits against an edge: how far along it (0 to 1) and how far out (feet)
  function against(p, e) {
    var ex = e.b.x - e.a.x, ey = e.b.y - e.a.y, L2 = ex * ex + ey * ey;
    return { t: ((p.x - e.a.x) * ex + (p.y - e.a.y) * ey) / L2, out: (p.x - e.a.x) * e.n.x + (p.y - e.a.y) * e.n.y };
  }

  // Squared distance transform (Felzenszwalb and Huttenlocher), one row or column
  function edt1d(f, n) {
    var d = new Float64Array(n), v = new Int32Array(n), z = new Float64Array(n + 1), k = 0, q, s;
    v[0] = 0; z[0] = -Infinity; z[1] = Infinity;
    for (q = 1; q < n; q++) {
      if (f[q] === Infinity) continue;
      if (f[v[k]] === Infinity) { v[k] = q; z[k] = -Infinity; z[k + 1] = Infinity; continue; }
      s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
      while (s <= z[k]) { k--; if (k < 0) break; s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]); }
      if (k < 0) { k = 0; v[0] = q; z[0] = -Infinity; z[1] = Infinity; continue; }
      k++; v[k] = q; z[k] = s; z[k + 1] = Infinity;
    }
    if (f[v[0]] === Infinity) { for (q = 0; q < n; q++) d[q] = Infinity; return d; }
    k = 0;
    for (q = 0; q < n; q++) { while (z[k + 1] < q) k++; d[q] = (q - v[k]) * (q - v[k]) + f[v[k]]; }
    return d;
  }
  function edt(free, nx, ny) {
    var g = new Float64Array(nx * ny), i, x, y, col = new Float64Array(ny), row = new Float64Array(nx);
    for (i = 0; i < nx * ny; i++) g[i] = free[i] ? Infinity : 0;
    for (x = 0; x < nx; x++) {
      for (y = 0; y < ny; y++) col[y] = g[y * nx + x];
      var dc = edt1d(col, ny);
      for (y = 0; y < ny; y++) g[y * nx + x] = dc[y];
    }
    for (y = 0; y < ny; y++) {
      for (x = 0; x < nx; x++) row[x] = g[y * nx + x];
      var dr = edt1d(row, nx);
      for (x = 0; x < nx; x++) g[y * nx + x] = Math.sqrt(dr[x]);
    }
    return g;   // in cells, to the nearest blocked cell's center
  }

  // A small binary heap of cell numbers, smallest key first
  function Heap() { this.k = []; this.v = []; }
  Heap.prototype.push = function (key, val) {
    var k = this.k, v = this.v, i = k.length; k.push(key); v.push(val);
    while (i > 0) { var p = (i - 1) >> 1; if (k[p] <= key) break; k[i] = k[p]; v[i] = v[p]; i = p; }
    k[i] = key; v[i] = val;
  };
  Heap.prototype.pop = function () {
    var k = this.k, v = this.v, top = v[0], lk = k.pop(), lv = v.pop(), n = k.length, i = 0;
    if (!n) return top;
    while (true) {
      var l = 2 * i + 1, r = l + 1, m = i, mk = lk;
      if (l < n && k[l] < mk) { m = l; mk = k[l]; }
      if (r < n && k[r] < mk) { m = r; mk = k[r]; }
      if (m === i) break;
      k[i] = k[m]; v[i] = v[m]; i = m;
    }
    k[i] = lk; v[i] = lv;
    return top;
  };

  function routes(o) {
    var rooms = o.rooms || [], pieces = o.pieces || [], doors = o.doors || [], wallTest = o.wallTest;
    if (!rooms.length || !doors.length || !wallTest) return null;
    var all = []; rooms.forEach(function (r) { all = all.concat(r); });
    var bb = PLAN.bounds(all), pad = 2, c = CELL / 12;
    var area = (bb.w + 2 * pad) * (bb.h + 2 * pad);
    if (area / (c * c) > 400000) c = Math.sqrt(area / 400000);   // keep very large plans quick
    var x0 = bb.x - pad, y0 = bb.y - pad, nx = Math.ceil((bb.w + 2 * pad) / c), ny = Math.ceil((bb.h + 2 * pad) / c), N = nx * ny;
    var free = new Uint8Array(N), inside = new Uint8Array(N), i, x, y;
    function at(i) { return { x: x0 + (i % nx + 0.5) * c, y: y0 + (Math.floor(i / nx) + 0.5) * c }; }
    function cellOf(p) { var cx = Math.floor((p.x - x0) / c), cy = Math.floor((p.y - y0) / c); return cx < 0 || cy < 0 || cx >= nx || cy >= ny ? -1 : cy * nx + cx; }
    // Floor: in a room, or close enough to one to be a wall or an opening between rooms
    var edgePad = EDGE_PAD / 12;
    for (i = 0; i < N; i++) {
      var p = at(i), inR = false, near = false;
      for (var r = 0; r < rooms.length && !inR; r++) {
        var rb = PLAN.bounds(rooms[r]);
        if (p.x < rb.x - edgePad || p.x > rb.x + rb.w + edgePad || p.y < rb.y - edgePad || p.y > rb.y + rb.h + edgePad) continue;
        if (PLAN.pointInPoly(p, rooms[r])) inR = true;
        else if (!near && GEO.edgeDist(p, rooms[r]) <= edgePad) near = true;
      }
      if ((inR || near) && !wallTest(p)) { free[i] = 1; inside[i] = inR ? 1 : 0; }
    }
    // Furniture is in the way
    var owner = new Int32Array(N).fill(-1);
    pieces.forEach(function (pc, k) {
      var b = PLAN.bounds(pc.poly);
      for (y = Math.max(0, Math.floor((b.y - y0) / c)); y <= Math.min(ny - 1, Math.floor((b.y + b.h - y0) / c)); y++)
        for (x = Math.max(0, Math.floor((b.x - x0) / c)); x <= Math.min(nx - 1, Math.floor((b.x + b.w - x0) / c)); x++) {
          var j = y * nx + x;
          if (PLAN.pointInPoly(at(j), pc.poly)) { free[j] = 0; owner[j] = k; }
        }
    });
    // Clear width at each square, whole inches, capped
    var dist = edt(free, nx, ny), wide = new Int16Array(N);
    for (i = 0; i < N; i++) wide[i] = free[i] ? Math.min(CAP, Math.max(0, Math.round((2 * dist[i] - 1) * c * 12))) : 0;
    // Openings: stretches of a room outline with no wall drawn and another room right across
    // (a living room open to a kitchen). Each becomes a passage, like a door with no swing.
    // Doorways already marked as doors are left to the doors.
    var passages = [], SAMPLE = 2 / 12, MIN_OPEN = 18 / 12;
    function nearDoor(p) { return doors.some(function (d) { return Math.hypot(p.x - d.cx, p.y - d.cy) <= d.w / 24 + 1; }); }
    function noInk(p, u) { for (var t = -10; t <= 10; t++) if (wallTest({ x: p.x + u.x * t / 12, y: p.y + u.y * t / 12 })) return false; return true; }
    function across(p, ri) {
      for (var rj = 0; rj < rooms.length; rj++) if (rj !== ri && (PLAN.pointInPoly(p, rooms[rj]) || GEO.edgeDist(p, rooms[rj]) <= 1)) return rj;
      return -1;
    }
    rooms.forEach(function (poly, ri) {
      for (var e = 0; e < poly.length; e++) {
        var A = poly[e], Bv = poly[(e + 1) % poly.length], L = Math.hypot(Bv.x - A.x, Bv.y - A.y);
        if (L < MIN_OPEN) continue;
        var u = { x: -(Bv.y - A.y) / L, y: (Bv.x - A.x) / L }, n = Math.max(2, Math.round(L / SAMPLE)), run0 = -1;
        for (var k = 0; k <= n; k++) {
          var t = k / n, p = { x: A.x + (Bv.x - A.x) * t, y: A.y + (Bv.y - A.y) * t };
          var rj = k < n ? across(p, ri) : -1, open = rj > -1 && noInk(p, u) && !nearDoor(p);
          if (open && run0 < 0) run0 = k;
          if ((!open || k === n) && run0 > -1) {
            var t0 = run0 / n, t1 = (open ? k : k - 1) / n;
            if ((t1 - t0) * L >= MIN_OPEN) {
              var a = { x: A.x + (Bv.x - A.x) * t0, y: A.y + (Bv.y - A.y) * t0 }, b = { x: A.x + (Bv.x - A.x) * t1, y: A.y + (Bv.y - A.y) * t1 };
              var mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
              // The same opening seen from the room on the other side: keep one
              var nb = across(mid, ri);   // named from its middle: a corner can touch a third room
              if (nb > -1 && !passages.some(function (q) { return GEO.segDist(mid, q.a, q.b) <= 1; }))
                passages.push({ a: a, b: b, cx: mid.x, cy: mid.y, w: Math.round((t1 - t0) * L * 12), rooms: [ri, nb] });
            }
            run0 = -1;
          }
        }
      }
    });
    // Doorways: the squares around each door, which are where routes start
    var doorCells = doors.map(function (d) {
      var R = (d.w / 2 + DOOR_PAD) / 12, list = [];
      for (y = Math.max(0, Math.floor((d.cy - R - y0) / c)); y <= Math.min(ny - 1, Math.floor((d.cy + R - y0) / c)); y++)
        for (x = Math.max(0, Math.floor((d.cx - R - x0) / c)); x <= Math.min(nx - 1, Math.floor((d.cx + R - x0) / c)); x++) {
          var j = y * nx + x, q = at(j);
          if (free[j] && Math.hypot(q.x - d.cx, q.y - d.cy) <= R) list.push(j);
        }
      return list;
    });
    // ...and the squares on each opening
    var passCells = passages.map(function (q) {
      var R = 6 / 12, b = PLAN.bounds([q.a, q.b]), list = [];
      for (y = Math.max(0, Math.floor((b.y - R - y0) / c)); y <= Math.min(ny - 1, Math.floor((b.y + b.h + R - y0) / c)); y++)
        for (x = Math.max(0, Math.floor((b.x - R - x0) / c)); x <= Math.min(nx - 1, Math.floor((b.x + b.w + R - x0) / c)); x++) {
          var j = y * nx + x;
          if (free[j] && GEO.segDist(at(j), q.a, q.b) <= R) list.push(j);
        }
      return list;
    });
    // Doors and openings are the places routes start from and run between
    var nodes = doors.map(function (d, k) { return { type: 'door', k: k, cells: doorCells[k], at: { x: d.cx, y: d.cy } }; })
      .concat(passages.map(function (q, k) { return { type: 'passage', k: k, cells: passCells[k], seg: q }; }));
    var inDoor = new Uint8Array(N);
    // Doorways are left out of the pinch (a door is as wide as it is); openings are not, so
    // furniture crowding an open edge between rooms still counts
    doorCells.forEach(function (l) { l.forEach(function (j) { inDoor[j] = 1; }); });
    function cellsNear(e, lo, hi, depth0, depth1) {
      var L = Math.hypot(e.b.x - e.a.x, e.b.y - e.a.y), reach = depth1 / 12, list = [];
      var ex = (e.b.x - e.a.x), ey = (e.b.y - e.a.y);
      var A = { x: e.a.x + ex * Math.min(0, lo), y: e.a.y + ey * Math.min(0, lo) }, Bq = { x: e.a.x + ex * Math.max(1, hi), y: e.a.y + ey * Math.max(1, hi) };
      var pts = [A, Bq, { x: A.x + e.n.x * reach, y: A.y + e.n.y * reach }, { x: Bq.x + e.n.x * reach, y: Bq.y + e.n.y * reach }], b = PLAN.bounds(pts);
      for (y = Math.max(0, Math.floor((b.y - y0) / c)); y <= Math.min(ny - 1, Math.floor((b.y + b.h - y0) / c)); y++)
        for (x = Math.max(0, Math.floor((b.x - x0) / c)); x <= Math.min(nx - 1, Math.floor((b.x + b.w - x0) / c)); x++) {
          var j = y * nx + x;
          if (!free[j]) continue;
          var s = against(at(j), e);
          if (s.t >= lo && s.t <= hi && s.out > depth0 / 12 && s.out <= reach) list.push({ j: j, out: s.out });
        }
      return L ? list : [];
    }
    // The places people need to reach
    var dests = [];
    pieces.forEach(function (pc, k) {
      var want = pc.role === 'bed' ? { left: 1, right: 1 } : pc.role === 'seat' || pc.role === 'desk' || pc.role === 'dresser' ? { front: 1 } : null;
      if (!want) return;
      edges(pc).forEach(function (e) {
        if (!want[e.name]) return;
        var lo = 0, hi = 1;
        if (pc.role === 'bed' && e.local) {   // beside a bed: where you stand is the lower part, below the nightstands
          var fa = (e.local.a.y + pc.d / 2) / pc.d, fb = (e.local.b.y + pc.d / 2) / pc.d;
          var t1 = (0.35 - fa) / (fb - fa), t2 = (0.95 - fa) / (fb - fa); lo = Math.min(t1, t2); hi = Math.max(t1, t2);
        }
        // A side set against a wall or another piece leaves nowhere to stand: nothing to reach
        if (!cellsNear(e, lo, hi, 0, REACH).some(function (z) { return z.out >= 12 / 12; })) return;
        // ...and the space you arrive in runs the whole side, plus 18" past each end (the way into it)
        var Ls = Math.hypot(e.b.x - e.a.x, e.b.y - e.a.y) * 12, ext = 18 / Ls;
        var zone = cellsNear(e, -ext, 1 + ext, 0, REACH);
        var mid = (lo + hi) / 2, stand = { x: e.a.x + (e.b.x - e.a.x) * mid + e.n.x, y: e.a.y + (e.b.y - e.a.y) * mid + e.n.y };   // 12" out
        dests.push({ piece: k, side: e.name, cells: zone.map(function (z) { return z.j; }), stand: stand });
      });
    });

    // From each door: the widest way to every square (then the shortest of those, kept to the middle)
    var NB = [[1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, 1.414], [1, -1, 1.414], [-1, 1, 1.414], [-1, -1, 1.414]];
    function run(src, nd) {
      function start(j) { var q = at(j); return nd.at ? Math.hypot(q.x - nd.at.x, q.y - nd.at.y) / c : GEO.segDist(q, nd.seg.a, nd.seg.b) / c; }
      var B = new Int16Array(N).fill(-1), cost = new Float64Array(N).fill(Infinity), par = new Int32Array(N).fill(-1), done = new Uint8Array(N), h = new Heap();
      function b0(j) { return inDoor[j] ? CAP : wide[j]; }   // on an opening, its own width counts from the start
      src.forEach(function (j) { if (!inside[j]) return; B[j] = b0(j); cost[j] = start(j); h.push((CAP - B[j]) * 1e7 + cost[j], j); });
      if (!h.v.length) src.forEach(function (j) { B[j] = b0(j); cost[j] = start(j); h.push((CAP - B[j]) * 1e7 + cost[j], j); });
      while (h.v.length) {
        var j = h.pop();
        if (done[j]) continue;
        done[j] = 1;
        var jx = j % nx, jy = (j - jx) / nx;
        for (var m = 0; m < 8; m++) {
          var ax = jx + NB[m][0], ay = jy + NB[m][1];
          if (ax < 0 || ay < 0 || ax >= nx || ay >= ny) continue;
          var q = ay * nx + ax;
          if (!free[q] || done[q]) continue;
          var wq = inDoor[q] ? CAP : wide[q], nb = Math.min(B[j], wq);
          var nc = cost[j] + NB[m][2] * (1 + 6 / (wq + 6));   // a little extra cost near things keeps routes centered
          if (nb > B[q] || (nb === B[q] && nc < cost[q])) { B[q] = nb; cost[q] = nc; par[q] = j; h.push((CAP - nb) * 1e7 + nc, q); }
        }
      }
      return { B: B, cost: cost, par: par };
    }
    var runs = nodes.map(function (nd) { return run(nd.cells, nd); });
    // Best way into a place: from a square next to it (the place itself is left out of the pinch)
    function reach(rn, dest) {
      var mark = {}, best = -1;
      if (dest.through) {   // an opening: reached once the route is on it, its own width counted
        dest.cells.forEach(function (j) {
          if (rn.B[j] > -1 && (best < 0 || rn.B[j] > rn.B[best] || (rn.B[j] === rn.B[best] && rn.cost[j] < rn.cost[best]))) best = j;
        });
        return best;
      }
      dest.cells.forEach(function (j) { mark[j] = 1; });
      dest.cells.forEach(function (j) {
        if (rn.par[j] < 0 && rn.B[j] > -1) { best = j; return; }   // a door or opening is right on it
        var jx = j % nx, jy = (j - jx) / nx;
        for (var m = 0; m < 8; m++) {
          var ax = jx + NB[m][0], ay = jy + NB[m][1], q = ay * nx + ax;
          if (ax < 0 || ay < 0 || ax >= nx || ay >= ny || mark[q] || rn.B[q] < 0) continue;
          if (best < 0 || rn.B[q] > rn.B[best] || (rn.B[q] === rn.B[best] && rn.cost[q] < rn.cost[best])) best = q;
        }
      });
      return best;
    }
    function trace(rn, j) { var path = []; while (j > -1) { path.push(j); j = rn.par[j]; } return path.reverse(); }
    // The pinch, measured across: from the nearest thing in the way, straight through to the far side
    function pinchLine(j) {
      var p = at(j), R = Math.ceil(dist[j]) + 1, jx = j % nx, jy = (j - jx) / nx, best = -1, bd = Infinity;
      for (y = Math.max(0, jy - R); y <= Math.min(ny - 1, jy + R); y++)
        for (x = Math.max(0, jx - R); x <= Math.min(nx - 1, jx + R); x++) {
          var q = y * nx + x;
          if (free[q]) continue;
          var dd = (x - jx) * (x - jx) + (y - jy) * (y - jy);
          if (dd < bd) { bd = dd; best = q; }
        }
      if (best < 0) return null;
      var a = at(best), u = { x: p.x - a.x, y: p.y - a.y }, L = Math.hypot(u.x, u.y) || 1;
      u = { x: u.x / L, y: u.y / L };
      var b = null;
      for (var s = 0; s < 2 * CAP / 12 + 2; s += c / 2) {
        var k = cellOf({ x: p.x + u.x * s, y: p.y + u.y * s });
        if (k < 0) break;
        if (!free[k]) { b = at(k); break; }
      }
      if (!b) return null;
      function what(q) {
        var k = cellOf(q);
        if (k > -1 && owner[k] > -1) return { type: 'piece', i: owner[k] };
        return { type: 'wall' };
      }
      var A = { x: a.x + u.x * c / 2, y: a.y + u.y * c / 2 }, Bp = { x: b.x - u.x * c / 2, y: b.y - u.y * c / 2 };
      return { a: A, b: Bp, between: [what(a), what(b)] };
    }

    var out = [];
    // Each room: its most open spot (furthest from anything in the way), so open rooms
    // like a kitchen get a route too. Arriving means getting within 18" of it.
    rooms.forEach(function (poly, r) {
      var b = PLAN.bounds(poly), best = -1;
      for (y = Math.max(0, Math.floor((b.y - y0) / c)); y <= Math.min(ny - 1, Math.floor((b.y + b.h - y0) / c)); y++)
        for (x = Math.max(0, Math.floor((b.x - x0) / c)); x <= Math.min(nx - 1, Math.floor((b.x + b.w - x0) / c)); x++) {
          var j = y * nx + x;
          if (free[j] && !inDoor[j] && (best < 0 || dist[j] > dist[best]) && PLAN.pointInPoly(at(j), poly)) best = j;
        }
      if (best < 0) return;
      var st = at(best), zone = [], R = 18 / 12;
      for (y = Math.max(0, Math.floor((st.y - R - y0) / c)); y <= Math.min(ny - 1, Math.floor((st.y + R - y0) / c)); y++)
        for (x = Math.max(0, Math.floor((st.x - R - x0) / c)); x <= Math.min(nx - 1, Math.floor((st.x + R - x0) / c)); x++) {
          var q = y * nx + x;
          if (free[q] && Math.hypot(at(q).x - st.x, at(q).y - st.y) <= R) zone.push(q);
        }
      dests.push({ room: r, cells: zone, stand: st, quiet: true });
    });
    // Every pair of doors and openings, once. A pair that can't be reached is only
    // flagged between two doors (an opening into a room with no marked door is normal).
    for (var na = 0; na < nodes.length; na++) for (var nb = na + 1; nb < nodes.length; nb++)
      dests.push({ node: nb, only: na, cells: nodes[nb].cells, stand: nodes[nb].at || null, through: nodes[nb].type === 'passage',
                   quiet: nodes[na].type !== 'door' || nodes[nb].type !== 'door' });
    // For drawing: the last stretch inside the place being reached, from where the route
    // enters it to where you'd stand (the shortest way through its own squares)
    function finish(dest, j) {
      var mark = {}, par = {}, queue = [j], seen = {}, best = j, bd = Infinity;
      dest.cells.forEach(function (q) { mark[q] = 1; });
      seen[j] = 1;
      while (queue.length) {
        var q = queue.shift(), pq = at(q), dd = dest.stand ? Math.hypot(pq.x - dest.stand.x, pq.y - dest.stand.y) : 0;
        if (dd < bd) { bd = dd; best = q; }
        var qx = q % nx, qy = (q - qx) / nx;
        for (var m = 0; m < 8; m++) {
          var ax = qx + NB[m][0], ay = qy + NB[m][1], w = ay * nx + ax;
          if (ax < 0 || ay < 0 || ax >= nx || ay >= ny || seen[w] || !mark[w]) continue;
          seen[w] = 1; par[w] = q; queue.push(w);
        }
      }
      var tail = [];
      for (var t = best; t !== j && t != null; t = par[t]) tail.push(at(t));
      tail.reverse();
      if (dest.node != null && dest.stand) tail.push(dest.stand);
      return tail;
    }
    dests.forEach(function (dest) {
      if (!dest.cells.length) return;
      var pick = null;
      runs.forEach(function (rn, k) {
        if (dest.node === k || (dest.only != null && dest.only !== k)) return;
        if (dest.only == null && nodes[k].type !== 'door') return;   // furniture and rooms are reached from the doors
        var j = reach(rn, dest);
        if (j < 0) return;
        if (!pick || rn.B[j] > pick.rn.B[pick.j] || (rn.B[j] === pick.rn.B[pick.j] && rn.cost[j] < pick.rn.cost[pick.j])) pick = { k: k, rn: rn, j: j };
      });
      var to = dest.node != null ? { node: dest.node } : dest.room != null ? { room: dest.room } : { piece: dest.piece, side: dest.side };
      if (!pick) {
        if (!dest.quiet) out.push({ to: to, from: dest.only != null ? dest.only : -1, blocked: true, width: 0, status: 'close', path: [] });
        return;
      }
      var cells = trace(pick.rn, pick.j), width = pick.rn.B[pick.j], pinch = null;
      if (width < CAP) {
        var pj = -1;
        cells.forEach(function (j) { if (!inDoor[j] && (pj < 0 || wide[j] < wide[pj])) pj = j; });
        if (pj > -1) pinch = pinchLine(pj);
        // Measured across the pinch, edge to edge. No far side within reach: it's open floor after all.
        width = pinch ? Math.min(CAP, Math.round(Math.hypot(pinch.a.x - pinch.b.x, pinch.a.y - pinch.b.y) * 12)) : CAP;
      }
      out.push({ to: to, from: pick.k,
                 path: (nodes[pick.k].at ? [nodes[pick.k].at] : []).concat(cells.map(at), finish(dest, pick.j)), cells: cells, width: width, open: width >= CAP, status: status(width),
                 blocked: width < 12, pinch: width < CAP ? pinch : null });
    });
    // Dining sides that a route passes behind (people walk behind seated guests there)
    var behind = {};
    pieces.forEach(function (pc, k) {
      if (pc.role !== 'dining' && pc.role !== 'island') return;
      edges(pc).forEach(function (e) {
        var zone = {}; cellsNear(e, 0, 1, BEHIND[0], BEHIND[1]).forEach(function (z) { zone[z.j] = 1; });
        var hit = out.some(function (r) {
          if (r.to.piece === k) return false;
          return (r.cells || []).some(function (j) { return zone[j] && !inDoor[j]; });
        });
        if (hit) (behind[k] = behind[k] || {})[e.name] = true;
      });
    });
    out.forEach(function (r) { delete r.cells; });
    return { routes: out, behind: behind, cell: c,
             nodes: nodes.map(function (nd) { return nd.type === 'door' ? { type: 'door', k: nd.k } : { type: 'passage', k: nd.k, rooms: nd.seg.rooms, a: nd.seg.a, b: nd.seg.b, w: nd.seg.w }; }) };
  }

  return { RULE: RULE, CAP: CAP, routes: routes, status: status };
})();
