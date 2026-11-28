const fs = require('fs'), vm = require('vm');
const ctx = { Math, console, Uint8Array, Int32Array, Float32Array, Uint32Array, Object, JSON, Array, String, Number, isFinite };
vm.createContext(ctx);
const src = fs.readFileSync(process.argv[2], 'utf8');
for (const name of ['WALLS', 'KITCHEN']) { const s = src.indexOf('var ' + name + ' = (function'), e = src.indexOf('})();', s) + 5; vm.runInContext(src.slice(s, e) + '\nthis.' + name + ' = ' + name + ';', ctx); }
const meta = JSON.parse(fs.readFileSync(process.argv[3] + '.json'));
const g = new Uint8Array(fs.readFileSync(process.argv[3] + '.gray'));
const G = { g, w: meta.w, h: meta.h };
const res = ctx.WALLS.measure(G, meta.rooms, meta.hints);
const fx = ctx.KITCHEN.find(G, res, meta.fixtures);
console.log(JSON.stringify({ ppf: res.ppf, fx: fx.filter(f => f.kind === 'fireplace') }));
