/* AquaHistorian 4.2 trend renderer - plain canvas, no external libraries. */
(function () {
  "use strict";
  var canvas = document.getElementById("trend");
  var dataEl = document.getElementById("trend-data");
  if (!canvas || !dataEl) { return; }
  var data;
  try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }
  // Keep only numeric (time, value) pairs; anything else is ignored by the chart.
  var pts = (data.points || []).filter(function (p) {
    return Array.isArray(p) && typeof p[0] === "number" && typeof p[1] === "number" && isFinite(p[0]) && isFinite(p[1]);
  });
  var tip = document.getElementById("trend-tip");
  var M = { l: 64, r: 16, t: 14, b: 34 };
  var view = [];

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function fmtTime(ts, withSec) {
    var d = new Date(ts * 1000);
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + (withSec ? ":" + pad(d.getSeconds()) : "");
  }
  function fmtVal(v) {
    var a = Math.abs(v);
    return a >= 1000 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
  }
  // min/max bucketing so long windows stay fast and keep spikes visible
  function downsample(src, buckets) {
    if (src.length <= buckets * 2) { return src.slice(); }
    var out = [], size = src.length / buckets;
    for (var i = 0; i < buckets; i++) {
      var s = Math.floor(i * size), e = Math.min(src.length, Math.floor((i + 1) * size));
      var lo = src[s], hi = src[s];
      for (var j = s; j < e; j++) {
        if (src[j][1] < lo[1]) { lo = src[j]; }
        if (src[j][1] > hi[1]) { hi = src[j]; }
      }
      if (lo[0] <= hi[0]) { out.push(lo); if (hi !== lo) { out.push(hi); } }
      else { out.push(hi); out.push(lo); }
    }
    return out;
  }

  function draw() {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth, h = canvas.clientHeight || 320;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.font = "11px Segoe UI, Tahoma, Arial, sans-serif";
    var pw = w - M.l - M.r, ph = h - M.t - M.b;
    ctx.strokeStyle = "#c3ced9"; ctx.strokeRect(M.l + 0.5, M.t + 0.5, pw, ph);
    if (!pts.length) {
      ctx.fillStyle = "#66768a"; ctx.textAlign = "center";
      ctx.fillText("No numeric data", M.l + pw / 2, M.t + ph / 2);
      view = []; return;
    }
    view = downsample(pts, Math.max(50, Math.floor(pw)));
    var x0 = pts[0][0], x1 = pts[pts.length - 1][0];
    var y0 = Infinity, y1 = -Infinity;
    pts.forEach(function (p) { if (p[1] < y0) { y0 = p[1]; } if (p[1] > y1) { y1 = p[1]; } });
    if (x1 === x0) { x0 -= 30; x1 += 30; }
    var span = y1 - y0 || Math.abs(y1) * 0.1 || 1;
    y0 -= span * 0.08; y1 += span * 0.08;
    var sx = function (t) { return M.l + (t - x0) / (x1 - x0) * pw; };
    var sy = function (v) { return M.t + ph - (v - y0) / (y1 - y0) * ph; };

    ctx.fillStyle = "#66768a"; ctx.strokeStyle = "#edf1f5";
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (var i = 0; i <= 5; i++) {
      var v = y0 + (y1 - y0) * i / 5, y = Math.round(sy(v)) + 0.5;
      ctx.beginPath(); ctx.moveTo(M.l + 1, y); ctx.lineTo(M.l + pw, y); ctx.stroke();
      ctx.fillText(fmtVal(v), M.l - 6, y);
    }
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    var nx = Math.max(2, Math.min(8, Math.floor(pw / 110)));
    for (var k = 0; k <= nx; k++) {
      var t = x0 + (x1 - x0) * k / nx, x = Math.round(sx(t)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, M.t + 1); ctx.lineTo(x, M.t + ph); ctx.stroke();
      ctx.fillText(fmtTime(t, (x1 - x0) < 600), x, M.t + ph + 6);
    }
    ctx.save();
    ctx.beginPath(); ctx.rect(M.l, M.t, pw, ph); ctx.clip();
    ctx.strokeStyle = "#1f7fc0"; ctx.lineWidth = 1.6; ctx.lineJoin = "round";
    ctx.beginPath();
    view.forEach(function (p, idx) {
      var px = sx(p[0]), py = sy(p[1]);
      if (idx === 0) { ctx.moveTo(px, py); } else { ctx.lineTo(px, py); }
    });
    ctx.stroke();
    if (view.length === 1) {
      ctx.fillStyle = "#1f7fc0"; ctx.beginPath(); ctx.arc(sx(view[0][0]), sy(view[0][1]), 3, 0, 7); ctx.fill();
    }
    ctx.restore();
    if (data.units) {
      ctx.save(); ctx.fillStyle = "#66768a"; ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillText(data.units, M.l + 6, M.t + 4); ctx.restore();
    }
    canvas._sx = sx; canvas._sy = sy;
  }

  canvas.addEventListener("mousemove", function (ev) {
    if (!view.length || !canvas._sx) { return; }
    var rect = canvas.getBoundingClientRect(), mx = ev.clientX - rect.left;
    var best = null, bd = Infinity;
    view.forEach(function (p) { var d = Math.abs(canvas._sx(p[0]) - mx); if (d < bd) { bd = d; best = p; } });
    if (!best || bd > 40) { tip.hidden = true; return; }
    tip.textContent = new Date(best[0] * 1000).toLocaleString() + "  " + fmtVal(best[1]) + (data.units ? " " + data.units : "");
    tip.hidden = false;
    tip.style.left = (canvas.offsetLeft + Math.min(canvas._sx(best[0]) + 20, rect.width - tip.offsetWidth)) + "px";
    tip.style.top = (canvas.offsetTop + Math.max(4, canvas._sy(best[1]) - 10)) + "px";
  });
  canvas.addEventListener("mouseleave", function () { tip.hidden = true; });
  window.addEventListener("resize", draw);
  draw();
}());
