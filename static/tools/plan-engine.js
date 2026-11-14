/* =====================================================================
   STUDIO LOU PLAN ENGINE
   Shared by the Floor Plan Parser and the modes built on it
   (Measure, Furnish, Light, 3D). Plain JavaScript, no build step.

   SNAP   reads the plan image: wall map, printed room names, box snapping,
          and pixels per foot.
   PLAN   measurement and scale helpers that work in real feet.

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
    return { rooms: rooms, ppf: ppf, ppfRooms: ppf ? voters : 0, wallPx: a.k };
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
  function area(r) { return (r.width && r.length) ? r.width * r.length : 0; }
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

  return {
    MISMATCH: MISMATCH,
    fmtFtIn: fmtFtIn, parseFtIn: parseFtIn, area: area, fmtArea: fmtArea,
    scaleFromAnalysis: scaleFromAnalysis, scaleFromLine: scaleFromLine,
    boxFt: boxFt, mismatch: mismatch
  };
})();
