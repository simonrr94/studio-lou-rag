
(function(){
  var BASE = Date.UTC(2026, 10, 26, 2, 10, 0);   // Nov 25, 7:10 PM in Phoenix
  var RD = Date;
  function D(a,b,c,d,e,f,g){ if (!arguments.length) return new RD(BASE); return arguments.length === 1 ? new RD(a) : new RD(a,b||0,c||1,d||0,e||0,f||0,g||0); }
  D.prototype = RD.prototype; D.now = function(){ return BASE; }; D.UTC = RD.UTC; D.parse = RD.parse;
  window.Date = D;
  var s = 12345; Math.random = function(){ s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
})();
