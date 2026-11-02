(function () {
  var G = window.G, C = Rbx3D.core, mul = C.mul, tr = C.tr, rx = C.rx, ry = C.ry, PC = C.PC;
  var cv = document.getElementById('gl'), R = C.mk(cv), $ = function (id) { return document.getElementById(id); };
  if (!R) { document.body.innerHTML = '<p style="padding:20px">This browser does not support WebGL.</p>'; return; }
  function size() { cv.width = innerWidth; cv.height = innerHeight; }
  size(); addEventListener('resize', size); R.gl.clearColor(.62, .78, .94, 1);
  var IDENT = new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]);

  /* ---------- the place ---------- */
  var solids = [], world = null, spawn = [0, 6, 0];
  var F6 = [[[0,0,1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]], [[0,0,-1],[1,-1,-1],[-1,-1,-1],[-1,1,-1],[1,1,-1]], [[1,0,0],[1,-1,1],[1,-1,-1],[1,1,-1],[1,1,1]],
            [[-1,0,0],[-1,-1,-1],[-1,-1,1],[-1,1,1],[-1,1,-1]], [[0,1,0],[-1,1,1],[1,1,1],[1,1,-1],[-1,1,-1]], [[0,-1,0],[-1,-1,-1],[1,-1,-1],[1,-1,1],[-1,-1,1]]];
  function build(parts) {
    var g = { pos: [], nrm: [], uv: [], col: [] };
    parts.forEach(function (p) {
      var x = p[0], y = p[1], z = p[2], m = p.slice(3, 12), hx = p[12] / 2, hy = p[13] / 2, hz = p[14] / 2, c = [p[15] / 255, p[16] / 255, p[17] / 255];
      if (p[18] >= .95) return;
      function rot(v) { return [m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[3] * v[0] + m[4] * v[1] + m[5] * v[2], m[6] * v[0] + m[7] * v[1] + m[8] * v[2]]; }
      F6.forEach(function (f) {
        var n = rot(f[0]);
        [1, 2, 3, 1, 3, 4].forEach(function (i) {
          var q = rot([f[i][0] * hx, f[i][1] * hy, f[i][2] * hz]);
          g.pos.push(q[0] + x, q[1] + y, q[2] + z); g.nrm.push(n[0], n[1], n[2]); g.uv.push(0, 0); g.col.push(c[0], c[1], c[2]);
        });
      });
      if (p[19]) {
        var ex = Math.abs(m[0]) * hx + Math.abs(m[1]) * hy + Math.abs(m[2]) * hz, ey = Math.abs(m[3]) * hx + Math.abs(m[4]) * hy + Math.abs(m[5]) * hz, ez = Math.abs(m[6]) * hx + Math.abs(m[7]) * hy + Math.abs(m[8]) * hz;
        solids.push([x - ex, x + ex, y - ey, y + ey, z - ez, z + ez]);
      }
    });
    return g;
  }
  fetch(G.place).then(function (r) { return r.json(); }).then(function (d) {
    var parts = d.parts || [];
    if (d.spawn) spawn = d.spawn;
    if (!parts.length) { parts = [[0, -.5, 0, 1,0,0, 0,1,0, 0,0,1, 512, 1, 512, 99, 140, 80, 0, 1]]; $('note').textContent = 'No parts could be read from this place, so a flat baseplate is shown.'; }
    var g = build(parts); world = C.mkObj(R, g, tr(0, 0, 0), [1, 1, 1], 0, null);
    respawn();
  }).catch(function () { $('note').textContent = 'Could not load the place.'; });

  /* ---------- the character ---------- */
  var chars = [], P = { x: 0, y: 6, z: 0, vy: 0, yaw: 0, ground: false }, cam = { yaw: 0, pitch: .35, dist: 12 }, keys = {}, phase = 0, dead = 0, bits = null, paused = false, sens = 1;
  C.avatar(R, G.eq).then(function (o) { chars = o; o.forEach(function (x) { x.m0 = x.m; }); });
  var HALF = .6, H = 5, JT = { 2: [1.5, 4, 0], 3: [-1.5, 4, 0], 4: [.5, 2, 0], 5: [-.5, 2, 0] };
  function respawn() { P.x = spawn[0]; P.y = spawn[1] + 3; P.z = spawn[2]; P.vy = 0; dead = 0; bits = null; $('hp').style.width = '100%'; }
  function hit(b) { return P.x + HALF > b[0] && P.x - HALF < b[1] && P.y + H > b[2] && P.y < b[3] && P.z + HALF > b[4] && P.z - HALF < b[5]; }
  function move(axis, d) {
    P[axis] += d;
    if (axis === 'y' && !solids.length && P.y < 0 && P.y > -4) { P.y = 0; P.vy = 0; P.ground = true; }
    solids.forEach(function (b) {
      if (!hit(b)) return;
      if (axis === 'y') { if (d < 0) { P.y = b[3]; P.ground = true; } else P.y = b[2] - H; P.vy = 0; }
      else if (b[3] - P.y <= 1.7) { P.y = b[3]; }
      else if (axis === 'x') P.x = d > 0 ? b[0] - HALF : b[1] + HALF;
      else P.z = d > 0 ? b[4] - HALF : b[5] + HALF;
    });
  }
  function die() {
    if (dead || !chars.length) return; dead = 1; $('hp').style.width = '0%';
    var cy = Math.cos(P.yaw), sy = Math.sin(P.yaw);
    bits = PC.map(function (c) {
      return { c: [P.x + c[0] * cy + c[2] * sy, P.y + c[1], P.z - c[0] * sy + c[2] * cy], d: [0, 0, 0], v: [(Math.random() - .5) * 18, 10 + Math.random() * 14, (Math.random() - .5) * 18], a: [0, 0], w: [(Math.random() - .5) * 10, (Math.random() - .5) * 10] };
    });
    setTimeout(respawn, 3200);
  }
  function step(dt) {
    var f = (keys.w ? 1 : 0) - (keys.s ? 1 : 0), s = (keys.d ? 1 : 0) - (keys.a ? 1 : 0), sy = Math.sin(cam.yaw), cy = Math.cos(cam.yaw);
    var dx = sy * f + cy * s, dz = -cy * f + sy * s, len = Math.hypot(dx, dz), moving = len > 0;
    if (moving) { dx /= len; dz /= len; P.yaw = Math.atan2(dx, dz); phase += dt * 11; }
    P.vy -= 196.2 * dt; if (keys[' '] && P.ground) { P.vy = 50; P.ground = false; }
    move('x', moving ? dx * 16 * dt : 0); move('z', moving ? dz * 16 * dt : 0); P.ground = false; move('y', P.vy * dt);
    if (P.y < -150) die();
    return moving;
  }
  function pose(moving) {
    var sw = moving && P.ground ? Math.sin(phase) * .85 : 0, a = {};
    if (!P.ground) { a[2] = -2.5; a[3] = -2.5; a[4] = .25; a[5] = -.25; } else { a[2] = sw; a[3] = -sw; a[4] = -sw; a[5] = sw; }
    return a;
  }
  function animate(dt, moving) {
    if (dead && bits) {
      var cy = Math.cos(P.yaw), sy = Math.sin(P.yaw);
      bits.forEach(function (b) { b.v[1] -= 60 * dt; for (var i = 0; i < 3; i++) b.d[i] += b.v[i] * dt; b.a[0] += b.w[0] * dt; b.a[1] += b.w[1] * dt; });
      var W = mul(tr(P.x, P.y, P.z), ry(P.yaw));
      chars.forEach(function (o) {
        var b = bits[o.part], base = mul(W, o.m0), rot = mul(rx(b.a[0]), ry(b.a[1]));
        o.m = mul(tr(b.c[0] + b.d[0], b.c[1] + b.d[1], b.c[2] + b.d[2]), mul(rot, mul(tr(-b.c[0], -b.c[1], -b.c[2]), base))); o.r = mul(rot, ry(P.yaw));
      });
      return;
    }
    var ang = pose(moving), W = mul(tr(P.x, P.y, P.z), ry(P.yaw));
    chars.forEach(function (o) {
      var a = ang[o.part] || 0, J = JT[o.part];
      if (J && a) { o.m = mul(W, mul(tr(J[0], J[1], J[2]), mul(rx(a), mul(tr(-J[0], -J[1], -J[2]), o.m0)))); o.r = mul(ry(P.yaw), rx(a)); }
      else { o.m = mul(W, o.m0); o.r = ry(P.yaw); }
    });
  }

  /* ---------- loop ---------- */
  var last = performance.now(), frames = 0, fpsT = last;
  (function loop(now) {
    var dt = Math.min(.05, (now - last) / 1000); last = now;
    var moving = false;
    if (world && !paused && !dead) moving = step(dt);
    if (world && !paused) animate(dt, moving);
    var st = { yaw: cam.yaw, pitch: cam.pitch, dist: cam.dist, k: 1, c: [P.x, P.y + 3, P.z] };
    R.gl.clearColor(.62, .78, .94, 1); R.gl.disable(R.gl.CULL_FACE);
    C.draw(R, (world ? [world] : []).concat(chars), st, cv.width, cv.height);
    frames++; if (now - fpsT > 1000) { if ($('fps').style.display === 'block') $('fps').textContent = frames + ' FPS'; frames = 0; fpsT = now; }
    requestAnimationFrame(loop);
  })(performance.now());

  /* ---------- input ---------- */
  var drag = null;
  addEventListener('keydown', function (e) {
    if (e.target.tagName === 'INPUT') { if (e.key === 'Enter') { var t = e.target.value.trim(); if (t) say(G.user, t); e.target.value = ''; e.target.blur(); } else if (e.key === 'Escape') e.target.blur(); return; }
    if (e.key === 'Escape') { toggleMenu(); return; }
    if (e.key === '/') { e.preventDefault(); $('chat').focus(); return; }
    keys[e.key.toLowerCase()] = true; if (e.key === ' ') e.preventDefault();
  });
  addEventListener('keyup', function (e) { keys[e.key.toLowerCase()] = false; });
  cv.addEventListener('mousedown', function (e) { drag = [e.clientX, e.clientY]; });
  addEventListener('mouseup', function () { drag = null; });
  addEventListener('mousemove', function (e) {
    if (!drag || paused) return;
    cam.yaw += (e.clientX - drag[0]) * .006 * sens; cam.pitch = Math.max(-.4, Math.min(1.4, cam.pitch + (e.clientY - drag[1]) * .006 * sens)); drag = [e.clientX, e.clientY];
  });
  cv.addEventListener('wheel', function (e) { e.preventDefault(); cam.dist = Math.max(3, Math.min(60, cam.dist + e.deltaY * .02)); }, { passive: false });
  cv.addEventListener('contextmenu', function (e) { e.preventDefault(); });
  window.addEventListener('blur', function () { keys = {}; });

  /* ---------- interface ---------- */
  function say(who, text) {
    var d = document.createElement('div'); d.textContent = who + ': ' + text; $('log').appendChild(d);
    setTimeout(function () { d.style.opacity = 0; setTimeout(function () { d.remove(); }, 800); }, 9000);
  }
  function toast(t) { var d = $('toast'); d.textContent = t; d.style.display = 'block'; setTimeout(function () { d.style.display = 'none'; }, 2500); }
  function toggleMenu() { paused = !paused; $('menu').style.display = paused ? 'block' : 'none'; $('panel').style.display = 'none'; keys = {}; }
  function panel(html) { $('panel').innerHTML = html + '<button class="mb" id="pb">Back</button>'; $('panel').style.display = 'block'; $('pb').onclick = function () { $('panel').style.display = 'none'; }; }
  $('resume').onclick = toggleMenu; $('menubtn').onclick = toggleMenu;
  $('reset').onclick = function () { toggleMenu(); die(); };
  $('leave').onclick = function () { location.href = G.back; };
  $('shot').onclick = function () { cv.toBlob(function (b) { var a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'screenshot.png'; a.click(); }); toast('Screenshot saved'); };
  $('help').onclick = function () { panel('<p><b>Controls</b></p><p>W A S D move<br>Space jump<br>Drag the mouse to turn the camera<br>Mouse wheel zoom<br>/ chat &nbsp; Esc menu</p>'); };
  $('settings').onclick = function () { panel('<p><b>Game Settings</b></p><p>Camera sensitivity <input id="sens" type="range" min="0.3" max="2.5" step="0.1" value="' + sens + '"></p><p><label><input id="fpsc" type="checkbox"' + ($('fps').style.display === 'block' ? ' checked' : '') + '> Show FPS</label></p>');
    $('sens').oninput = function () { sens = parseFloat(this.value); }; $('fpsc').onchange = function () { $('fps').style.display = this.checked ? 'block' : 'none'; }; };
  $('abuse').onclick = $('video').onclick = function () { toast('Not available in the test client'); };
  $('me').textContent = G.user; $('plist').innerHTML = '<div class="row">' + G.user + '</div>';
  if (G.tool) { $('slot1').textContent = G.tool; $('slot1').style.display = 'block'; }
})();
