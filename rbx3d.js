var Rbx3D = (function () {
  function addTri(o, v, raw) {
    var a = v[0].p, b = v[1].p, c = v[2].p, u = [b[0]-a[0], b[1]-a[1], b[2]-a[2]], w = [c[0]-a[0], c[1]-a[1], c[2]-a[2]],
        n = [u[1]*w[2]-u[2]*w[1], u[2]*w[0]-u[0]*w[2], u[0]*w[1]-u[1]*w[0]], l = Math.hypot(n[0], n[1], n[2]) || 1;
    v.forEach(function (x) {
      var q = x.n || [n[0]/l, n[1]/l, n[2]/l], t = x.t || [0, 0];
      o.pos.push(x.p[0], x.p[1], x.p[2]); o.nrm.push(q[0], q[1], q[2]); o.uv.push(t[0], raw ? t[1] : 1 - t[1]);
    });
  }
  function parseObj(txt) {
    var P = [], T = [], N = [], o = { pos: [], nrm: [], uv: [] };
    function ix(i, n) { return i < 0 ? n + i : i - 1; }
    txt.split('\n').forEach(function (l) {
      var a = l.trim().split(/\s+/), k = a[0];
      if (k === 'v') P.push(a.slice(1, 4).map(Number));
      else if (k === 'vt') T.push(a.slice(1, 3).map(Number));
      else if (k === 'vn') N.push(a.slice(1, 4).map(Number));
      else if (k === 'f') {
        var v = a.slice(1).map(function (s) {
          var p = s.split('/').map(function (x) { return x === '' ? NaN : parseInt(x, 10); });
          return { p: P[ix(p[0], P.length)], t: isNaN(p[1]) ? null : T[ix(p[1], T.length)], n: isNaN(p[2]) ? null : N[ix(p[2], N.length)] };
        });
        for (var i = 1; i < v.length - 1; i++) addTri(o, [v[0], v[i], v[i + 1]]);
      }
    });
    return o;
  }
  function parseV1(txt) {   // Roblox text mesh: "version 1.00", face count, then [pos][normal][uv] per vertex
    var s = txt.indexOf('version 1.00') === 0 ? 0.5 : 1, o = { pos: [], nrm: [], uv: [] },
        n = txt.split('\n').slice(2).join(' ').match(/-?\d*\.?\d+(?:e[-+]?\d+)?/gi).map(Number);
    for (var i = 0; i + 8 < n.length; i += 9) {
      o.pos.push(n[i]*s, n[i+1]*s, n[i+2]*s); o.nrm.push(n[i+3], n[i+4], n[i+5]); o.uv.push(n[i+6], n[i+7]);
    }
    return o;
  }
  function parseBin(buf) {  // Roblox binary mesh v2.xx / v3.xx
    var dv = new DataView(buf), b0 = 13, hs = dv.getUint16(b0, true), vs = dv.getUint8(b0 + 2), v3 = new Uint8Array(buf)[8] === 51,
        vc = dv.getUint32(b0 + (v3 ? 8 : 4), true), fc = dv.getUint32(b0 + (v3 ? 12 : 8), true), vo = b0 + hs, fo = vo + vc * vs, V = [], o = { pos: [], nrm: [], uv: [] };
    if (v3) { var nl = dv.getUint16(b0 + 6, true); if (nl > 1) fc = dv.getUint32(fo + fc * 12 + 4, true); }
    function f(x) { return dv.getFloat32(x, true); }
    for (var i = 0; i < vc; i++) { var b = vo + i * vs; V.push({ p: [f(b), f(b+4), f(b+8)], n: [f(b+12), f(b+16), f(b+20)], t: [f(b+24), f(b+28)] }); }
    for (var k = 0; k < fc; k++) addTri(o, [0, 1, 2].map(function (j) { return V[dv.getUint32(fo + k * 12 + j * 4, true)]; }), true);
    return o;
  }
  function mul(a, b) { var o = new Float32Array(16); for (var i = 0; i < 4; i++) for (var j = 0; j < 4; j++) { var s = 0; for (var k = 0; k < 4; k++) s += a[k*4+j] * b[i*4+k]; o[i*4+j] = s; } return o; }
  function rx(a) { var c = Math.cos(a), s = Math.sin(a); return new Float32Array([1,0,0,0, 0,c,s,0, 0,-s,c,0, 0,0,0,1]); }
  function ry(a) { var c = Math.cos(a), s = Math.sin(a); return new Float32Array([c,0,-s,0, 0,1,0,0, s,0,c,0, 0,0,0,1]); }
  function tr(x, y, z) { return new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, x,y,z,1]); }
  function sc(k) { return new Float32Array([k,0,0,0, 0,k,0,0, 0,0,k,0, 0,0,0,1]); }
  function pr(a) { var t = 1 / Math.tan(0.4), n = .1, f = 50; return new Float32Array([t/a,0,0,0, 0,t,0,0, 0,0,(f+n)/(n-f),-1, 0,0,2*f*n/(n-f),0]); }
  function sh(gl, type, src) { var s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; }


  var VS = 'attribute vec3 p,n,c;attribute vec2 t;uniform mat4 m,r;varying vec3 vn,vc;varying vec2 vt;void main(){gl_Position=m*vec4(p,1.);vn=(r*vec4(n,0.)).xyz;vt=t;vc=c;}';
  var FS = 'precision mediump float;uniform sampler2D s;uniform vec3 col;uniform float md,fv;varying vec3 vn,vc;varying vec2 vt;void main(){vec3 N=normalize(vn);float d=min(1.,max(dot(N,normalize(vec3(.4,.6,.7))),0.)*.55+max(dot(N,normalize(vec3(-.6,.2,-.5))),0.)*.2+.5);vec4 t=texture2D(s,vec2(vt.x,fv>.5?1.-vt.y:vt.y));vec3 c=md<.5?col*vc:(md>2.5?t.rgb*vc/.64:t.rgb);float a=(md>1.5&&md<2.5)?t.a:1.;if(a<.03)discard;gl_FragColor=vec4(c*d,a);}';
  function mk(cv) {
    var gl = cv.getContext('webgl', { preserveDrawingBuffer: true, antialias: true }) || cv.getContext('experimental-webgl');
    if (!gl) return null;
    var pg = gl.createProgram();
    gl.attachShader(pg, sh(gl, gl.VERTEX_SHADER, VS)); gl.attachShader(pg, sh(gl, gl.FRAGMENT_SHADER, FS)); gl.linkProgram(pg); gl.useProgram(pg);
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.clearColor(.88, .88, .88, 1);
    return { gl: gl, pg: pg, u: function (n) { return gl.getUniformLocation(pg, n); }, a: function (n) { return gl.getAttribLocation(pg, n); } };
  }
  function mkObj(R, g, m, col, md, tex) {
    var gl = R.gl;
    function B(a) { var b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(a), gl.STATIC_DRAW); return b; }
    return { b: g.col ? [B(g.pos), B(g.nrm), B(g.uv), B(g.col)] : [B(g.pos), B(g.nrm), B(g.uv)], n: g.pos.length / 3, m: m, col: col || [.75, .75, .75], md: md || 0, tex: tex || null };
  }
  function free(R, o) { o.b.forEach(function (b) { R.gl.deleteBuffer(b); }); if (o.tex) R.gl.deleteTexture(o.tex); }
  function box(w, h, d) {
    var x = w / 2, y = h / 2, z = d / 2, o = { pos: [], nrm: [], uv: [] },
        F = [[[0,0,1],[-x,-y,z],[x,-y,z],[x,y,z],[-x,y,z]], [[0,0,-1],[x,-y,-z],[-x,-y,-z],[-x,y,-z],[x,y,-z]], [[1,0,0],[x,-y,z],[x,-y,-z],[x,y,-z],[x,y,z]],
             [[-1,0,0],[-x,-y,-z],[-x,-y,z],[-x,y,z],[-x,y,-z]], [[0,1,0],[-x,y,z],[x,y,z],[x,y,-z],[-x,y,-z]], [[0,-1,0],[-x,-y,-z],[x,-y,-z],[x,-y,z],[-x,-y,z]]];
    F.forEach(function (f) { [1,2,3,1,3,4].forEach(function (i) { o.pos.push.apply(o.pos, f[i]); o.nrm.push.apply(o.nrm, f[0]); o.uv.push(0, 0); }); });
    return o;
  }
  function quad(w, h, z, y, x0) {
    var a = w / 2, b = h / 2, x = x0 || 0;
    return { pos: [x-a,y+b,z, x+a,y+b,z, x+a,y-b,z, x-a,y+b,z, x+a,y-b,z, x-a,y-b,z], nrm: [0,0,1, 0,0,1, 0,0,1, 0,0,1, 0,0,1, 0,0,1], uv: [0,0, 1,0, 1,1, 0,0, 1,1, 0,1] };
  }
  function loadTex(R, url, crop) {
    return new Promise(function (res) {
      var im = new Image();
      im.onload = function () {
        var s = im, gl = R.gl;
        if (crop) {
          var c = document.createElement('canvas'), w = im.width, h = im.height;
          c.width = Math.round((crop[2] - crop[0]) * w); c.height = Math.round((crop[3] - crop[1]) * h);
          c.getContext('2d').drawImage(im, crop[0] * w, crop[1] * h, c.width, c.height, 0, 0, c.width, c.height); s = c;
        }
        var t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, s);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        var pot = function (n) { return (n & (n - 1)) === 0; };
        if (pot(s.width) && pot(s.height)) { gl.generateMipmap(gl.TEXTURE_2D); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR); } else gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        res(t);
      };
      im.onerror = function () { res(null); }; im.src = url;
    });
  }
  function loadMesh(url) {
    return fetch(url).then(function (r) { return r.arrayBuffer(); }).then(function (buf) {
      var head = String.fromCharCode.apply(null, new Uint8Array(buf, 0, Math.min(12, buf.byteLength)));
      var nat = function (g) { g.natural = true; return g; };
      if (head.indexOf('version 1.') === 0) return nat(parseV1(new TextDecoder().decode(buf)));
      if (head.indexOf('version 2.') === 0 || head.indexOf('version 3.') === 0) return nat(parseBin(buf));
      return parseObj(new TextDecoder().decode(buf));
    });
  }
  function fit(g, maxd, x, y, z, bottom, off, natural) {   // size/place a mesh; off = saved position {x,y,z,r,s}
    var mn = [1e9,1e9,1e9], mx = [-1e9,-1e9,-1e9];
    for (var i = 0; i < g.pos.length; i++) { var a = i % 3; mn[a] = Math.min(mn[a], g.pos[i]); mx[a] = Math.max(mx[a], g.pos[i]); }
    var k = natural && g.natural ? 1 : maxd / (Math.max(mx[0]-mn[0], mx[1]-mn[1], mx[2]-mn[2]) || 1), c = [0,1,2].map(function (a) { return (mn[a] + mx[a]) / 2; });
    off = off || {}; var s = off.s || 1, lift = bottom ? (mx[1]-mn[1]) * k * s / 2 : 0;
    return mul(tr(x + (off.x || 0), y + (off.y || 0) + lift, z + (off.z || 0)), mul(ry((off.r || 0) * Math.PI / 180), mul(sc(s), mul(ry(Math.PI), mul(sc(k), tr(-c[0], -c[1], -c[2]))))));
  }

  var skinP;
  function loadSkin() { return skinP || (skinP = fetch('/static/models/r6.json').then(function (r) { return r.json(); })); }
  var E2F = [0, 1, 3, 2, 5, 4];                                                   // Roblox BodyPart number -> part index in the skin file
  var PC = [[0,4.5,0], [0,3,0], [1.5,3,0], [-1.5,3,0], [.5,1,0], [-.5,1,0]];       // head, torso, left arm, right arm, left leg, right leg
  var COL = [[.96,.8,.19], [.05,.41,.67], [.96,.8,.19], [.96,.8,.19], [.64,.74,.28], [.64,.74,.28]];
  function sub(sk, tint, mt, part) {
    var o = { pos: [], nrm: [], uv: [], col: [] };
    for (var i = 0; i < sk.mat.length; i++) if (sk.mat[i] === mt && sk.part[i] === part) {
      o.pos.push(sk.pos[i*3], sk.pos[i*3+1], sk.pos[i*3+2]); o.nrm.push(sk.nrm[i*3], sk.nrm[i*3+1], sk.nrm[i*3+2]);
      o.uv.push(sk.uv[i*2], sk.uv[i*2+1]); o.col.push(tint[i*3], tint[i*3+1], tint[i*3+2]);
    }
    return o;
  }
  var ARM = { right: [19,355,64,128], front: [85,355,64,128], left: [151,355,64,128], back: [217,355,64,128], top: [217,289,64,64], bottom: [217,485,64,64] };
  var ARML = { right: [308,355,64,128], front: [374,355,64,128], left: [440,355,64,128], back: [506,355,64,128], top: [308,289,64,64], bottom: [308,485,64,64] };
  var BOXES = {   // clothing template (585x559): part -> centre, size, face rectangles [x, y, w, h]
    1: { c: [0,3,0], s: [2,2,1], f: { front: [231,74,128,128], back: [427,74,128,128], right: [165,74,64,128], left: [361,74,64,128], top: [231,8,128,64], bottom: [231,204,128,64] } },
    3: { c: [-1.5,3,0], s: [1,2,1], f: ARM }, 2: { c: [1.5,3,0], s: [1,2,1], f: ARML },
    5: { c: [-.5,1,0], s: [1,2,1], f: ARM }, 4: { c: [.5,1,0], s: [1,2,1], f: ARML } };
  var FN = { front: [0,0,1], back: [0,0,-1], right: [-1,0,0], left: [1,0,0], top: [0,1,0], bottom: [0,-1,0] };
  function clothGeo(part, e) {            // a slightly larger box around the body part, every side textured from the template
    var b = BOXES[part], x = b.s[0] / 2 + e, y = b.s[1] / 2 + e, z = b.s[2] / 2 + e, g = { pos: [], nrm: [], uv: [] },
        Q = { front: [[-x,y,z],[x,y,z],[x,-y,z],[-x,-y,z]], back: [[x,y,-z],[-x,y,-z],[-x,-y,-z],[x,-y,-z]],
              right: [[-x,y,-z],[-x,y,z],[-x,-y,z],[-x,-y,-z]], left: [[x,y,z],[x,y,-z],[x,-y,-z],[x,-y,z]],
              top: [[-x,y,-z],[x,y,-z],[x,y,z],[-x,y,z]], bottom: [[-x,-y,z],[x,-y,z],[x,-y,-z],[-x,-y,-z]] };
    for (var f in b.f) {
      var r = b.f[f], u0 = r[0] / 585, v0 = r[1] / 559, u1 = (r[0] + r[2]) / 585, v1 = (r[1] + r[3]) / 559, uv = [[u0,v0],[u1,v0],[u1,v1],[u0,v1]], n = FN[f];
      [0,1,2,0,2,3].forEach(function (i) { var q = Q[f][i]; g.pos.push(q[0] + b.c[0], q[1] + b.c[1], q[2] + b.c[2]); g.nrm.push(n[0], n[1], n[2]); g.uv.push(uv[i][0], uv[i][1]); });
    }
    return g;
  }
  function avatar(R, eq) {
    var P = [], jobs = [];
    function add(g, m, col, md, tex, part) { var o = mkObj(R, g, m, col, md, tex); o.part = part; P.push(o); }
    function of(k) { return eq.filter(function (e) { return e.kind === k; })[0]; }
    var face = of('face'), shirt = of('shirt'), pants = of('pants'), ts = of('tshirt'), hat = of('hat'), tool = of('tool'), body = of('body'), skip = [0, 0, 0, 0, 0, 0];
    if (body) body.parts.forEach(function (p) { skip[E2F[p.p]] = 1; });
    jobs.push(loadSkin().then(function (sk) {
      var tint = []; sk.part.forEach(function (p) { tint.push(COL[p][0], COL[p][1], COL[p][2]); });
      return loadTex(R, face ? '/static/img/head_atlas_noface.png' : '/static/img/head_atlas.png').then(function (t) {
        for (var p = 0; p < 6; p++) if (!skip[p]) [0, 1].forEach(function (mt) { var g = sub(sk, tint, mt, p); if (g.pos.length) add(g, tr(0,0,0), [1,1,1], mt ? 3 : 0, mt ? t : null, p); });
      });
    }).catch(function () {
      [[box(1.25,1.25,1.25), 0], [box(2,2,1), 1], [box(1,2,1), 2], [box(1,2,1), 3], [box(1,2,1), 4], [box(1,2,1), 5]].forEach(function (b) { if (!skip[b[1]]) add(b[0], tr(PC[b[1]][0], PC[b[1]][1], PC[b[1]][2]), COL[b[1]], 0, null, b[1]); });
    }));
    if (body) body.parts.forEach(function (bp) {            // an R6 body from Roblox: its own meshes replace the default parts
      var f = E2F[bp.p];
      jobs.push(Promise.all([loadMesh('/files/' + bp.mesh), bp.tex ? loadTex(R, '/files/' + bp.tex) : null]).then(function (r) {
        add(r[0], tr(PC[f][0], PC[f][1], PC[f][2]), COL[f], r[1] ? 1 : 0, r[1], f);
      }).catch(function () {}));
    });
    if (face || skip[0]) jobs.push(loadTex(R, face ? '/files/' + face.tex : '/static/img/face_default.png').then(function (t) { if (t) add(quad(1.1,1.1,skip[0] ? .66 : .608,4.5), tr(0,0,0), null, 2, t, 0); }));
    [[shirt, [1, 3, 2], .012], [pants, [1, 5, 4], .02]].forEach(function (c) {      // clothes wrap the whole body like on the real site
      if (c[0]) jobs.push(loadTex(R, '/files/' + c[0].tex).then(function (t) { if (t) c[1].forEach(function (p) { add(clothGeo(p, c[2]), tr(0,0,0), null, 2, t, p); }); }));
    });
    if (ts) jobs.push(loadTex(R, '/files/' + ts.tex).then(function (t) { if (t) add(quad(1.4,1.4,.525,3.1), tr(0,0,0), null, 2, t, 1); }));
    [[hat, 1.5, 0, 4.82, 0, true, 0], [tool, 2.6, -1.5, 2.3, .9, false, 3]].forEach(function (h) {
      var e = h[0]; if (!e) return;
      jobs.push(Promise.all([loadMesh('/files/' + e.mesh), e.tex ? loadTex(R, '/files/' + e.tex) : null]).then(function (r) {
        add(r[0], fit(r[0], h[1], h[2], h[3], h[4], h[5], e.off, true), null, r[1] ? 1 : 0, r[1], h[6]);
        if (e.off && e.off.f) P[P.length - 1].flip = 1;
      }).catch(function () {}));
    });
    return Promise.all(jobs).then(function () { P.sort(function (a, b) { return (a.md === 2 ? 1 : 0) - (b.md === 2 ? 1 : 0); }); return P; });
  }
  function aloneObjs(R, it) {
    if (it.mesh) return Promise.all([loadMesh('/files/' + it.mesh), it.tex ? loadTex(R, '/files/' + it.tex) : null]).then(function (r) { var o = mkObj(R, r[0], fit(r[0], 2, 0, 0, 0, false), null, r[1] ? 1 : 0, r[1]); if (it.off && it.off.f) o.flip = 1; return [o]; });
    return loadTex(R, '/files/' + it.tex).then(function (t) { return t ? [mkObj(R, quad(2, 2, 0, 0), tr(0, 0, 0), null, 2, t)] : []; });
  }
  function draw(R, objs, st, w, h) {
    var gl = R.gl, Rm = mul(rx(st.pitch), ry(st.yaw)),
        V = mul(pr(w / h), mul(tr(0, st.dy || 0, -st.dist), mul(Rm, mul(sc(st.k), tr(-st.c[0], -st.c[1], -st.c[2])))));
    gl.viewport(0, 0, w, h); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    objs.forEach(function (o) {
      gl.uniformMatrix4fv(R.u('r'), false, o.r ? mul(Rm, o.r) : Rm);
      gl.uniformMatrix4fv(R.u('m'), false, mul(V, o.m)); gl.uniform1f(R.u('md'), o.md); gl.uniform1f(R.u('fv'), o.flip ? 1 : 0); gl.uniform3fv(R.u('col'), o.col);
      if (o.tex) gl.bindTexture(gl.TEXTURE_2D, o.tex);
      [['p', 3], ['n', 3], ['t', 2], ['c', 3]].forEach(function (a, i) {
        var l = R.a(a[0]);
        if (o.b[i]) { gl.bindBuffer(gl.ARRAY_BUFFER, o.b[i]); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, a[1], gl.FLOAT, false, 0, 0); }
        else { gl.disableVertexAttribArray(l); gl.vertexAttrib3f(l, 1, 1, 1); }
      });
      gl.drawArrays(gl.TRIANGLES, 0, o.n);
    });
  }
  function startAvatar(cv) {
    var dpr = Math.min(2, window.devicePixelRatio || 1);
    if (dpr > 1) { cv.style.width = cv.width + 'px'; cv.style.height = cv.height + 'px'; cv.width = Math.round(cv.width * dpr); cv.height = Math.round(cv.height * dpr); }
    var R = mk(cv); if (!R) { cv.outerHTML = '<p>Your browser does not support WebGL.</p>'; return; }
    var st = { yaw: .5, pitch: .12, dist: 3.7, k: .3, c: [0, 2.6, 0] }, objs = [], drag = null;
    var mode = 'worn', eqs = JSON.parse(cv.getAttribute('data-eq') || '[]'), item = cv.getAttribute('data-item') ? JSON.parse(cv.getAttribute('data-item')) : null;
    cv.rbxEq = function (e) { eqs = e; cv.rbxMode(mode); };
    cv.rbxMode = function (m) {
      mode = m; objs = [];
      if (m === 'alone' && item && item.kind !== 'body') { st.c = [0, 0, 0]; st.k = 1; st.dist = 3.4; aloneObjs(R, item).then(function (o) { objs = o; }); }
      else { st.c = [0, 2.6, 0]; st.k = .3; st.dist = 3.7; avatar(R, m === 'alone' && item ? [item] : eqs).then(function (o) { objs = o; }); }
    };
    cv.rbxMode('worn');
    cv.onmousedown = function (e) { drag = [e.clientX, e.clientY]; };
    window.addEventListener('mouseup', function () { drag = null; });
    window.addEventListener('mousemove', function (e) { if (!drag) return; st.yaw += (e.clientX - drag[0]) * .01; st.pitch = Math.max(-1.4, Math.min(1.4, st.pitch + (e.clientY - drag[1]) * .01)); drag = [e.clientX, e.clientY]; });
    cv.onwheel = function (e) { e.preventDefault(); st.dist = Math.max(1.8, Math.min(9, st.dist + e.deltaY * .003)); };
    cv.ontouchstart = function (e) { drag = [e.touches[0].clientX, e.touches[0].clientY]; };
    cv.ontouchmove = function (e) { e.preventDefault(); var t = e.touches[0]; st.yaw += (t.clientX - drag[0]) * .01; drag = [t.clientX, t.clientY]; };
    cv.ontouchend = function () { drag = null; };
    (function loop() { if (!drag) st.yaw += .008; draw(R, objs, st, cv.width, cv.height); requestAnimationFrame(loop); })();
  }
  function thumbs(imgs) {   // renders every hat/tool preview with ONE shared WebGL canvas, then shows it as a picture
    imgs = [].slice.call(imgs); if (!imgs.length) return;
    var cv = document.createElement('canvas'); cv.width = cv.height = 240; var R = mk(cv); if (!R) return;
    var st = { yaw: .6, pitch: .25, dist: 3.4, k: 1, c: [0, 0, 0] };
    imgs.reduce(function (chain, img) {
      return chain.then(function () {
        return Promise.all([loadMesh(img.getAttribute('data-mesh')), img.getAttribute('data-tex') ? loadTex(R, img.getAttribute('data-tex')) : null]).then(function (r) {
          var o = mkObj(R, r[0], fit(r[0], 2, 0, 0, 0, false), null, r[1] ? 1 : 0, r[1]); if (img.getAttribute('data-flip') === '1') o.flip = 1;
          draw(R, [o], st, 240, 240); img.src = cv.toDataURL(); free(R, o);
        }).catch(function () {});
      });
    }, Promise.resolve());
  }
  function thumbBodies(imgs) {
    imgs = [].slice.call(imgs); if (!imgs.length) return;
    var cv = document.createElement('canvas'); cv.width = cv.height = 240; var R = mk(cv); if (!R) return;
    var st = { yaw: .5, pitch: .12, dist: 3.7, k: .3, c: [0, 2.6, 0] };
    imgs.reduce(function (chain, img) {
      return chain.then(function () {
        return avatar(R, JSON.parse(img.getAttribute('data-eq'))).then(function (o) { draw(R, o, st, 240, 240); img.src = cv.toDataURL(); o.forEach(function (x) { free(R, x); }); }).catch(function () {});
      });
    }, Promise.resolve());
  }
  function init() { thumbBodies(document.querySelectorAll('img.thb')); [].forEach.call(document.querySelectorAll('canvas.av'), startAvatar); thumbs(document.querySelectorAll('img.th')); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  return { avatar: startAvatar, thumbs: thumbs, core: { mk: mk, mkObj: mkObj, draw: draw, avatar: avatar, mul: mul, tr: tr, rx: rx, ry: ry, sc: sc, PC: PC, free: free } };
})();
