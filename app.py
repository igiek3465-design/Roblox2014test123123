import os, re, shutil, socket, sqlite3, secrets, datetime, mimetypes, urllib.request
from functools import wraps
from flask import Flask, g, render_template, render_template_string as rts, request, redirect, session, abort, Response, jsonify
from werkzeug.security import generate_password_hash as gph, check_password_hash as cph

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get('DATA_DIR') or os.path.join(os.path.expanduser('~'), '.roblox2014')   # outside the program folder: every new version finds the same accounts
os.makedirs(DATA, exist_ok=True)


def _adopt_old_data():
    """First start of a new version: copy accounts/forum/items from the newest older version folder that still has them."""
    if os.path.exists(os.path.join(DATA, 'rbx2014.db')) or os.environ.get('DATABASE_URL'): return
    cands = [os.path.join(BASE, 'data')]
    try: cands += [os.path.join(os.path.dirname(BASE), n, 'data') for n in os.listdir(os.path.dirname(BASE)) if n.lower().startswith('roblox2014')]
    except OSError: pass
    found = [c for c in cands if os.path.exists(os.path.join(c, 'rbx2014.db'))]
    if found:
        src = max(found, key=lambda c: os.path.getmtime(os.path.join(c, 'rbx2014.db')))
        for n in os.listdir(src):
            if os.path.isfile(os.path.join(src, n)): shutil.copy2(os.path.join(src, n), os.path.join(DATA, n))
        print('  Kept your old accounts and items from: ' + src)


_adopt_old_data()
PG = os.environ.get('DATABASE_URL')          # set this on Render/Neon/Supabase so accounts survive restarts
if PG:
    import psycopg2, psycopg2.extras
    INTEG = (psycopg2.IntegrityError,)
else:
    INTEG = (sqlite3.IntegrityError,)
PK, BL = ('serial primary key', 'bytea') if PG else ('integer primary key', 'blob')
ADMINS = [a.strip() for a in os.environ.get('ADMINS', 'igorkon15,ROBLOX').split(',') if a.strip()]
KINDS = {'hat': 'Hats', 'face': 'Faces', 'shirt': 'Shirts', 'pants': 'Pants', 'tshirt': 'T-Shirts', 'tool': 'Tools', 'body': 'Bodies'}
KIND1 = {'hat': 'Hat', 'face': 'Face', 'shirt': 'Shirt', 'pants': 'Pants', 'tshirt': 'T-Shirt', 'tool': 'Tool', 'body': 'R6 body'}
GENRES = ['building', 'horror', 'town-and-city', 'military', 'comedy', 'medieval', 'adventure', 'sci-fi', 'naval', 'fps', 'rpg', 'sports', 'fighting', 'western']
EXT = {'mesh': {'.obj', '.mesh'}, 'tex': {'.png', '.jpg', '.jpeg'}, 'game': {'.rbxl', '.rbxlx', '.zip', '.html'}}
INFO = {'privacy': ('Privacy Policy', 'This server stores your username, a hashed password and your birthday. Nothing is sent to any third party.'),
        'terms': ('Terms of Service', 'Be kind, do not share passwords, and have fun building. The owner may remove accounts or items that break these rules.'),
        'advertise': ('Advertise with Us', 'There are no ads on this server.'), 'press': ('Press', 'This is a private fan-made server.'),
        'contact': ('Contact Us', 'Ask the person who runs this server.'), 'about': ('About Us', 'A private ROBLOX 2014-style community. Build, play and make friends.'),
        'jobs': ('Jobs', 'No open positions right now.'), 'parents': ('Parents', 'Accounts need a birthday. Only a username, password hash and birthday are stored.')}
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

app = Flask(__name__)
app.config.update(SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=60 * 1024 * 1024, PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=30))
_kf = os.path.join(DATA, 'secret.key')
if not os.environ.get('SECRET_KEY') and not os.path.exists(_kf):
    open(_kf, 'w').write(secrets.token_hex(32))
app.secret_key = os.environ.get('SECRET_KEY') or open(_kf).read().strip()



class _FixPath:
    def __init__(s, app): s.app = app
    def __call__(s, env, start):
        p = env.get('PATH_INFO', '')
        if p.startswith('/www.civdefn.tk'): p = p[len('/www.civdefn.tk'):]
        env['PATH_INFO'] = '/' + p.lstrip('/')
        return s.app(env, start)


app.wsgi_app = _FixPath(app.wsgi_app)


class DB:
    def __init__(s):
        if PG:
            s.c = psycopg2.connect(PG.replace('postgres://', 'postgresql://', 1))
        else:
            s.c = sqlite3.connect(os.path.join(DATA, 'rbx2014.db')); s.c.row_factory = sqlite3.Row

    def x(s, sql, a=()):
        if PG:
            cur = s.c.cursor(cursor_factory=psycopg2.extras.RealDictCursor); cur.execute(sql.replace('?', '%s'), a); return cur
        return s.c.execute(sql, a)

    def one(s, sql, a=()): return s.x(sql, a).fetchone()
    def all(s, sql, a=()): return s.x(sql, a).fetchall()

    def ins(s, sql, a):
        if PG: return s.x(sql + ' returning id', a).fetchone()['id']
        return s.x(sql, a).lastrowid

    def commit(s): s.c.commit()


def db():
    if 'db' not in g: g.db = DB()
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop('db', None)
    if d:
        try: d.c.rollback()
        finally: d.c.close()


def today(): return datetime.date.today().isoformat()
def B(d): return psycopg2.Binary(d) if PG else d


def init():
    d = DB()
    for s in [f"create table if not exists users(id {PK}, username text, pw text, birthday text, joined text, robux integer default 100, blurb text default '', banned integer default 0, admin integer default 0)",
              'create unique index if not exists u_lower on users(lower(username))',
              f'create table if not exists items(id {PK}, uid integer, name text, kind text, price integer, mesh text, tex text, official integer default 0, created text)',
              f'create table if not exists blobs(name text primary key, ctype text, data {BL})',
              'create table if not exists owned(uid integer, iid integer, primary key(uid, iid))',
              'create table if not exists equipped(uid integer, iid integer, primary key(uid, iid))',
              f'create table if not exists games(id {PK}, uid integer, title text, descr text, file text, thumb text, genre text, created text)',
              f'create table if not exists posts(id {PK}, uid integer, subject text, body text, created text)',
              'create table if not exists listings(id %s, iid integer, uid integer, price integer, created text, unique(iid, uid))' % PK,
              f'create table if not exists trades(id {PK}, frm integer, tou integer, gives text, takes text, grobux integer, trobux integer, status text, created text)',
              'create table if not exists bodyparts(iid integer, part integer, mesh text, tex text)',
              'create table if not exists settings(k text primary key, v text)']:
        d.x(s)
    d.commit()
    for col in ('srcid text', 'stock integer default 0', 'sold integer default 0', 'pub integer default 1', 'limited integer default 0', 'flipv integer default 0', 'ox real default 0', 'oy real default 0', 'oz real default 0', 'rot real default 0', 'scl real default 1'):
        try: d.x('alter table items add column ' + col); d.commit()
        except Exception: d.c.rollback()
    for stmt in ('alter table owned add column serial integer', 'alter table games add column visits integer default 0'):
        try: d.x(stmt); d.commit()
        except Exception: d.c.rollback()
    pw = os.environ.get('ADMIN_PASSWORD') or 'igorkon15'     # default admin password (set ADMIN_PASSWORD to change it)
    for n in ADMINS:
        u = d.one('select * from users where lower(username)=lower(?)', (n,))
        try:
            if not u:
                p = pw or secrets.token_urlsafe(8)
                d.x('insert into users(username,pw,birthday,joined,robux,admin) values(?,?,?,?,?,1)', (n, gph(p), '2000-01-01', today(), 1000000))
                if not pw: print('  Created admin account "%s" with password: %s   (set ADMIN_PASSWORD to choose your own)' % (n, p))
            elif pw: d.x('update users set pw=?, admin=1 where id=?', (gph(pw), u['id']))
            else: d.x('update users set admin=1 where id=?', (u['id'],))
            d.commit()
        except INTEG:
            d.c.rollback()
    d.c.close()


init()


def cur_user():
    if 'u' not in g:
        u = db().one('select * from users where id=?', (session['uid'],)) if 'uid' in session else None
        if u and u['banned']: session.clear(); u = None
        g.u = u
    return g.u


def setting(k, default=''):
    r = db().one('select v from settings where k=?', (k,))
    return r['v'] if r else default


def set_setting(k, v):
    db().x('delete from settings where k=?', (k,)); db().x('insert into settings(k,v) values(?,?)', (k, v)); db().commit()


@app.context_processor
def inject():
    return {'user': cur_user(), 'announcement': setting('announcement')}


MACROS = '''{% macro th(i) %}{% if i.mesh %}<img class="th" width="120" height="120" data-mesh="/files/{{ i.mesh }}" data-tex="{{ '/files/' + i.tex if i.tex else '' }}" data-flip="{{ 1 if i.flipv else 0 }}" alt="">{% elif i.kind == 'body' and i.eq %}<img class="thb" width="120" height="120" data-eq='{{ i.eq|tojson }}' alt="">{% elif i.tex %}<img width="120" height="120" style="object-fit:contain;background:#cfd8e6" src="/files/{{ i.tex }}" alt="">{% else %}<div style="width:120px;height:120px;margin:0 auto 8px;background:#cfd8e6"></div>{% endif %}{% endmacro %}
{% macro price(i) %}{{ 'R$ %d' % i.price if i.price else 'Free' }}{% endmacro %}
{% macro lim(i) %}{% if i.limited == 2 %}<span class="lim limu">Limited U</span> {% elif i.limited %}<span class="lim">Limited</span> {% endif %}{% endmacro %}
{% macro status(i) %}{{ lim(i) }}{% if i.stock and i.sold >= i.stock %}<b>Sold out</b>{% if i.best %}<br>Resale from R$ {{ i.best }}{% endif %}{% else %}<b>{{ price(i) }}</b>{% if i.stock %}<br>{{ i.stock - i.sold }} left{% endif %}{% endif %}{% endmacro %}'''


def page(title, tpl, **kw):
    return render_template('page.html', title=title, content=rts(MACROS + tpl, **kw))


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not cur_user(): return redirect('/newlogin?next=' + request.path)
        return f(*a, **k)
    return w


def admin_required(f):
    @wraps(f)
    @login_required
    def w(*a, **k):
        if not cur_user()['admin']: abort(403)
        return f(*a, **k)
    return w


def safe_next(n): return n if n and n.startswith('/') and not n.startswith('//') else '/home'


# ---------- files stored in the database (so they survive restarts too) ----------
def put(data, ext, name=None):
    name = name or secrets.token_hex(8) + ext
    db().x('insert into blobs(name,ctype,data) values(?,?,?)', (name, mimetypes.guess_type('x' + ext)[0] or 'application/octet-stream', B(data)))
    return name


def save_upload(f, kind):
    if not f or not f.filename: return None
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in EXT[kind]: raise ValueError('Unsupported file type: ' + (ext or 'none'))
    return put(f.read(), ext)


def fetch_asset(raw, kind, depth=0):
    """Download a public Roblox asset by ID on the server and keep a copy in our own database."""
    if not raw.strip().isdigit(): raise ValueError('IDs must be numbers.')
    aid = int(raw)
    for e in ('.mesh', '.png', '.jpg'):
        if db().one('select 1 as x from blobs where name=?', ('rbx_%d%s' % (aid, e),)): return 'rbx_%d%s' % (aid, e)
    req = urllib.request.Request('https://assetdelivery.roblox.com/v1/asset/?id=%d' % aid, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r: data = r.read(30 * 1024 * 1024)
    ext = '.mesh' if data[:8] == b'version ' else '.png' if data[:4] == b'\x89PNG' else '.jpg' if data[:2] == b'\xff\xd8' else None
    if ext is None and depth == 0:
        m = re.search(rb'(?:id=|rbxassetid://)(\d+)', data)
        if m: return fetch_asset(m.group(1).decode(), kind, 1)
    if ext is None or (kind == 'mesh') != (ext == '.mesh'):
        raise ValueError('Asset %d is not a %s.' % (aid, 'mesh' if kind == 'mesh' else 'texture image'))
    return put(data, ext, 'rbx_%d%s' % (aid, ext))


@app.route('/files/<name>')
def files(name):
    r = db().one('select ctype, data from blobs where name=?', (name,)) or abort(404)
    resp = Response(bytes(r['data']), mimetype=r['ctype'])
    resp.headers['Content-Security-Policy'] = 'sandbox allow-scripts'
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


# ---------- accounts ----------
@app.route('/')
def index(): return redirect('/home' if cur_user() else '/newlogin')


@app.route('/newlogin', methods=['GET', 'POST'])
@app.route('/Login/NewLogin.aspx', methods=['GET', 'POST'])
def newlogin():
    nxt = request.values.get('next') or request.values.get('ReturnUrl') or ''
    if request.method == 'POST':
        name = request.form.get('Username', '').strip()
        u = db().one('select * from users where lower(username)=lower(?)', (name,))
        if u and u['banned']:
            return render_template('newlogin.html', error='This account has been banned.', username=name, next=nxt)
        if u and cph(u['pw'], request.form.get('Password', '')):
            session.clear(); session.permanent = True; session['uid'] = u['id']
            return redirect(safe_next(nxt))
        return render_template('newlogin.html', error='Incorrect username or password.', username=name, next=nxt)
    if cur_user(): return redirect(safe_next(nxt))
    return render_template('newlogin.html', next=nxt)


SIGNUP = '''{% if err %}<div class="err">{{ err }}</div>{% endif %}
<form method="post" action="/Login/NewAge.aspx"><div class="box" style="width:360px">
<label>Username (3-20 letters, numbers or _)</label><input class="text-box" name="username" value="{{ f.get('username','') }}">
<label>Password (6+ characters)</label><input class="text-box" type="password" name="password">
<label>Confirm password</label><input class="text-box" type="password" name="password2">
<label>Birthday</label>
<select class="form-select" name="Month" style="width:100px"><option value="">Month</option>{% for i, m in months %}<option value="{{ i }}" {{ 'selected' if f.get('Month') == i|string }}>{{ m }}</option>{% endfor %}</select>
<select class="form-select" name="Day" style="width:55px"><option value="">Day</option>{% for d in range(1, 32) %}<option {{ 'selected' if f.get('Day') == d|string }}>{{ d }}</option>{% endfor %}</select>
<select class="form-select" name="Year" style="width:65px"><option value="">Year</option>{% for y in range(year, 1899, -1) %}<option {{ 'selected' if f.get('Year') == y|string }}>{{ y }}</option>{% endfor %}</select>
<button class="btn-medium btn-primary" type="submit">Sign Up</button></div></form>'''


@app.route('/Login/NewAge.aspx', methods=['GET', 'POST'])
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    f, err = request.values, None
    if request.method == 'POST':
        n, p = f.get('username', '').strip(), f.get('password', '')
        try: bd = datetime.date(int(f['Year']), int(f['Month']), int(f['Day']))
        except (KeyError, ValueError): bd = None
        if not re.fullmatch(r'[A-Za-z0-9_]{3,20}', n): err = 'Username must be 3-20 letters, numbers or underscores.'
        elif n.lower() in [a.lower() for a in ADMINS]: err = 'That username is reserved.'
        elif len(p) < 6: err = 'Password must be at least 6 characters.'
        elif p != f.get('password2'): err = 'Passwords do not match.'
        elif not bd or bd > datetime.date.today(): err = 'Please select a valid birthday.'
        else:
            try:
                uid = db().ins('insert into users(username,pw,birthday,joined) values(?,?,?,?)', (n, gph(p), bd.isoformat(), today()))
                db().commit()
                session.clear(); session.permanent = True; session['uid'] = uid
                return redirect('/home')
            except INTEG:
                db().c.rollback(); err = 'That username is already taken.'
    return page('Sign Up', SIGNUP, f=f, err=err, months=list(enumerate(MONTHS, 1)), year=datetime.date.today().year)


@app.route('/logout')
def logout():
    session.clear(); return redirect('/newlogin')


def body_parts(iid):
    return [dict(p=r['part'], mesh=r['mesh'], tex=r['tex']) for r in db().all('select part, mesh, tex from bodyparts where iid=? order by part', (iid,))]


def with_eq(rows):
    out = []
    for r in rows:
        r = dict(r)
        if r.get('kind') == 'body': r['eq'] = [dict(kind='body', parts=body_parts(r['id']))]
        out.append(r)
    return out


def eq_list(uid):
    out = []
    for r in db().all('select i.id, i.kind, i.mesh, i.tex, i.ox, i.oy, i.oz, i.rot, i.scl, i.flipv from equipped e join items i on i.id=e.iid where e.uid=?', (uid,)):
        e = dict(kind=r['kind'], mesh=r['mesh'], tex=r['tex'], off=dict(x=r['ox'] or 0, y=r['oy'] or 0, z=r['oz'] or 0, r=r['rot'] or 0, s=r['scl'] or 1, f=r['flipv'] or 0))
        if r['kind'] == 'body': e['parts'] = body_parts(r['id'])
        out.append(e)
    return out


AVATAR = '''<canvas class="av" width="{{ w }}" height="{{ w }}" data-eq='{{ eq|tojson }}' {% if item %}data-item='{{ item|tojson }}'{% endif %} style="display:block;background:#e1e1e1;border:1px solid #bcbcbc"></canvas>'''


@app.route('/home')
@login_required
def home():
    u = cur_user()
    inv = with_eq(db().all('select i.*, o.serial, (e.iid is not null) as worn from owned o join items i on i.id=o.iid left join equipped e on e.uid=o.uid and e.iid=o.iid where o.uid=? order by i.id desc', (u['id'],)))
    return page('Home', '''<div style="display:flex;gap:28px;align-items:flex-start"><div>''' + AVATAR + '''<p style="margin-top:8px"><b>R$ {{ user.robux }}</b> Robux &nbsp;|&nbsp; <a href="/settings">Settings</a>{% if user.admin %} &nbsp;|&nbsp; <a href="/admin">Admin</a>{% endif %}</p></div>
<div style="flex:1"><h2>Hello, {{ user.username }}!</h2><p>Your inventory. Equip items to wear them on your character.</p>
<div class="grid">{% for i in inv %}<div class="card">{{ th(i) }}<br>{{ lim(i) }}<a href="/item/{{ i.id }}">{{ i.name }}</a>{% if i.serial %}<br>#{{ i.serial }} of {{ i.stock }}{% endif %}<br>
<form method="post" action="/{{ 'unequip' if i.worn else 'equip' }}/{{ i.id }}"><button class="btn-small btn-neutral" style="border:0">{{ 'Take off' if i.worn else 'Wear' }}</button></form></div>
{% else %}<p>Nothing yet. Visit the <a href="/catalog">catalog</a> or <a href="/item/new">upload an item</a>.</p>{% endfor %}</div>
<p><a href="/item/new">+ Upload item</a> &nbsp; <a href="/game/new">+ Upload game</a> &nbsp; <a href="/trades">Trades</a></p></div></div>''', eq=eq_list(u['id']), w=400, inv=inv)


@app.route('/equip/<int:iid>', methods=['POST'])
@login_required
def equip(iid):
    u, d = cur_user(), db()
    it = d.one('select i.* from items i join owned o on o.iid=i.id where i.id=? and o.uid=?', (iid, u['id'])) or abort(404)
    d.x('delete from equipped where uid=? and iid in (select id from items where kind=?)', (u['id'], it['kind']))
    d.x('insert into equipped(uid,iid) values(?,?)', (u['id'], iid)); d.commit()
    return redirect(request.referrer or '/home')


@app.route('/unequip/<int:iid>', methods=['POST'])
@login_required
def unequip(iid):
    db().x('delete from equipped where uid=? and iid=?', (cur_user()['id'], iid)); db().commit()
    return redirect(request.referrer or '/home')


# ---------- catalog, items, Robux ----------
ITEM_FORM = '''{% if err %}<div class="err" style="white-space:pre-wrap">{{ err }}</div>{% endif %}
<form method="post" enctype="multipart/form-data"><div class="box" style="width:440px">
<label>Type</label><select class="form-select" name="kind" style="width:200px"><option value="">Auto-detect (Roblox ID)</option>{% for k, v in kinds.items() %}<option value="{{ k }}">{{ v }}</option>{% endfor %}</select>
<label>Name</label><input class="text-box" name="name" maxlength="60">
<label>Price in Robux (0 = free)</label><input class="text-box" name="price" value="0" style="width:120px">
<label>Copies (how many can be bought from you, 0 = unlimited)</label><input class="text-box" name="stock" value="0" style="width:120px">
<label>Sale type</label><select class="form-select" name="limited" style="width:300px"><option value="0">Normal</option><option value="1">Limited (owners can resell)</option><option value="2">Limited U (numbered copies, owners can resell)</option></select>
<p style="margin-top:14px"><b>Roblox item ID</b> (the number from the catalog / develop page: hats, tools, faces, shirts, pants, T-shirts, <b>R6 bodies / packages</b>, meshes)</p>
<input class="text-box" name="rid">
<p style="margin-top:14px"><b>Or</b> enter the parts yourself</p>
<label>Mesh ID</label><input class="text-box" name="mesh_id"><label>Texture / image ID</label><input class="text-box" name="tex_id">
<p style="margin-top:14px"><b>Or upload files</b> (.obj / .mesh model, .png / .jpg image)</p>
<label>Model (hats, tools)</label><input type="file" name="mesh"><label>Image (texture, face, shirt)</label><input type="file" name="tex">
{% if user.admin %}<label><input type="checkbox" name="official"> Official item (made by ROBLOX)</label>{% endif %}
<p style="margin-top:12px">Each Roblox ID can only be added once. Hats and tools open a position editor next.</p>
<button class="btn-medium btn-neutral" type="submit">Continue</button></div></form>'''


@app.route('/item/new', methods=['GET', 'POST'])
@login_required
def item_new():
    err, u = None, cur_user()
    if request.method == 'POST':
        f, d = request.form, db()
        try:
            kind = f.get('kind') or ''
            if kind and kind not in KINDS: raise ValueError('Choose an item type.')
            try: price, stock, limited = max(0, int(f.get('price') or 0)), max(0, int(f.get('stock') or 0)), min(2, max(0, int(f.get('limited') or 0)))
            except ValueError: raise ValueError('Price and copies must be numbers.')
            if limited == 2 and not stock: raise ValueError('Limited U items are numbered, so set how many copies exist.')
            mesh = tex = srcid = parts = None
            rid, mid, tid = f.get('rid', '').strip(), f.get('mesh_id', '').strip(), f.get('tex_id', '').strip()
            srcid = rid or ('m%s' % mid if mid else ('t%s' % tid if tid else None))
            if srcid:
                dup = d.one('select id, name from items where srcid=?', (srcid,))
                if dup: raise ValueError('That Roblox ID was already added as "%s" (item #%d). Each ID can only exist once.' % (dup['name'], dup['id']))
            if rid:
                res = import_roblox(rid, kind); kind, mesh, tex, parts = res['kind'], res['mesh'], res['tex'], res.get('parts')
            else:
                if not kind: raise ValueError('Choose an item type.')
                if kind == 'body': raise ValueError('R6 bodies are added with a Roblox ID (the package or body-part id).')
                if kind in ('hat', 'tool'):
                    if mid:
                        if not mid.isdigit(): raise ValueError('IDs must be numbers.')
                        mesh = store_mesh(get_raw(int(mid)), kind)
                    elif request.files.get('mesh') and request.files['mesh'].filename:
                        fl = request.files['mesh']
                        if os.path.splitext(fl.filename)[1].lower() not in EXT['mesh']: raise ValueError('Models must be .obj or .mesh files.')
                        mesh = store_mesh(fl.read(), kind)
                    else: raise ValueError('Hats and tools need a Roblox ID, a mesh ID or a .obj / .mesh file.')
                if tid:
                    if not tid.isdigit(): raise ValueError('IDs must be numbers.')
                    tex = store_image(tid)
                else: tex = save_upload(request.files.get('tex'), 'tex')
                if kind not in ('hat', 'tool') and not tex: raise ValueError('Faces and shirts need an image or a texture ID.')
            pub = 0 if kind in ('hat', 'tool') else 1
            iid = d.ins('insert into items(uid,name,kind,price,mesh,tex,official,created,srcid,stock,sold,pub,limited) values(?,?,?,?,?,?,?,?,?,?,0,?,?)',
                        (u['id'], (f.get('name') or 'Item %s' % (rid or iid_hint())).strip()[:60], kind, price, mesh, tex, 1 if u['admin'] and f.get('official') else 0, today(), srcid, stock, pub, limited))
            for p in (parts or []): d.x('insert into bodyparts(iid,part,mesh,tex) values(?,?,?,?)', (iid, p['part'], p['mesh'], p['tex']))
            d.x('insert into owned(uid,iid) values(?,?)', (u['id'], iid)); d.commit()
            return redirect('/item/%d/edit' % iid if not pub else '/item/%d' % iid)
        except ValueError as e:
            db().c.rollback(); err = str(e)
        except INTEG:
            db().c.rollback(); err = 'That Roblox ID was just added by someone else.'
        except Exception as ex:
            db().c.rollback(); err = 'Import failed (%s): %s' % (ex.__class__.__name__, ex)
    return page('Upload Item', ITEM_FORM, err=err, kinds=KINDS)


def iid_hint(): return secrets.token_hex(2)


def _off(r): return dict(x=r['ox'] or 0, y=r['oy'] or 0, z=r['oz'] or 0, r=r['rot'] or 0, s=r['scl'] or 1, f=r['flipv'] or 0)


@app.route('/catalog')
def catalog():
    k = request.args.get('kind')
    rows = with_eq(db().all('select i.*, u.username, (select min(price) from listings l where l.iid=i.id) as best from items i join users u on u.id=i.uid where i.pub=1 '
                    + ('and i.kind=? ' if k in KINDS else '') + 'order by i.id desc limit 200', (k,) if k in KINDS else ()))
    return page('Catalog', '''<p><a href="/catalog">All</a>{% for a, b in kinds.items() %} &nbsp;|&nbsp; <a href="/catalog?kind={{ a }}">{{ b }}</a>{% endfor %}{% if user %} &nbsp;&nbsp; <b><a href="/item/new">+ Upload an item</a></b>{% endif %}</p>
<div class="grid">{% for i in rows %}<div class="card">{{ th(i) }}<br><a href="/item/{{ i.id }}">{{ i.name }}</a><br>{{ 'ROBLOX' if i.official else i.username }}<br>{{ status(i) }}</div>
{% else %}<p>The catalog is empty. Be the first to upload an item!</p>{% endfor %}</div>''', rows=rows, kinds=KINDS)


@app.route('/item/<int:iid>')
def item_view(iid):
    d, u = db(), cur_user()
    it = d.one('select i.*, u.username from items i join users u on u.id=i.uid where i.id=?', (iid,)) or abort(404)
    can_edit = bool(u and (u['admin'] or u['id'] == it['uid']))
    if not it['pub'] and not can_edit: abort(404)
    eq = [e for e in (eq_list(u['id']) if u else []) if e['kind'] != it['kind']] + [dict(kind=it['kind'], mesh=it['mesh'], tex=it['tex'], off=_off(it), parts=body_parts(iid) if it['kind'] == 'body' else None)]
    lst = d.all('select l.id, l.price, l.uid, u.username from listings l join users u on u.id=l.uid where l.iid=? order by l.price, l.id', (iid,))
    mylist = next((l for l in lst if u and l['uid'] == u['id']), None)
    owned = bool(u and d.one('select 1 as x from owned where uid=? and iid=?', (u['id'], iid)))
    worn = bool(u and d.one('select 1 as x from equipped where uid=? and iid=?', (u['id'], iid)))
    soldout = bool(it['stock'] and it['sold'] >= it['stock'])
    ow = d.one('select serial from owned where uid=? and iid=?', (u['id'], iid)) if u else None
    serial = ow['serial'] if ow else None
    return page(it['name'], '<div style="display:flex;gap:28px;align-items:flex-start"><div>' + AVATAR + '''<p style="margin-top:6px">Drag to rotate, scroll to zoom</p>
<p><button type="button" class="btn-small btn-neutral" onclick="document.querySelector('canvas.av').rbxMode('worn')">On my character</button> <button type="button" class="btn-small btn-neutral" onclick="document.querySelector('canvas.av').rbxMode('alone')">Item only</button></p></div>
<div class="box" style="width:300px"><p>{{ lim(it) }}{{ kind1[it.kind] }} &middot; by {{ 'ROBLOX' if it.official else it.username }}</p><p>Price: <b>{{ price(it) }}</b></p>
{% if it.stock %}<p>{% if soldout %}<b>Sold out</b>{% if lst %} &middot; cheapest resale <b>R$ {{ lst[0].price }}</b>{% endif %}{% else %}{{ it.stock - it.sold }} of {{ it.stock }} copies left{% endif %}</p>{% endif %}
{% if not it.pub %}<p class="err">Not published yet. Save its position to publish it.</p>{% endif %}
{% if not user %}<p><a href="/newlogin?next=/item/{{ it.id }}">Log in</a> to buy this.</p>
{% elif owned %}<p>You own this.{% if serial %} <b>#{{ serial }} of {{ it.stock }}</b>{% endif %}</p><form method="post" action="/{{ 'unequip' if worn else 'equip' }}/{{ it.id }}"><button class="btn-medium btn-neutral" style="width:120px">{{ 'Take off' if worn else 'Wear' }}</button></form>
{% elif soldout %}<p>All copies are taken. Buy from a reseller below.</p>
{% else %}<form method="post" action="/buy/{{ it.id }}"><button class="btn-medium btn-primary" style="width:120px">Buy</button></form>{% endif %}
{% if err %}<div class="err" style="margin-top:10px">{{ err }}</div>{% endif %}
{% if can_edit and it.kind in ('hat', 'tool') %}<p style="margin-top:12px"><a href="/item/{{ it.id }}/edit">Edit position</a></p>{% endif %}
{% if can_edit %}<form method="post" action="/item/{{ it.id }}/delete" style="margin-top:14px"><button class="btn-small" style="background:#a00;border:0">Delete</button></form>{% endif %}</div></div>
{% if it.limited or lst %}<h2 style="margin-top:22px">Resellers</h2>
<table style="width:560px"><tr><th>Seller</th><th>Price</th><th></th></tr>
{% for l in lst %}<tr><td><a href="/user/{{ l.username }}">{{ l.username }}</a></td><td>R$ {{ l.price }}</td><td>
{% if user and l.uid == user.id %}<form method="post" action="/unsell/{{ it.id }}"><button class="btn-small" style="background:#a00">Take off sale</button></form>
{% elif user and not owned %}<form method="post" action="/buy/{{ it.id }}/from/{{ l.id }}"><button class="btn-small btn-primary">Buy</button></form>{% endif %}</td></tr>
{% else %}<tr><td colspan="3">No one is reselling this yet.</td></tr>{% endfor %}</table>
{% if owned and not mylist and it.limited %}<form method="post" action="/sell/{{ it.id }}"><div class="box" style="width:300px"><label>Sell your copy for (Robux)</label><input class="text-box" name="price" style="width:120px"><button class="btn-medium btn-neutral" style="width:120px">Put on sale</button></div></form>{% endif %}{% endif %}''',
                it=it, eq=eq, w=420, lst=lst, mylist=mylist, item=dict(kind=it['kind'], mesh=it['mesh'], tex=it['tex'], off=_off(it), parts=body_parts(iid) if it['kind'] == 'body' else None), owned=owned, worn=worn, kinds=KINDS, kind1=KIND1,
                err=request.args.get('err'), can_edit=can_edit, soldout=soldout, serial=serial)


EDITOR = '<div style="display:flex;gap:28px;align-items:flex-start"><div>' + AVATAR + '''<p style="margin-top:6px">Drag the picture to look around. Move the item with the buttons or the keyboard.</p></div>
<div class="box" style="width:340px"><p><b>Position "{{ it.name }}"</b></p>
<table id="pad" style="width:auto"><tr><td></td><td><button type="button" data-k="oy" data-d="1">&#9650; Up</button></td><td><button type="button" data-k="oz" data-d="1">Forward</button></td></tr>
<tr><td><button type="button" data-k="ox" data-d="-1">&#9664; Left</button></td><td><button type="button" data-k="oy" data-d="-1">&#9660; Down</button></td><td><button type="button" data-k="ox" data-d="1">Right &#9654;</button></td></tr>
<tr><td><button type="button" data-k="rot" data-d="-1">&#8630; Turn</button></td><td><button type="button" data-k="oz" data-d="-1">Back</button></td><td><button type="button" data-k="rot" data-d="1">Turn &#8631;</button></td></tr>
<tr><td><button type="button" data-k="scl" data-d="-1">Smaller</button></td><td><button type="button" id="flipbtn">Flip texture</button></td><td><button type="button" data-k="scl" data-d="1">Bigger</button></td></tr></table>
<p>Step <select id="step"><option>0.02</option><option selected>0.05</option><option>0.1</option><option>0.25</option></select> &nbsp; Keys: arrows, W/S forward/back, Q/E turn</p>
<form method="post" action="/item/{{ it.id }}/place">
<input type="hidden" id="flipv" name="flipv"><input type="hidden" id="ox" name="ox"><input type="hidden" id="oy" name="oy"><input type="hidden" id="oz" name="oz"><input type="hidden" id="rot" name="rot"><input type="hidden" id="scl" name="scl">
<button class="btn-medium btn-primary" style="width:200px">Save and publish</button></form></div></div>
<script>
(function () {
  var cv = document.querySelector('canvas.av'), eq = JSON.parse(cv.getAttribute('data-eq')), o = eq[eq.length - 1].off, M = {ox: 'x', oy: 'y', oz: 'z', rot: 'r', scl: 's'};
  function show() { for (var k in M) document.getElementById(k).value = o[M[k]].toFixed(3); document.getElementById('flipv').value = o.f ? 1 : 0; if (cv.rbxEq) cv.rbxEq(eq); }
  document.getElementById('flipbtn').onclick = function () { o.f = o.f ? 0 : 1; show(); };
  function move(k, d) {
    var m = parseFloat(document.getElementById('step').value);
    if (k === 'rot') o.r += d * 15; else if (k === 'scl') o.s = Math.max(.3, Math.min(3, o.s + d * .1)); else o[M[k]] = Math.max(-4, Math.min(4, o[M[k]] + d * m));
    show();
  }
  [].forEach.call(document.querySelectorAll('#pad button'), function (b) { b.onclick = function () { move(b.getAttribute('data-k'), parseFloat(b.getAttribute('data-d'))); }; });
  document.addEventListener('keydown', function (e) {
    var t = {ArrowLeft: ['ox', -1], ArrowRight: ['ox', 1], ArrowUp: ['oy', 1], ArrowDown: ['oy', -1], w: ['oz', 1], s: ['oz', -1], q: ['rot', -1], e: ['rot', 1]}[e.key];
    if (t && e.target.tagName !== 'SELECT') { e.preventDefault(); move(t[0], t[1]); }
  });
  for (var k in M) document.getElementById(k).value = o[M[k]]; document.getElementById('flipv').value = o.f ? 1 : 0;
})();
</script>'''


@app.route('/item/<int:iid>/edit')
@login_required
def item_edit(iid):
    u, d = cur_user(), db()
    it = d.one('select * from items where id=?', (iid,)) or abort(404)
    if not (u['admin'] or u['id'] == it['uid']) or it['kind'] not in ('hat', 'tool'): abort(403)
    eq = [e for e in eq_list(u['id']) if e['kind'] != it['kind']] + [dict(kind=it['kind'], mesh=it['mesh'], tex=it['tex'], off=_off(it))]
    return page('Position: ' + it['name'], EDITOR, it=it, eq=eq, w=420, item=None)


@app.route('/item/<int:iid>/place', methods=['POST'])
@login_required
def item_place(iid):
    u, d = cur_user(), db()
    it = d.one('select * from items where id=?', (iid,)) or abort(404)
    if not (u['admin'] or u['id'] == it['uid']): abort(403)
    def num(k, lo, hi, dflt):
        try: return max(lo, min(hi, float(request.form.get(k, dflt))))
        except ValueError: return dflt
    d.x('update items set ox=?, oy=?, oz=?, rot=?, scl=?, flipv=?, pub=1 where id=?', (num('ox', -4, 4, 0), num('oy', -4, 4, 0), num('oz', -4, 4, 0), num('rot', -3600, 3600, 0), num('scl', .3, 3, 1), 1 if request.form.get('flipv') == '1' else 0, iid)); d.commit()
    return redirect('/item/%d' % iid)


@app.route('/buy/<int:iid>', methods=['POST'])
@login_required
def buy(iid):
    d, u = db(), cur_user()
    it = d.one('select * from items where id=?', (iid,)) or abort(404)
    if not it['pub']: abort(404)
    if d.one('select 1 as x from owned where uid=? and iid=?', (u['id'], iid)): return redirect('/item/%d' % iid)
    if it['stock'] and d.x('update items set sold=sold+1 where id=? and sold<stock', (iid,)).rowcount != 1:
        d.c.rollback(); return redirect('/item/%d?err=Sold+out.+Buy+from+a+reseller+below.' % iid)
    if it['price'] and d.x('update users set robux=robux-? where id=? and robux>=?', (it['price'], u['id'], it['price'])).rowcount != 1:
        d.c.rollback(); return redirect('/item/%d?err=Not+enough+Robux.' % iid)
    if it['price'] and not it['official'] and it['uid'] != u['id']:
        d.x('update users set robux=robux+? where id=?', (it['price'], it['uid']))
    serial = d.one('select sold from items where id=?', (iid,))['sold'] if it['limited'] == 2 else None
    d.x('insert into owned(uid,iid,serial) values(?,?,?)', (u['id'], iid, serial)); d.commit()
    return redirect('/item/%d' % iid)


# ---------- trading ----------
def _ids(s): return [int(x) for x in (s or '').split(',') if x.strip().isdigit()]
OWNED_Q = 'select i.id, i.name from owned o join items i on i.id=o.iid where o.uid=? order by i.id'


@app.route('/trade/<name>', methods=['GET', 'POST'])
@login_required
def trade_new(name):
    d, u = db(), cur_user()
    t = d.one('select * from users where lower(username)=lower(?)', (name,)) or abort(404)
    if t['id'] == u['id']: abort(404)
    mine, theirs, err = d.all(OWNED_Q, (u['id'],)), d.all(OWNED_Q, (t['id'],)), None
    if request.method == 'POST':
        give = [int(x) for x in request.form.getlist('give') if x.isdigit()]; take = [int(x) for x in request.form.getlist('take') if x.isdigit()]
        try: gr, tr_ = max(0, int(request.form.get('grobux') or 0)), max(0, int(request.form.get('trobux') or 0))
        except ValueError: gr = tr_ = -1
        if gr < 0: err = 'Robux must be numbers.'
        elif not (set(give) <= {r['id'] for r in mine} and set(take) <= {r['id'] for r in theirs}): err = 'Pick items that you and they own.'
        elif not (give or take or gr or tr_): err = 'Offer something first.'
        else:
            d.x('insert into trades(frm,tou,gives,takes,grobux,trobux,status,created) values(?,?,?,?,?,?,?,?)',
                (u['id'], t['id'], ','.join(map(str, give)), ','.join(map(str, take)), gr, tr_, 'pending', today())); d.commit()
            return redirect('/trades')
    return page('Trade with ' + t['username'], '''{% if err %}<div class="err">{{ err }}</div>{% endif %}
<form method="post"><div style="display:flex;gap:28px"><div class="box" style="width:300px"><b>You give</b>{% for r in mine %}<label><input type="checkbox" name="give" value="{{ r.id }}"> {{ r.name }}</label>{% else %}<p>You own nothing yet.</p>{% endfor %}
<label>+ Robux you add</label><input class="text-box" name="grobux" value="0" style="width:120px"></div>
<div class="box" style="width:300px"><b>You get from {{ t.username }}</b>{% for r in theirs %}<label><input type="checkbox" name="take" value="{{ r.id }}"> {{ r.name }}</label>{% else %}<p>They own nothing yet.</p>{% endfor %}
<label>+ Robux you ask for</label><input class="text-box" name="trobux" value="0" style="width:120px"></div></div>
<button class="btn-medium btn-primary" style="width:160px">Send trade</button></form>''', mine=mine, theirs=theirs, t=t, err=err)


@app.route('/trades')
@login_required
def trades():
    d, u = db(), cur_user()
    rows = d.all('select t.*, a.username as fname, b.username as tname from trades t join users a on a.id=t.frm join users b on b.id=t.tou where t.frm=? or t.tou=? order by t.id desc limit 50', (u['id'], u['id']))
    names = {r['id']: r['name'] for r in d.all('select id, name from items')}
    show = lambda ids, rb: ', '.join([names.get(i, '?') for i in _ids(ids)] + (['R$ %d' % rb] if rb else [])) or 'nothing'
    view = [dict(id=r['id'], status=r['status'], frm=r['fname'], to=r['tname'], mine=r['frm'] == u['id'], gives=show(r['gives'], r['grobux']), takes=show(r['takes'], r['trobux'])) for r in rows]
    return page('Trades', '''<table><tr><th>Trade</th><th>Status</th><th></th></tr>{% for r in view %}<tr><td>{% if r.mine %}You give <b>{{ r.gives }}</b> and get <b>{{ r.takes }}</b> from <a href="/user/{{ r.to }}">{{ r.to }}</a>{% else %}<a href="/user/{{ r.frm }}">{{ r.frm }}</a> gives <b>{{ r.gives }}</b> for your <b>{{ r.takes }}</b>{% endif %}</td><td>{{ r.status }}</td><td>
{% if r.status == 'pending' %}{% if r.mine %}<form method="post" action="/trade/{{ r.id }}/cancel"><button class="btn-small" style="background:#a00">Cancel</button></form>
{% else %}<form method="post" action="/trade/{{ r.id }}/accept" style="display:inline"><button class="btn-small btn-primary">Accept</button></form> <form method="post" action="/trade/{{ r.id }}/decline" style="display:inline"><button class="btn-small" style="background:#a00">Decline</button></form>{% endif %}{% endif %}</td></tr>
{% else %}<tr><td colspan="3">No trades yet. Open someone's profile and press Trade.</td></tr>{% endfor %}</table>''', view=view)


@app.route('/trade/<int:tid>/<act>', methods=['POST'])
@login_required
def trade_act(tid, act):
    d, u = db(), cur_user()
    t = d.one('select * from trades where id=?', (tid,)) or abort(404)
    if t['status'] != 'pending': return redirect('/trades')
    new = None
    if act == 'decline' and t['tou'] == u['id']: new = 'declined'
    elif act == 'cancel' and t['frm'] == u['id']: new = 'cancelled'
    elif act == 'accept' and t['tou'] == u['id']:
        give, take = _ids(t['gives']), _ids(t['takes'])
        owns = lambda uid, ids: all(d.one('select 1 as x from owned where uid=? and iid=?', (uid, i)) for i in ids)
        a, b = d.one('select robux from users where id=?', (t['frm'],)), d.one('select robux from users where id=?', (t['tou'],))
        ok = (owns(t['frm'], give) and owns(t['tou'], take) and not any(d.one('select 1 as x from owned where uid=? and iid=?', (t['tou'], i)) for i in give)
              and not any(d.one('select 1 as x from owned where uid=? and iid=?', (t['frm'], i)) for i in take) and a['robux'] >= t['grobux'] and b['robux'] >= t['trobux'])
        if ok:
            for ids, src, dst in ((give, t['frm'], t['tou']), (take, t['tou'], t['frm'])):
                for i in ids:
                    ser = (d.one('select serial from owned where uid=? and iid=?', (src, i)) or {'serial': None})['serial']
                    for tb in ('owned', 'equipped'): d.x('delete from %s where uid=? and iid=?' % tb, (src, i))
                    d.x('delete from listings where uid=? and iid=?', (src, i)); d.x('insert into owned(uid,iid,serial) values(?,?,?)', (dst, i, ser))
            d.x('update users set robux=robux-?+? where id=?', (t['grobux'], t['trobux'], t['frm'])); d.x('update users set robux=robux+?-? where id=?', (t['grobux'], t['trobux'], t['tou']))
        new = 'accepted' if ok else 'failed'
    else: abort(403)
    d.x('update trades set status=? where id=?', (new, tid)); d.commit()
    return redirect('/trades')


@app.route('/sell/<int:iid>', methods=['POST'])
@login_required
def sell(iid):
    u, d = cur_user(), db()
    if not d.one('select 1 as x from owned where uid=? and iid=?', (u['id'], iid)): abort(403)
    if not (d.one('select limited from items where id=?', (iid,)) or {'limited': 0})['limited']: abort(403)      # only Limited and Limited U can be resold
    try: price = int(request.form.get('price', ''))
    except ValueError: price = 0
    if price < 1: return redirect('/item/%d?err=Enter+a+price+of+at+least+1+Robux.' % iid)
    d.x('delete from listings where iid=? and uid=?', (iid, u['id']))
    d.x('insert into listings(iid,uid,price,created) values(?,?,?,?)', (iid, u['id'], price, today())); d.commit()
    return redirect('/item/%d' % iid)


@app.route('/unsell/<int:iid>', methods=['POST'])
@login_required
def unsell(iid):
    db().x('delete from listings where iid=? and uid=?', (iid, cur_user()['id'])); db().commit()
    return redirect('/item/%d' % iid)


@app.route('/buy/<int:iid>/from/<int:lid>', methods=['POST'])
@login_required
def buy_from(iid, lid):
    d, u = db(), cur_user()
    l = d.one('select * from listings where id=? and iid=?', (lid, iid)) or abort(404)
    if l['uid'] == u['id'] or d.one('select 1 as x from owned where uid=? and iid=?', (u['id'], iid)): return redirect('/item/%d' % iid)
    if d.x('update users set robux=robux-? where id=? and robux>=?', (l['price'], u['id'], l['price'])).rowcount != 1:
        return redirect('/item/%d?err=Not+enough+Robux.' % iid)
    d.x('update users set robux=robux+? where id=?', (l['price'], l['uid']))
    ser = (d.one('select serial from owned where uid=? and iid=?', (l['uid'], iid)) or {'serial': None})['serial']
    for t in ('owned', 'equipped'): d.x('delete from %s where uid=? and iid=?' % t, (l['uid'], iid))
    d.x('delete from listings where id=?', (lid,))
    d.x('insert into owned(uid,iid,serial) values(?,?,?)', (u['id'], iid, ser)); d.commit()
    return redirect('/item/%d' % iid)


@app.route('/item/<int:iid>/delete', methods=['POST'])
@login_required
def item_delete(iid):
    u, d = cur_user(), db()
    it = d.one('select * from items where id=?', (iid,)) or abort(404)
    if not (u['admin'] or u['id'] == it['uid']): abort(403)
    for t in ('owned', 'equipped', 'listings', 'bodyparts'): d.x('delete from %s where iid=?' % t, (iid,))
    d.x('delete from items where id=?', (iid,)); d.commit()
    return redirect('/catalog')


# ---------- games (uploads only, no fake ones) ----------
@app.route('/games')
def games():
    rows = db().all('select id, title, thumb from games order by id desc')
    return page('Games', '''{% if user %}<p><a href="/game/new"><b>+ Upload a game</b></a></p>{% endif %}<div class="grid">
{% for r in rows %}<div class="card"><i {% if r.thumb %}style="background:url(/files/{{ r.thumb }}) center/cover"{% endif %}></i><a href="/game/{{ r.id }}">{{ r.title }}</a></div>
{% else %}<p>No games yet. {% if user %}Upload the first one!{% else %}<a href="/newlogin?next=/games">Log in</a> to upload one.{% endif %}</p>{% endfor %}</div>''', rows=rows)


@app.route('/genre/<genre>')
def genre(genre):
    if genre not in GENRES: abort(404)
    rows = db().all('select id, title, thumb from games where genre=? order by id desc', (genre,))
    return page(genre.replace('-', ' ').title() + ' Games', '<div class="grid">{% for r in rows %}<div class="card"><i></i><a href="/game/{{ r.id }}">{{ r.title }}</a></div>{% else %}<p>No games in this genre yet.</p>{% endfor %}</div><p><a href="/games">All games</a></p>', rows=rows)


@app.route('/game/new', methods=['GET', 'POST'])
@login_required
def game_new():
    err = None
    if request.method == 'POST':
        try:
            t = request.form.get('title', '').strip()[:80]
            if not t: raise ValueError('Please give your game a title.')
            fl = save_upload(request.files.get('file'), 'game')
            if not fl: raise ValueError('Choose a game file (.rbxl, .rbxlx, .zip or .html).')
            th = save_upload(request.files.get('thumb'), 'tex')
            gn = request.form.get('genre') if request.form.get('genre') in GENRES else 'adventure'
            gid = db().ins('insert into games(uid,title,descr,file,thumb,genre,created) values(?,?,?,?,?,?,?)', (cur_user()['id'], t, request.form.get('descr', '')[:2000], fl, th, gn, today()))
            db().commit()
            return redirect('/game/%d' % gid)
        except ValueError as e:
            db().c.rollback(); err = str(e)
    return page('Upload Game', '''{% if err %}<div class="err">{{ err }}</div>{% endif %}<form method="post" enctype="multipart/form-data"><div class="box" style="width:430px">
<label>Title</label><input class="text-box" name="title" maxlength="80"><label>Description</label><textarea name="descr"></textarea>
<label>Genre</label><select class="form-select" name="genre" style="width:140px">{% for g in genres %}<option>{{ g }}</option>{% endfor %}</select>
<label>Game file (.rbxl, .rbxlx, .zip, .html)</label><input type="file" name="file"><label>Thumbnail (optional)</label><input type="file" name="thumb">
<button class="btn-medium btn-neutral" type="submit">Upload</button></div></form>''', err=err, genres=GENRES)


@app.route('/game/<int:gid>/delete', methods=['POST'])
@login_required
def game_delete(gid):
    u = cur_user()
    r = db().one('select * from games where id=?', (gid,)) or abort(404)
    if not (u['admin'] or u['id'] == r['uid']): abort(403)
    db().x('delete from games where id=?', (gid,)); db().commit()
    return redirect('/games')


# ---------- people, forum, settings, admin ----------
@app.route('/people')
def people():
    q = request.args.get('q', '').strip()
    rows = db().all('select username, joined from users where lower(username) like lower(?) order by id desc limit 100', ('%' + q + '%',))
    return page('People', '<form><input class="text-box" name="q" value="{{ q }}" placeholder="Search members"> <button class="btn-medium btn-neutral" style="display:inline-block;font-size:16px;height:25px;line-height:25px">Search</button></form><br><table><tr><th>Member</th><th>Joined</th></tr>{% for r in rows %}<tr><td><a href="/user/{{ r.username }}">{{ r.username }}</a></td><td>{{ r.joined }}</td></tr>{% endfor %}</table>', q=q, rows=rows)


@app.route('/user/<name>')
def profile(name):
    d = db()
    u = d.one('select * from users where lower(username)=lower(?)', (name,)) or abort(404)
    n = d.one('select count(*) as n from posts where uid=?', (u['id'],))['n']
    return page(u['username'], '<div style="display:flex;gap:28px;align-items:flex-start">' + AVATAR + '<div class="box" style="width:320px"><p>Member since {{ u.joined }}</p><p>Forum posts: {{ n }}</p>{% if user and user.id != u.id %}<p><a href="/trade/{{ u.username }}"><b>Trade with {{ u.username }}</b></a></p>{% endif %}<p style="white-space:pre-wrap">{{ u.blurb }}</p></div></div>', u=u, n=n, eq=eq_list(u['id']), w=360)


@app.route('/leaderboards')
def leaderboards():
    top = db().all('select u.username, u.robux, count(p.id) as c from users u left join posts p on p.uid=u.id group by u.id, u.username, u.robux order by c desc, u.id limit 20')
    return page('Leaderboards', '<table><tr><th>#</th><th>Member</th><th>Forum posts</th></tr>{% for r in top %}<tr><td>{{ loop.index }}</td><td><a href="/user/{{ r.username }}">{{ r.username }}</a></td><td>{{ r.c }}</td></tr>{% endfor %}</table>', top=top)


@app.route('/forum', methods=['GET', 'POST'])
def forum():
    if request.method == 'POST':
        if not cur_user(): return redirect('/newlogin?next=/forum')
        s, b = request.form.get('subject', '').strip()[:100], request.form.get('body', '').strip()[:5000]
        if s and b:
            db().x('insert into posts(uid,subject,body,created) values(?,?,?,?)', (cur_user()['id'], s, b, datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))); db().commit()
        return redirect('/forum')
    rows = db().all('select p.id, p.subject, p.created, u.username from posts p join users u on u.id=p.uid order by p.id desc limit 100')
    return page('Forum', '''<table><tr><th>Subject</th><th>Author</th><th>Posted</th></tr>{% for r in rows %}<tr><td><a href="/forum/{{ r.id }}">{{ r.subject }}</a></td><td>{{ r.username }}</td><td>{{ r.created }}</td></tr>{% endfor %}</table>
{% if user %}<form method="post"><div class="box" style="width:360px"><label>Subject</label><input class="text-box" name="subject" maxlength="100"><label>Message</label><textarea name="body"></textarea><button class="btn-medium btn-neutral" type="submit">Post</button></div></form>{% else %}<p><a href="/newlogin?next=/forum">Log in</a> to post.</p>{% endif %}''', rows=rows)


@app.route('/forum/<int:pid>')
def forum_post(pid):
    r = db().one('select p.*, u.username from posts p join users u on u.id=p.uid where p.id=?', (pid,)) or abort(404)
    return page(r['subject'], '<div class="box"><p><b>{{ r.username }}</b> &middot; {{ r.created }}</p><p style="white-space:pre-wrap">{{ r.body }}</p></div><p><a href="/forum">Back to forum</a></p>', r=r)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    u, msg = cur_user(), None
    if request.method == 'POST':
        f = request.form
        if f.get('action') == 'blurb':
            db().x('update users set blurb=? where id=?', (f.get('blurb', '')[:500], u['id'])); db().commit(); msg = 'Saved.'
        elif not cph(u['pw'], f.get('old', '')): msg = 'Current password is wrong.'
        elif len(f.get('new', '')) < 6: msg = 'New password must be at least 6 characters.'
        else:
            db().x('update users set pw=? where id=?', (gph(f['new']), u['id'])); db().commit(); msg = 'Password changed.'
    return page('Settings', '''{% if msg %}<div class="box" style="width:360px">{{ msg }}</div>{% endif %}
<form method="post"><input type="hidden" name="action" value="blurb"><div class="box" style="width:360px"><label>About me</label><textarea name="blurb">{{ user.blurb }}</textarea><button class="btn-medium btn-neutral">Save</button></div></form>
<form method="post"><input type="hidden" name="action" value="password"><div class="box" style="width:360px"><label>Current password</label><input class="text-box" type="password" name="old"><label>New password</label><input class="text-box" type="password" name="new"><button class="btn-medium btn-neutral">Change</button></div></form>''', msg=msg)


@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin():
    msg, f, d = None, request.form, db()
    if request.method == 'POST':
        a, name = f.get('action'), f.get('username', '').strip()
        if a == 'announce': set_setting('announcement', f.get('text', '')[:300]); msg = 'Announcement updated.'
        elif a == 'flags': set_setting('admin_fly', '1' if f.get('admin_fly') else '0'); msg = 'Client settings saved.'
        elif a in ('grant', 'ban', 'unban'):
            u = d.one('select * from users where lower(username)=lower(?)', (name,))
            if not u: msg = 'No such user.'
            elif a == 'grant':
                try: d.x('update users set robux=robux+? where id=?', (int(f.get('amount', 0)), u['id'])); d.commit(); msg = 'Robux updated.'
                except ValueError: msg = 'Amount must be a number.'
            elif u['admin']: msg = 'Admins cannot be banned.'
            else: d.x('update users set banned=? where id=?', (1 if a == 'ban' else 0, u['id'])); d.commit(); msg = 'Done.'
    return page('Admin', '''{% if msg %}<div class="box" style="width:420px">{{ msg }}</div>{% endif %}
<form method="post"><input type="hidden" name="action" value="announce"><div class="box" style="width:420px"><label>Site announcement (shown on every page, empty = hide)</label><input class="text-box" name="text" value="{{ ann }}" style="width:380px"><button class="btn-medium btn-neutral">Publish</button></div></form>
<form method="post"><input type="hidden" name="action" value="grant"><div class="box" style="width:420px"><label>Give Robux (negative removes)</label><input class="text-box" name="username" placeholder="username"><input class="text-box" name="amount" placeholder="amount" style="margin-top:6px"><button class="btn-medium btn-neutral">Give</button></div></form>
<form method="post"><div class="box" style="width:420px"><label>Ban / unban</label><input class="text-box" name="username" placeholder="username"><button class="btn-medium btn-neutral" name="action" value="ban">Ban</button> <button class="btn-medium btn-neutral" name="action" value="unban">Unban</button></div></form>
<form method="post"><input type="hidden" name="action" value="flags"><div class="box" style="width:420px"><label><input type="checkbox" name="admin_fly" {{ 'checked' if fly }}> Admins can fly and use commands in game (read by the client)</label><button class="btn-medium btn-neutral">Save</button></div></form>
<p><a href="/item/new">+ Add an official item</a> &nbsp; <a href="/admin/asset">Check a Roblox ID</a> &nbsp; <a href="/admin/restore">Restore data</a></p>''', msg=msg, ann=setting('announcement'), fly=setting('admin_fly') == '1')


@app.route('/api/me')
def api_me():
    u = cur_user()
    if not u: return jsonify(loggedIn=False)
    return jsonify(loggedIn=True, username=u['username'], admin=bool(u['admin']), robux=u['robux'], equipped=eq_list(u['id']), flags={'admin_fly': setting('admin_fly') == '1'})


@app.route('/upgrades')
def upgrades(): return page('Builders Club', '<div class="box"><p>Builders Club is not sold here. Everyone builds for free.</p></div>')


@app.route('/blog')
def blog(): return page('Blog', '<div class="box"><h2>Welcome to the server</h2><p>Sign up, upload items, and say hi on the forum.</p></div>')


@app.route('/help')
def help_(): return page('Help', '<div class="box"><p>Need your password reset? Ask the server owner. Questions? Post on the <a href="/forum">forum</a>.</p></div>')


@app.route('/forgot')
def forgot(): return page('Forgot your password?', '<div class="box"><p>Ask the person who runs this server to reset your password.</p></div><p><a href="/newlogin">Back to login</a></p>')


@app.route('/facebook')
def facebook(): return page('Login with Facebook', '<div class="box"><p>Facebook login is not available on this server.</p></div><p><a href="/newlogin">Back to login</a></p>')


@app.route('/info/<slug>')
def info(slug):
    t, b = INFO.get(slug) or abort(404)
    return page(t, '<div class="box"><p>{{ b }}</p></div>', b=b)


import io
# ---------- play: connecting the 2014 client ----------
import subprocess, time, zipfile
from urllib.parse import quote

CLIENT_DIR = os.environ.get('CLIENT_DIR') or next((p for p in (os.path.join(BASE, '2014M'), os.path.join(BASE, '..', '2014M')) if os.path.isdir(p)), '')
GAME_PORT = int(os.environ.get('GAME_PORT', 53640))
GAME_SERVER = os.environ.get('GAME_SERVER', '')       # "host:port" of a game server you start yourself (used instead of CLIENT_DIR)
RCC = {'proc': None, 'gid': None}
with sqlite3.connect(os.path.join(DATA, 'rbx2014.db')) if not PG else psycopg2.connect(PG.replace('postgres://', 'postgresql://', 1)) as _c:
    _c.cursor().execute('create table if not exists launches(token text primary key, uid integer, gid integer, created text)')


import struct, math
import xml.etree.ElementTree as ET
import urllib.error
DROP = 0.2      # hats sit a little lower on the head


def obj_tris(text):
    P, T, N, tris = [], [], [], []
    ix = lambda i, n: i + n if i < 0 else i - 1
    for line in text.splitlines():
        a = line.split()
        if not a: continue
        if a[0] == 'v': P.append([float(x) for x in a[1:4]])
        elif a[0] == 'vt': T.append([float(x) for x in a[1:3]])
        elif a[0] == 'vn': N.append([float(x) for x in a[1:4]])
        elif a[0] == 'f':
            v = []
            for s in a[1:]:
                p = (s.split('/') + ['', ''])[:3]
                v.append((P[ix(int(p[0]), len(P))], T[ix(int(p[1]), len(T))] if p[1] else [0, 0], N[ix(int(p[2]), len(N))] if p[2] else None))
            tris += [(v[0], v[i], v[i + 1]) for i in range(1, len(v) - 1)]
    if not tris: raise ValueError('That model file has no triangles.')
    return tris


def v1_tris(text):
    lines = text.split('\n'); s = 0.5 if lines[0].startswith('version 1.00') else 1.0
    n = [float(x) for x in re.findall(r'-?\d*\.?\d+(?:[eE][-+]?\d+)?', ' '.join(lines[2:]))]
    v = [((n[i] * s, n[i + 1] * s, n[i + 2] * s), (n[i + 6], n[i + 7]), (n[i + 3], n[i + 4], n[i + 5])) for i in range(0, len(n) - 8, 9)]
    return [tuple(v[i:i + 3]) for i in range(0, len(v) - 2, 3)]


def bin_tris(d):
    o, ver = 13, d[8:9]
    hs = struct.unpack_from('<H', d, o)[0]
    if ver == b'4': nv, nf = struct.unpack_from('<II', d, o + 4); vs = 40
    elif ver == b'3': vs = d[o + 2]; nv, nf = struct.unpack_from('<II', d, o + 8)
    else: vs = d[o + 2]; nv, nf = struct.unpack_from('<II', d, o + 4)
    vo = o + hs; fo = vo + nv * vs
    if ver == b'4' and struct.unpack_from('<H', d, o + 14)[0]: fo += nv * 8          # skinning data sits between vertices and faces
    if ver == b'3' and struct.unpack_from('<H', d, o + 6)[0] > 1: nf = struct.unpack_from('<I', d, fo + nf * 12 + 4)[0]
    V = [(struct.unpack_from('<3f', d, vo + i * vs), struct.unpack_from('<2f', d, vo + i * vs + 24), struct.unpack_from('<3f', d, vo + i * vs + 12)) for i in range(nv)]
    return [tuple(V[j] for j in struct.unpack_from('<3I', d, fo + f * 12)) for f in range(nf)]


def mesh_tris(data):
    """Any supported mesh -> (triangles, came_from_roblox_format)."""
    if data[:8] == b'version ':
        v = data[8:9]
        if data[:11] == b'version 1.0' or data[:11] == b'version 1.1': return v1_tris(data.decode('latin1')), True
        if v in (b'2', b'3', b'4'): return bin_tris(data), True
        raise ValueError('Mesh %s is a newer format that is not supported yet (versions 1-4 work).' % data[:12].decode('ascii', 'ignore').strip())
    return obj_tris(data.decode('utf8', 'ignore')), False


def write_v1(tris, maxd=None, center=True, flipuv=False):
    """Roblox text mesh (version 1.00), centred on its bounding box and optionally scaled to maxd studs."""
    pts = [q[0] for t in tris for q in t]
    mn = [min(p[k] for p in pts) for k in range(3)]; mx = [max(p[k] for p in pts) for k in range(3)]
    ctr = [(mn[k] + mx[k]) / 2 for k in range(3)] if center else [0, 0, 0]
    s = maxd / (max(mx[k] - mn[k] for k in range(3)) or 1) if maxd else 1.0
    out = []
    for t in tris:
        a, b, c = (q[0] for q in t)
        u, w = [b[k] - a[k] for k in range(3)], [c[k] - a[k] for k in range(3)]
        fn = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
        ln = sum(x * x for x in fn) ** .5 or 1
        for p, uv, n in t:
            n = n or [x / ln for x in fn]
            out.append('[%.5f,%.5f,%.5f][%.5f,%.5f,%.5f][%.5f,%.5f,0]' % tuple([(p[k] - ctr[k]) * s * 2 for k in range(3)] + list(n) + [uv[0], 1 - uv[1] if flipuv else uv[1]]))   # v1.00 halves positions
    return 'version 1.00\n%d\n%s' % (len(tris), ''.join(out)), (mx[1] - mn[1]) * s


def store_mesh(data, kind):
    """Convert any mesh to the format the 2014 client reads and keep it in the database."""
    tris, rb = mesh_tris(data)
    return put(write_v1(tris, None if rb else (2.5 if kind == 'tool' else 1.5), kind != 'body', not rb)[0].encode(), '.mesh')


def mesh_data(it):
    r = db().one('select data from blobs where name=?', (it['mesh'],)) or abort(404)
    tris, rb = mesh_tris(bytes(r['data']))
    t, h = write_v1(tris, None if rb else (2.5 if it['kind'] == 'tool' else 1.5), True, (not rb) != bool(it['flipv']))
    return t.encode(), h


def _cf(name, pos=(0, 0, 0), rot=(1, 0, 0, 0, 1, 0, 0, 0, 1)):
    return '<CoordinateFrame name="%s"><X>%.4f</X><Y>%.4f</Y><Z>%.4f</Z>%s</CoordinateFrame>' % (
        name, pos[0], pos[1], pos[2], ''.join('<R%d%d>%s</R%d%d>' % (i // 3, i % 3, rot[i], i // 3, i % 3) for i in range(9)))


def _place(it, h):
    """Attachment/grip frame for the saved position (viewer front is +Z, Roblox front is -Z, so x and z flip)."""
    ox, oy, oz, rot, scl = (it['ox'] or 0), (it['oy'] or 0), (it['oz'] or 0), (it['rot'] or 0), (it['scl'] or 1)
    r = math.radians(rot); c, s = math.cos(r), math.sin(r)
    t = (-ox, oy + ((h * scl) / 2 - DROP if it['kind'] == 'hat' else 0), -oz)
    v = (c * t[0] - s * t[2], t[1], s * t[0] + c * t[2])
    return (-v[0], -v[1], -v[2]), (round(c, 5), 0, round(-s, 5), 0, 1, 0, round(s, 5), 0, round(c, 5)), scl


def item_xml(it, base):
    e = lambda s: (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    tex = '%s/files/%s' % (base, it['tex']) if it['tex'] else ''
    k = it['kind']
    if k in ('hat', 'tool'):
        pos, rot, scl = _place(it, mesh_data(it)[1])
        part = ('<Item class="Part" referent="RBX1"><Properties><string name="Name">Handle</string><token name="FormFactor">1</token><Vector3 name="size"><X>1</X><Y>1</Y><Z>1</Z></Vector3></Properties>'
                '<Item class="SpecialMesh" referent="RBX2"><Properties><string name="Name">Mesh</string><Content name="MeshId"><url>%s/mesh/%d.mesh</url></Content>%s'
                '<token name="MeshType">5</token><Vector3 name="Scale"><X>%s</X><Y>%s</Y><Z>%s</Z></Vector3></Properties></Item></Item>') % (
                    base, it['id'], '<Content name="TextureId"><url>%s</url></Content>' % tex if tex else '', scl, scl, scl)
        if k == 'hat':
            body = '<Item class="Hat" referent="RBX0"><Properties>%s<string name="Name">%s</string></Properties>%s</Item>' % (_cf('AttachmentPoint', pos, rot), e(it['name']), part)
        else:
            body = '<Item class="Tool" referent="RBX0"><Properties>%s<string name="Name">%s</string><bool name="CanBeDropped">false</bool><bool name="RequiresHandle">true</bool></Properties>%s</Item>' % (_cf('Grip', pos, rot), e(it['name']), part)
    elif k == 'shirt':
        body = '<Item class="Shirt" referent="RBX0"><Properties><string name="Name">Shirt</string><Content name="ShirtTemplate"><url>%s</url></Content></Properties></Item>' % tex
    elif k == 'pants':
        body = '<Item class="Pants" referent="RBX0"><Properties><string name="Name">Pants</string><Content name="PantsTemplate"><url>%s</url></Content></Properties></Item>' % tex
    elif k == 'tshirt':
        body = '<Item class="ShirtGraphic" referent="RBX0"><Properties><string name="Name">Shirt Graphic</string><Content name="Graphic"><url>%s</url></Content></Properties></Item>' % tex
    else:
        body = '<Item class="Decal" referent="RBX0"><Properties><string name="Name">face</string><token name="Face">5</token><Content name="Texture"><url>%s</url></Content></Properties></Item>' % tex
    return '<roblox version="4">\n%s\n</roblox>' % body


# ---------- importing Roblox assets by ID (bare meshes, images, and hat/tool/shirt/face wrapper files) ----------
import json, gzip


def http_get(url, headers=None):
    h = {'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'identity'}; h.update(headers or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r: d = r.read(30 * 1024 * 1024)
    except urllib.error.HTTPError as ex:
        raise ValueError('Roblox has no downloadable asset with that ID (HTTP %d). It is private, removed, or it is not an asset ID - for bodies use the package or body-part ID, or the bundle number.' % ex.code if ex.code in (404, 400) else 'Roblox refused the download (HTTP %d). The asset is private or off-sale.' % ex.code)
    except Exception:
        raise ValueError('This server could not reach Roblox (no internet?).')
    return gzip.decompress(d) if d[:2] == b'\x1f\x8b' else d


def fetch_asset_bytes(aid):
    try:
        d = http_get('https://assetdelivery.roblox.com/v1/asset/?id=%d' % aid)
        if not (d[:1] == b'{' and b'"errors"' in d[:400]): return d
        first = ValueError('Roblox said: ' + d[:200].decode('latin1'))
    except ValueError as ex:
        first = ex
    try:                                                   # second route: ask for the CDN address, then download from it
        j = json.loads(http_get('https://assetdelivery.roblox.com/v2/assetId/%d' % aid, {'Accept': 'application/json'}))
        return http_get(j['locations'][0]['location'])
    except Exception:
        raise first


def get_raw(aid):
    name = 'rbxraw_%d' % aid
    r = db().one('select data from blobs where name=?', (name,))
    if r: return bytes(r['data'])
    data = fetch_asset_bytes(aid)
    try: put(data, '', name); db().commit()
    except INTEG: db().c.rollback()
    return data


def lz4_block(src):
    out, i = bytearray(), 0
    while i < len(src):
        tok = src[i]; i += 1; ll = tok >> 4
        if ll == 15:
            while True:
                b = src[i]; i += 1; ll += b
                if b != 255: break
        out += src[i:i + ll]; i += ll
        if i >= len(src): break
        off = src[i] | (src[i + 1] << 8); i += 2; ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255: break
        st = len(out) - off
        for _ in range(ml + 4): out.append(out[st]); st += 1
    return bytes(out)


WANT = ('MeshId', 'TextureId', 'TextureID', 'ShirtTemplate', 'PantsTemplate', 'Graphic', 'Texture')
ID_RE = re.compile(rb'(?:id=|rbxassetid://)(\d+)')


def classify(d):
    if d[:8] == b'version ': return 'mesh'
    if d[:4] == b'\x89PNG' or d[:2] == b'\xff\xd8': return 'image'
    if d[:8] == b'<roblox!' or d.lstrip()[:7] == b'<roblox': return 'wrapper'
    if len(d) < 4000 and ID_RE.search(d) and re.fullmatch(rb'[\w:/.?=&;,\s%-]+', d.strip()): return 'idlist'      # a package: just a list of asset ids
    return 'unknown'


def preview(d): return ''.join(chr(c) if 32 <= c < 127 else '.' for c in d[:70])


def wrapper_info(data):
    """Class names and asset ids inside an rbxm (binary) or rbxmx (xml) file. Asset ids are found by text, whatever the property type."""
    info = {'classes': set(), 'ids': {}, 'all': []}
    def grab(prop, raw):
        found = [m.group(1).decode() for m in ID_RE.finditer(raw)]
        if prop in WANT: info['ids'].setdefault(prop, []).extend(found)
        info['all'].extend(found)
    try:
        if data[:8] == b'<roblox!':
            pos, counts = 32, {}
            while pos + 16 <= len(data):
                name = data[pos:pos + 4]; clen, ulen = struct.unpack_from('<II', data, pos + 4); pos += 16
                n = clen or ulen; payload = data[pos:pos + n]; pos += n
                if clen: payload = lz4_block(payload)
                if name == b'INST':
                    cid, ln = struct.unpack_from('<iI', payload, 0); info['classes'].add(payload[8:8 + ln].decode('latin1'))
                elif name == b'PROP':
                    cid, ln = struct.unpack_from('<iI', payload, 0); grab(payload[8:8 + ln].decode('latin1'), payload[9 + ln:])
                elif name.startswith(b'END'): break
        else:
            for item in ET.fromstring(data).iter('Item'):
                info['classes'].add(item.get('class'))
                props = item.find('Properties')
                for p in (props if props is not None else []):
                    v = p.findtext('url') if p.tag == 'Content' else p.text
                    if v: grab(p.get('name'), v.encode())
    except Exception as ex:
        raise ValueError('Could not read this asset file (%s).' % ex.__class__.__name__)
    return info


def character_meshes(data):
    """R6 body parts from CharacterMesh objects (rbxm or rbxmx): [(Roblox BodyPart number, mesh id, texture id)]."""
    out = []
    try:
        if data[:8] == b'<roblox!':
            classes, counts, vals, pos = {}, {}, {}, 32
            while pos + 16 <= len(data):
                name = data[pos:pos + 4]; clen, ulen = struct.unpack_from('<II', data, pos + 4); pos += 16
                n = clen or ulen; payload = data[pos:pos + n]; pos += n
                if clen: payload = lz4_block(payload)
                if name == b'INST':
                    cid, ln = struct.unpack_from('<iI', payload, 0); classes[cid] = payload[8:8 + ln].decode('latin1'); counts[cid] = struct.unpack_from('<i', payload, 9 + ln)[0]
                elif name == b'PROP':
                    cid, ln = struct.unpack_from('<iI', payload, 0)
                    if classes.get(cid) != 'CharacterMesh': continue
                    prop, raw, cnt = payload[8:8 + ln].decode('latin1'), payload[9 + ln:], counts[cid]
                    if prop == 'BodyPart': vals['part'] = [int.from_bytes(bytes(raw[k * cnt + i] for k in range(4)), 'big') for i in range(cnt)]
                    elif prop in ('MeshId', 'BaseTextureId'):
                        o, L = 0, []
                        for _ in range(cnt):
                            sl = struct.unpack_from('<I', raw, o)[0]; L.append(raw[o + 4:o + 4 + sl]); o += 4 + sl
                        vals[prop] = L
                elif name.startswith(b'END'): break
            for i, p in enumerate(vals.get('part', [])):
                m = ID_RE.search((vals.get('MeshId') or [b''] * 9)[i]); t = ID_RE.search((vals.get('BaseTextureId') or [b''] * 9)[i])
                if m: out.append((p, m.group(1).decode(), t.group(1).decode() if t else None))
        else:
            for item in ET.fromstring(data).iter('Item'):
                if item.get('class') != 'CharacterMesh': continue
                pr = {p.get('name'): (p.findtext('url') if p.tag == 'Content' else p.text) or '' for p in (item.find('Properties') if item.find('Properties') is not None else [])}
                m = ID_RE.search(pr.get('MeshId', '').encode()); t = ID_RE.search(pr.get('BaseTextureId', '').encode())
                if m and (pr.get('BodyPart') or '').strip().isdigit(): out.append((int(pr['BodyPart']), m.group(1).decode(), t.group(1).decode() if t else None))
    except Exception:
        return []
    return out


def collect_char_meshes(aid, depth=0):
    d = get_raw(int(aid)); c = classify(d); found = []
    ids = []
    if c == 'wrapper':
        found = character_meshes(d)
        if not found: ids = wrapper_info(d)['all']
    elif c == 'idlist': ids = [m.group(1).decode() for m in ID_RE.finditer(d)]
    if not found and depth < 2:
        for i in list(dict.fromkeys(ids))[:12]:
            try: found += collect_char_meshes(i, depth + 1)
            except ValueError: pass
    return found


def bundle_ids(rid):
    j = json.loads(http_get('https://catalog.roblox.com/v1/bundles/details?bundleIds=%s' % rid))
    return [str(i['id']) for b in j for i in b.get('items', []) if i.get('type') == 'Asset']


def build_body(rid, ids=None):
    seen, parts = set(), []
    entries = [e for i in ids for e in collect_char_meshes(i)] if ids else collect_char_meshes(rid)
    for part, mid, tid in entries:
        if part in seen or part not in range(6): continue
        try: mesh = store_mesh(get_raw(int(mid)), 'body')
        except ValueError: continue
        tex = None
        if tid:
            try: tex = store_image(tid)
            except ValueError: pass
        seen.add(part); parts.append(dict(part=part, mesh=mesh, tex=tex))
    return parts


def _ext(d): return '.png' if d[:4] == b'\x89PNG' else '.jpg'


def find_image(tid, depth=0):
    """Bytes of the image behind an image or decal asset id."""
    d = get_raw(int(tid))
    if classify(d) == 'image': return d, _ext(d)
    if depth == 0 and classify(d) == 'wrapper':
        info = wrapper_info(d)
        for i in dict.fromkeys(info['all']):
            try: return find_image(i, 1)
            except ValueError: pass
    raise ValueError('Asset %s is not an image.' % tid)


def store_image(tid):
    d, ext = find_image(tid)
    name = 'rbximg_%s%s' % (tid, ext)
    if not db().one('select 1 as x from blobs where name=?', (name,)): put(d, ext, name)
    return name


def import_roblox(rid, kind):
    """Roblox item/asset id -> dict(kind, mesh, tex). Works for bare meshes/images and for hat, tool, shirt, T-shirt and face assets."""
    if not rid.isdigit(): raise ValueError('IDs must be numbers.')
    try: data = get_raw(int(rid))
    except ValueError as first:
        if kind in ('body', ''):                       # not an asset: maybe a bundle number from roblox.com/bundles/<id>
            try:
                parts = build_body(rid, bundle_ids(rid))
                if parts: return {'kind': 'body', 'mesh': None, 'tex': None, 'parts': parts}
            except Exception:
                pass
        raise first
    k = classify(data); mesh_raw = img = None; cl = set(); tried = []
    if kind == 'body' or k == 'idlist' or (k == 'wrapper' and 'CharacterMesh' in wrapper_info(data)['classes']):
        parts = build_body(rid)
        if not parts: raise ValueError('No R6 body parts found inside asset %s. Roblox sent %d bytes (%s: %s).' % (rid, len(data), k, preview(data)))
        return {'kind': 'body', 'mesh': None, 'tex': None, 'parts': parts}
    if k == 'mesh': mesh_raw = data
    elif k == 'image': img = (data, _ext(data), rid)
    elif k == 'wrapper':
        info = wrapper_info(data); cl = info['classes']
        order = [i for p in WANT for i in info['ids'].get(p, [])]
        for cid in list(dict.fromkeys(order + info['all']))[:12]:
            if mesh_raw and img: break
            try: d = get_raw(int(cid))
            except ValueError as ex: tried.append('%s: %s' % (cid, ex)); continue
            c = classify(d)
            if c == 'mesh' and not mesh_raw: mesh_raw = d
            elif c == 'image' and not img: img = (d, _ext(d), cid)
            elif c == 'wrapper' and not img:
                try: dd, ee = find_image(cid); img = (dd, ee, cid)
                except ValueError: pass
    if not mesh_raw and not img:
        raise ValueError('Nothing usable inside asset %s. Roblox sent %d bytes (%s: %s). Classes: %s. %s' % (
            rid, len(data), k, preview(data), ', '.join(sorted(c for c in cl if c)) or 'none', ' '.join(tried[:3])))
    kind = kind or ('hat' if cl & {'Hat', 'Accessory'} else 'tool' if 'Tool' in cl else 'pants' if 'Pants' in cl else 'shirt' if 'Shirt' in cl else 'tshirt' if 'ShirtGraphic' in cl else 'face' if 'Decal' in cl else ('hat' if mesh_raw else ''))
    if not kind: raise ValueError('Choose an item type for this ID.')
    if kind in ('hat', 'tool') and not mesh_raw: raise ValueError('Asset %s has no mesh, so it cannot be a %s.' % (rid, kind))
    if kind in ('face', 'shirt', 'pants', 'tshirt') and not img: raise ValueError('Asset %s has no image, so it cannot be a %s.' % (rid, kind))
    mesh = store_mesh(mesh_raw, kind) if kind in ('hat', 'tool') else None
    tex = None
    if img:
        tex = 'rbximg_%s%s' % (img[2], img[1])
        if not db().one('select 1 as x from blobs where name=?', (tex,)): put(img[0], img[1], tex)
    return {'kind': kind, 'mesh': mesh, 'tex': tex}


@app.route('/admin/asset')
@admin_required
def admin_asset():
    rid, out = request.args.get('id', '').strip(), ''
    if rid.isdigit():
        try:
            d = get_raw(int(rid)); c = classify(d); out = 'type: %s\nsize: %d bytes\nstarts with: %s' % (c, len(d), preview(d))
            if c == 'wrapper':
                i = wrapper_info(d); out += '\nclasses: %s\nids by property: %s\nall ids found: %s' % (', '.join(sorted(x for x in i['classes'] if x)), i['ids'], i['all'])
        except ValueError as ex:
            out = str(ex)
    return page('Check a Roblox ID', '<form><input class="text-box" name="id" value="{{ rid }}" placeholder="asset id"> <button class="btn-small btn-neutral">Check</button></form><br><div class="box"><pre style="white-space:pre-wrap;font-size:12px">{{ out }}</pre></div>', rid=rid, out=out)


def raw_asset(aid):
    """Public Roblox assets that places reference by ID are fetched once on the server and then served from our own database."""
    name = 'rbxraw_%d' % aid
    r = db().one('select data from blobs where name=?', (name,))
    if r: return bytes(r['data'])
    try:
        req = urllib.request.Request('https://assetdelivery.roblox.com/v1/asset/?id=%d' % aid, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as resp: data = resp.read(30 * 1024 * 1024)
    except Exception:
        abort(404)
    put(data, '', name); db().commit()
    return data


@app.route('/asset/')
@app.route('/Asset/')
def asset():
    base = request.url_root.rstrip('/')
    if request.args.get('item', '').isdigit() and request.args.get('part', '').isdigit():
        r = db().one('select * from bodyparts where iid=? and part=?', (int(request.args['item']), int(request.args['part']))) or abort(404)
        return Response('<roblox version="4">\n<Item class="CharacterMesh" referent="RBX0"><Properties><string name="Name">CharacterMesh</string><token name="BodyPart">%d</token><Content name="MeshId"><url>%s/files/%s</url></Content><Content name="BaseTextureId"><url>%s</url></Content><Content name="OverlayTextureId"><url></url></Content></Properties></Item>\n</roblox>' % (r['part'], base, r['mesh'], '%s/files/%s' % (base, r['tex']) if r['tex'] else ''), mimetype='text/xml')
    if request.args.get('item', '').isdigit():
        it = db().one('select * from items where id=?', (int(request.args['item']),)) or abort(404)
        return Response(item_xml(it, base), mimetype='text/xml')
    if request.args.get('id', '').isdigit():
        return Response(raw_asset(int(request.args['id'])), mimetype='application/octet-stream')
    abort(404)


@app.route('/mesh/<int:iid>.mesh')
def mesh_file(iid):
    it = db().one('select * from items where id=?', (iid,)) or abort(404)
    if not it['mesh']: abort(404)
    return Response(mesh_data(it)[0], mimetype='application/octet-stream')


def lua_str(s): return str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ').replace('\r', ' ')


def appearance(uid, base):
    urls = []
    for r in db().all('select i.id, i.kind from equipped e join items i on i.id=e.iid where e.uid=?', (uid,)):
        if r['kind'] == 'body': urls += ['%s/asset/?item=%d&part=%d' % (base, r['id'], p['p']) for p in body_parts(r['id'])]
        else: urls.append('%s/asset/?item=%d' % (base, r['id']))
    return ';'.join(urls) + '|Bright yellow;Bright blue;Bright yellow;Bright yellow;Br. yellowish green;Br. yellowish green'


def server_addr(host):
    if GAME_SERVER: h, _, p = GAME_SERVER.partition(':'); return h or host, int(p or GAME_PORT)
    return host, GAME_PORT


JOIN_LUA = '''-- generated by the site for @NAME@
local UID, IP, PORT = @UID@, "@IP@", @PORT@
pcall(function() settings().Network.UseInstancePacketCache = true end)
pcall(function() settings().Network.UsePhysicsPacketCache = true end)
pcall(function() game:GetService("ContentProvider"):SetBaseUrl("@BASE@/") end)
pcall(function() game:GetService("Players"):SetChatStyle(Enum.ChatStyle.ClassicAndBubble) end)
local client = game:GetService("NetworkClient")
local player = game:GetService("Players"):CreateLocalPlayer(UID)
pcall(function() player.Name = "@NAME@" end)
player.CharacterAppearance = "@APP@"
pcall(function() game:GetService("Visit"):SetUploadUrl("") end)
local function onDisconnection() pcall(function() game:SetMessage("You were disconnected from the game.") end) end
client.ConnectionAccepted:connect(function(url, replicator)
	local waiting = true
	pcall(function()
		replicator.Disconnection:connect(onDisconnection)
		local marker = replicator:SendMarker()
		marker.Received:connect(function() waiting = false end)
		while waiting do
			pcall(function() workspace:ZoomToExtents() end)
			wait(0.5)
		end
		game:ClearMessage()
	end)
end)
client.ConnectionRejected:connect(function() pcall(function() game:SetMessage("The server rejected the connection.") end) end)
client.ConnectionFailed:connect(function(_, code, msg) pcall(function() game:SetMessage("Could not connect to the game server (" .. tostring(msg) .. ")") end) end)
pcall(function() game:SetMessage("Connecting to the game...") end)
client:PlayerConnect(UID, IP, PORT, -1, 20)
'''


@app.route('/game/host.ashx')
def host_script():
    if request.remote_addr not in ('127.0.0.1', '::1'): abort(403)
    lua = open(os.path.join(BASE, 'rcc', 'host.lua'), encoding='utf8').read().replace('@PORT@', str(GAME_PORT)).replace('@BASE@', request.url_root.rstrip('/') + '/www.civdefn.tk')
    return Response(lua, mimetype='text/plain')


@app.route('/game/join.ashx')
def join_script():
    L = db().one('select * from launches where token=?', (request.args.get('token', ''),)) or abort(404)
    u = db().one('select * from users where id=?', (L['uid'],)) or abort(404)
    base = request.url_root.rstrip('/')
    ip, port = server_addr(request.host.rsplit(':', 1)[0] if ':' in request.host else request.host)
    lua = JOIN_LUA
    for k, v in (('NAME', u['username']), ('UID', u['id']), ('IP', ip), ('PORT', port), ('BASE', base), ('APP', appearance(u['id'], base))):
        lua = lua.replace('@%s@' % k, lua_str(v))
    return Response(lua, mimetype='text/plain')


def rcc_log_tail(n=40):
    c = [os.path.join(DATA, 'rcc.log')]
    for d in (os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Roblox', 'logs'), os.path.join(CLIENT_DIR or '', 'logs')):
        if d and os.path.isdir(d): c += [os.path.join(d, f) for f in os.listdir(d) if f.endswith(('.txt', '.log'))]
    c = [p for p in c if os.path.isfile(p)]
    if not c: return '(no log file found)'
    p = max(c, key=os.path.getmtime)
    return p + '\n' + ''.join(open(p, errors='replace').readlines()[-n:])


@app.route('/rcc-log')
@admin_required
def rcc_log():
    return page('Game server log', '<div class="box"><pre style="white-space:pre-wrap;font-size:12px">{{ log }}</pre></div>', log=rcc_log_tail(120))


def ensure_server(gid, local_base):
    """Start RCCService with the uploaded place on the PC that has the client folder. Returns an error text or None."""
    if GAME_SERVER: return None
    if not CLIENT_DIR or os.name != 'nt':
        return 'No game server is attached to this website. Run the site on the Windows PC that has the client folder (set CLIENT_DIR), or set GAME_SERVER to a server you started yourself.'
    g_ = db().one('select * from games where id=?', (gid,))
    if not g_['file'].endswith(('.rbxl', '.rbxlx')): return 'This upload is not a .rbxl / .rbxlx place file.'
    alive = RCC['proc'] and RCC['proc'].poll() is None
    if alive and RCC['gid'] == gid: return None
    if alive: RCC['proc'].terminate(); time.sleep(1.5)
    data = bytes(db().one('select data from blobs where name=?', (g_['file'],))['data'])
    for p in (os.path.join(CLIENT_DIR, 'content', 'temp.rbxl'), os.path.join(CLIENT_DIR, 'PlatformContent', 'temp.rbxl')):
        open(p, 'wb').write(data)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\r\n<Settings>\r\n\t<ContentFolder>content</ContentFolder>\r\n\t<BaseUrl>%s/</BaseUrl>\r\n</Settings>\r\n' % local_base
    open(os.path.join(CLIENT_DIR, 'AppSettings.xml'), 'w').write(xml)
    # RCCService.exe takes the same options as the client; its "launch script" is our host script
    cmd = [os.path.join(CLIENT_DIR, 'RCCService.exe'), '--play', '-a', local_base + '/Login/Negotiate.ashx', '-t', '0', '-j', local_base + '/game/host.ashx']
    lf = open(os.path.join(DATA, 'rcc.log'), 'wb'); lf.write(('Command: ' + ' '.join(cmd) + '\n').encode()); lf.flush()
    RCC['proc'] = subprocess.Popen(cmd, cwd=CLIENT_DIR, stdout=lf, stderr=subprocess.STDOUT)
    time.sleep(6)
    if RCC['proc'].poll() is not None: return 'RCCService closed right after starting (exit code %s). Last log lines:\n%s' % (RCC['proc'].returncode, rcc_log_tail())
    RCC['gid'] = gid
    return None


@app.route('/play/<int:gid>', methods=['GET', 'POST'])
def play(gid):
    r = db().one('select * from games where id=?', (gid,)) or abort(404)
    if r['file'].endswith('.html'):
        return page(r['title'], '<iframe sandbox="allow-scripts allow-pointer-lock" src="/files/{{ f }}" style="width:960px;height:600px;border:1px solid #bcbcbc"></iframe>', f=r['file'])
    if request.method == 'POST':
        u = cur_user() or abort(403)
        pt = request.host.rsplit(':', 1)[1] if ':' in request.host else '80'
        err = ensure_server(gid, 'http://localhost%s/www.civdefn.tk' % ('' if pt == '80' else ':' + pt))
        if err: return page(r['title'], '<div class="box"><p class="err" style="white-space:pre-wrap">{{ err }}</p></div>', err=err)
        tok = secrets.token_hex(12)
        db().x('insert into launches(token,uid,gid,created) values(?,?,?,?)', (tok, u['id'], gid, today())); db().x('update games set visits=coalesce(visits,0)+1 where id=?', (gid,)); db().commit()
        link = 'rbx2014://join?u=' + quote('%s/game/join.ashx?token=%s' % (request.url_root.rstrip('/'), tok), safe='')
        return page(r['title'], '<div class="box"><p>Starting the client with your equipped items...</p><p>If nothing opens, <a id="l" href="{{ link }}">click here</a>. First time? <a href="/client">Install the client patch</a>.</p></div><script>setTimeout(function(){location.href=document.getElementById("l").href},400)</script>', link=link)
    return page(r['title'], '''<div class="box"><p>This place opens in the 2014 client wearing what you have equipped.</p>
{% if user %}<form method="post"><button class="btn-medium btn-primary" style="width:120px">Play</button></form>{% else %}<p><a href="/newlogin?next=/play/{{ gid }}">Log in</a> to play.</p>{% endif %}
<p style="margin-top:14px"><a href="/client">First time? Set up the client</a></p></div>''', gid=gid)


@app.route('/client')
def client_page():
    return page('Get the client', '''<div class="box"><p><b>1.</b> <a href="/client/patch.zip">Download the client patch</a> and copy its files into your client folder (the one with RobloxPlayerBeta.exe).</p>
<p><b>2.</b> Run <b>install.bat</b> once. It lets the Play button open the client.</p>
<p><b>3.</b> Press Play on any uploaded .rbxl game. The patch points the client at this site automatically, even on wifi.</p></div>''')


@app.route('/client/patch.zip')
def client_patch():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        d = os.path.join(BASE, 'client_patch')
        for n in sorted(os.listdir(d)): z.write(os.path.join(d, n), n)
    return Response(buf.getvalue(), mimetype='application/zip', headers={'Content-Disposition': 'attachment; filename=client_patch.zip'})


@app.route('/<path:p>.ashx', methods=['GET', 'POST'])
def ashx_stub(p):                      # the client pings a few legacy endpoints (Negotiate, Visit, ClientPresence...); answer them quietly
    return ''


# ---------- reading .rbxl / .rbxlx places for the browser test client ----------
PART_CLASSES = ('Part', 'WedgePart', 'SpawnLocation', 'TrussPart', 'CornerWedgePart', 'MeshPart', 'Seat', 'VehicleSeat')
_ROT = {0x02: (1,0,0,0,1,0,0,0,1), 0x03: (1,0,0,0,0,-1,0,1,0), 0x05: (1,0,0,0,-1,0,0,0,-1), 0x06: (1,0,0,0,0,1,0,-1,0), 0x07: (0,1,0,1,0,0,0,0,-1), 0x09: (0,0,1,1,0,0,0,1,0),
        0x0a: (0,-1,0,1,0,0,0,0,1), 0x0c: (0,0,-1,1,0,0,0,-1,0), 0x0d: (0,1,0,0,0,1,1,0,0), 0x0e: (0,0,-1,0,1,0,1,0,0), 0x10: (0,-1,0,0,0,-1,1,0,0), 0x11: (0,0,1,0,-1,0,1,0,0),
        0x14: (-1,0,0,0,1,0,0,0,-1), 0x15: (-1,0,0,0,0,1,0,1,0), 0x17: (-1,0,0,0,-1,0,0,0,1), 0x18: (-1,0,0,0,0,-1,0,-1,0), 0x19: (0,1,0,-1,0,0,0,0,1), 0x1b: (0,0,-1,-1,0,0,0,1,0),
        0x1c: (0,-1,0,-1,0,0,0,0,-1), 0x1e: (0,0,1,-1,0,0,0,-1,0), 0x1f: (0,1,0,0,0,-1,-1,0,0), 0x20: (0,0,1,0,1,0,-1,0,0), 0x22: (0,-1,0,0,0,1,-1,0,0), 0x23: (0,0,-1,0,-1,0,-1,0,0)}


def _il(raw, n, off=0): return [int.from_bytes(bytes(raw[off + k * n + i] for k in range(4)), 'big') for i in range(n)]
def _zz(v): return (v >> 1) ^ -(v & 1)
def _delta(vals):
    out, acc = [], 0
    for v in vals: acc += _zz(v); out.append(acc)
    return out
def _fl(v): return struct.unpack('<f', struct.pack('<I', ((v >> 1) | (v << 31)) & 0xFFFFFFFF))[0]
def _fls(raw, n, off): return [_fl(v) for v in _il(raw, n, off)]


def _part_row(cf, size, col, tr_, collide):
    return [round(x, 3) for x in cf] + [round(x, 3) for x in size] + list(col) + [round(tr_, 3), 1 if collide else 0]


def place_bin(d):
    pos, cls_of, refs, props, parent = 32, {}, {}, {}, {}
    while pos + 16 <= len(d):
        name = d[pos:pos + 4]; clen, ulen = struct.unpack_from('<II', d, pos + 4); pos += 16
        n = clen or ulen; pl = d[pos:pos + n]; pos += n
        if clen: pl = lz4_block(pl)
        if name == b'INST':
            cid, ln = struct.unpack_from('<iI', pl, 0); cn = pl[8:8 + ln].decode('latin1'); cnt = struct.unpack_from('<i', pl, 9 + ln)[0]
            refs[cid] = (cn, _delta(_il(pl, cnt, 13 + ln)))
            for r in refs[cid][1]: cls_of[r] = cn
        elif name == b'PRNT':
            cnt = struct.unpack_from('<i', pl, 1)[0]; ch = _delta(_il(pl, cnt, 5)); pa = _delta(_il(pl, cnt, 5 + 4 * cnt)); parent.update(zip(ch, pa))
        elif name == b'PROP':
            cid, ln = struct.unpack_from('<iI', pl, 0); pn = pl[8:8 + ln].decode('latin1'); typ = pl[8 + ln]; raw = pl[9 + ln:]
            if cid not in refs or pn not in ('CFrame', 'size', 'Size', 'Color3uint8', 'Transparency', 'CanCollide'): continue
            n_ = len(refs[cid][1]); rs = refs[cid][1]; val = None
            try:
                if pn == 'CFrame' and typ == 0x10:
                    o, rots = 0, []
                    for _ in range(n_):
                        rid = raw[o]; o += 1
                        if rid == 0: rots.append(struct.unpack_from('<9f', raw, o)); o += 36
                        else: rots.append(_ROT.get(rid, _ROT[2]))
                    X, Y, Z = _fls(raw, n_, o), _fls(raw, n_, o + 4 * n_), _fls(raw, n_, o + 8 * n_)
                    val = [(X[i], Y[i], Z[i]) + tuple(rots[i]) for i in range(n_)]
                elif pn in ('size', 'Size') and typ == 0x0E: val = list(zip(_fls(raw, n_, 0), _fls(raw, n_, 4 * n_), _fls(raw, n_, 8 * n_)))
                elif pn == 'Color3uint8' and typ == 0x1A: val = list(zip(raw[:n_], raw[n_:2 * n_], raw[2 * n_:3 * n_]))
                elif pn == 'Transparency' and typ == 0x04: val = _fls(raw, n_, 0)
                elif pn == 'CanCollide' and typ == 0x02: val = list(raw[:n_])
            except Exception:
                val = None
            if val:
                for r, v in zip(rs, val): props.setdefault(r, {})[pn if pn != 'Size' else 'size'] = v
        elif name.startswith(b'END'): break
    def in_ws(r):
        for _ in range(60):
            if cls_of.get(r) == 'Workspace': return True
            r = parent.get(r, -1)
            if r == -1 or r not in cls_of and r not in parent: return False
        return False
    parts, spawn = [], None
    for r, c in cls_of.items():
        if c in PART_CLASSES and r in props and 'CFrame' in props[r] and in_ws(r):
            p = props[r]; cf = p['CFrame']; sz = p.get('size', (4, 1, 2))
            parts.append(_part_row(cf, sz, p.get('Color3uint8', (163, 162, 165)), (p.get('Transparency') or 0), p.get('CanCollide', 1)))
            if c == 'SpawnLocation' and not spawn: spawn = [round(cf[0], 2), round(cf[1] + sz[1] / 2, 2), round(cf[2], 2)]
    return parts, spawn


def place_xml(d):
    parts, spawn = [], None
    def val(props, name):
        for p in props:
            if p.get('name') == name: return p
    def walk(node, ws):
        nonlocal spawn
        for it in node.findall('Item'):
            c = it.get('class'); w = ws or c == 'Workspace'; props = it.find('Properties')
            if w and c in PART_CLASSES and props is not None:
                cf = val(props, 'CFrame'); sz = val(props, 'size') if val(props, 'size') is not None else val(props, 'Size')
                if cf is not None:
                    g = lambda k: float(cf.findtext(k) or 0)
                    row = [g('X'), g('Y'), g('Z')] + [g(k) for k in ('R00', 'R01', 'R02', 'R10', 'R11', 'R12', 'R20', 'R21', 'R22')]
                    size = [float(sz.findtext(k) or 1) for k in 'XYZ'] if sz is not None else [4, 1, 2]
                    c3 = val(props, 'Color3uint8'); col = (163, 162, 165)
                    if c3 is not None and (c3.text or '').strip().isdigit(): v = int(c3.text); col = ((v >> 16) & 255, (v >> 8) & 255, v & 255)
                    t = val(props, 'Transparency'); cc = val(props, 'CanCollide')
                    parts.append(_part_row(row, size, col, float(t.text) if t is not None and t.text else 0, not (cc is not None and (cc.text or '').strip() == 'false')))
                    if c == 'SpawnLocation' and not spawn: spawn = [round(row[0], 2), round(row[1] + size[1] / 2, 2), round(row[2], 2)]
            walk(it, w)
    walk(ET.fromstring(d), False)
    return parts, spawn


def read_place(data):
    try:
        parts, spawn = place_bin(data) if data[:8] == b'<roblox!' else place_xml(data)
    except Exception:
        parts, spawn = [], None
    return {'parts': parts[:20000], 'spawn': spawn, 'count': len(parts)}


def is_tester(u): return bool(u) and u['username'].lower() in [a.lower() for a in ADMINS]


TEST_PAGE = '''<!DOCTYPE html><html><head><meta charset="utf-8"><title>{{ title }} - ROBLOX test client</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;background:#9ec7ee;font-family:'Source Sans Pro','Segoe UI',Arial,sans-serif;user-select:none}
#gl{position:fixed;left:0;top:0;width:100%;height:100%;display:block}
#plist{position:fixed;right:0;top:0;width:150px;text-align:right}
#me{font:700 22px/26px 'Source Sans Pro',Arial;color:#fff;text-shadow:0 0 3px #000,1px 1px 0 #000;padding:2px 8px 4px}
.row{margin:2px 0;padding:2px 8px;background:rgba(120,120,120,.7);color:#fff;font-size:12px;font-weight:600;text-align:left;border:1px solid rgba(255,255,255,.12)}
#hot{position:fixed;left:50%;bottom:42px;transform:translateX(-50%);text-align:center}
#slots{display:flex;gap:2px;justify-content:center;min-height:42px}
.slot{width:42px;height:42px;background:rgba(30,30,30,.7);border:1px solid #777;color:#fff;font-size:10px;display:none;padding:2px;box-sizing:border-box;overflow:hidden}
#hpbar{width:140px;height:8px;margin:6px auto 0;background:#222;border:1px solid #444}#hp{height:100%;width:100%;background:#4ad92b;transition:width .2s}
#bottom{position:fixed;left:0;right:0;bottom:0;height:24px;background:rgba(10,10,10,.85);color:#ddd;font-size:12px;line-height:24px}
#chat{background:transparent;border:0;outline:0;color:#fff;width:70%;padding-left:6px;font-size:12px}#chat::placeholder{color:#ddd}
#menubtn{position:fixed;left:6px;bottom:34px;width:32px;height:28px;cursor:pointer;background:linear-gradient(#fff 0 3px,transparent 3px 8px,#fff 8px 11px,transparent 11px 16px,#fff 16px 19px,transparent 19px)}
#log{position:fixed;left:8px;top:8px;width:340px;color:#fff;font-size:13px;text-shadow:1px 1px 0 #000}#log div{transition:opacity .8s;margin:2px 0}
#menu{display:none;position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);width:250px;padding:12px 14px 14px;background:rgba(25,25,25,.72);border-radius:4px;text-align:center;color:#fff;z-index:5}
#menu h3{margin:0 0 8px;font:700 19px 'Source Sans Pro',Arial}
.mb{display:block;width:100%;margin:6px 0;padding:7px 0;background:rgba(150,150,150,.55);border:1px solid rgba(255,255,255,.4);color:#fff;font:600 14px 'Source Sans Pro',Arial;cursor:pointer}
.mb:hover{background:rgba(190,190,190,.65)}.mb.blue{background:#4a85e0;border-color:#8db5f2}.two{display:flex;gap:8px}.two .mb{flex:1}
#panel{display:none;margin-top:8px;padding:8px;background:rgba(0,0,0,.35);font-size:13px;text-align:left}
#toast{display:none;position:fixed;left:50%;top:70px;transform:translateX(-50%);background:rgba(0,0,0,.8);color:#fff;padding:8px 14px;font-size:13px}
#note{position:fixed;left:50%;bottom:70px;transform:translateX(-50%);color:#fff;text-shadow:1px 1px 0 #000;font-size:13px}
#fps{display:none;position:fixed;left:8px;bottom:70px;color:#fff;font-size:12px;text-shadow:1px 1px 0 #000}
</style></head><body>
<canvas id="gl"></canvas>
<div id="plist"><div id="me"></div></div><div id="plist2"></div>
<div id="hot"><div id="slots"><div class="slot" id="slot1"></div></div><div id="hpbar"><div id="hp"></div></div></div>
<div id="menubtn"></div><div id="log"></div><div id="note"></div><div id="fps"></div><div id="toast"></div>
<div id="bottom"><input id="chat" placeholder='To chat click here or press "/" key' autocomplete="off"></div>
<div id="menu"><h3>Game Menu</h3><button class="mb blue" id="resume">Resume Game</button><button class="mb" id="reset">Reset Character</button><button class="mb" id="settings">Game Settings</button>
<div class="two"><button class="mb" id="help">Help</button><button class="mb" id="shot">Screenshot</button></div>
<div class="two"><button class="mb" id="abuse">Report Abuse</button><button class="mb" id="video">Record Video</button></div>
<button class="mb" id="leave">Leave Game</button><div id="panel"></div></div>
<script>window.G = {{ cfg|tojson }};</script><script src="/static/js/rbx3d.js"></script><script src="/static/js/game.js"></script>
</body></html>'''


@app.route('/test/<int:gid>')
@login_required
def test_client(gid):
    u = cur_user()
    if not is_tester(u): abort(403)
    g_ = db().one('select * from games where id=?', (gid,)) or abort(404)
    db().x('update games set visits=coalesce(visits,0)+1 where id=?', (gid,)); db().commit()
    tool = db().one("select i.name from equipped e join items i on i.id=e.iid where e.uid=? and i.kind='tool'", (u['id'],))
    cfg = dict(user=u['username'], title=g_['title'], place='/test/%d/place.json' % gid, back='/game/%d' % gid, eq=eq_list(u['id']), tool=tool['name'] if tool else '')
    return rts(TEST_PAGE, cfg=cfg, title=g_['title'])


@app.route('/test/<int:gid>/place.json')
@login_required
def test_place(gid):
    if not is_tester(cur_user()): abort(403)
    g_ = db().one('select * from games where id=?', (gid,)) or abort(404)
    b = db().one('select data from blobs where name=?', (g_['file'],))
    return jsonify(read_place(bytes(b['data']))) if b and g_['file'].endswith(('.rbxl', '.rbxlx')) else jsonify(parts=[], spawn=None, count=0)


# ---------- backups: every start keeps a copy of the database; admins can restore one ----------
def backup_now():
    f = os.path.join(DATA, 'rbx2014.db')
    if PG or not os.path.exists(f): return
    bd = os.path.join(DATA, 'backups'); os.makedirs(bd, exist_ok=True)
    old = sorted(os.listdir(bd))
    if old and time.time() - os.path.getmtime(os.path.join(bd, old[-1])) < 3600: return
    shutil.copy2(f, os.path.join(bd, 'rbx2014_%s.db' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S')))
    for n in sorted(os.listdir(bd))[:-20]: os.remove(os.path.join(bd, n))


backup_now()


@app.route('/admin/restore', methods=['GET', 'POST'])
@admin_required
def admin_restore():
    msg = None
    if PG: msg = 'This site uses a Postgres database, which keeps its own data. Nothing to restore here.'
    elif request.method == 'POST':
        f = request.files.get('db'); data = f.read() if f else b''
        if data[:16] != b'SQLite format 3\x00': msg = 'That is not a rbx2014.db file.'
        else:
            backup_now(); cur = os.path.join(DATA, 'rbx2014.db')
            shutil.copy2(cur, os.path.join(DATA, 'backups', 'before_restore_%s.db' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S')))
            open(cur, 'wb').write(data); init(); msg = 'Restored. All accounts, items, games and posts from that file are back (and upgraded to this version).'
    return page('Restore data', '''{% if msg %}<div class="box" style="width:520px">{{ msg }}</div>{% endif %}
<div class="box" style="width:520px"><p>Pick the <b>rbx2014.db</b> file from an older version's <b>data</b> folder (or from <b>{{ data }}</b>\\backups). It replaces the current data; a copy of the current data is kept in the backups folder first.</p>
<form method="post" enctype="multipart/form-data"><input type="file" name="db"><button class="btn-medium btn-neutral" style="width:140px">Restore</button></form></div>''', msg=msg, data=DATA)


# ---------- game page like the real one ----------
@app.route('/game/<int:gid>')
def game_db(gid):
    r = db().one('select g.*, u.username, u.joined as ujoined from games g join users u on u.id=g.uid where g.id=?', (gid,)) or abort(404)
    return page(r['title'], '''<div style="display:flex;gap:26px;align-items:flex-start">
<div style="width:500px"><div style="height:280px;background:{{ '#9ab' if not r.thumb else 'url(/files/' + r.thumb + ') center/cover' }}"></div></div>
<div style="width:300px"><p style="font-size:17px"><b>Builder:</b> <a href="/user/{{ r.username }}"><b>{{ r.username }}</b></a><br><span style="font-size:12px"><b>Joined:</b> {{ r.ujoined }}</span></p>
<hr style="border:0;border-top:1px solid #ccc">
<a class="btn-medium btn-primary" href="/play/{{ r.id }}" style="width:100%;height:38px;line-height:38px;font-size:24px;margin:14px 0">Play</a>
{% if tester %}<a class="btn-small btn-neutral" href="/test/{{ r.id }}" style="display:block;text-align:center;margin-bottom:12px">Play in browser (test client)</a>{% endif %}
<p style="font-size:12px;line-height:19px"><b>Created:</b> {{ r.created }}<br><b>Visited:</b> {{ r.visits or 0 }}<br><b>Genres:</b> <a href="/genre/{{ r.genre }}">{{ r.genre }}</a></p>
<p style="font-size:12px"><a href="/files/{{ r.file }}" download>Download file</a></p></div></div>
<p style="margin-top:18px;white-space:pre-wrap">{{ r.descr }}</p>
{% if user and (user.admin or user.id == r.uid) %}<form method="post" action="/game/{{ r.id }}/delete"><button class="btn-small" style="background:#a00;border:0">Delete game</button></form>{% endif %}''', r=r, tester=is_tester(cur_user()))


@app.errorhandler(403)
def forbidden(_): return page('Not allowed', '<div class="box"><p>You do not have permission to do that.</p></div>'), 403


@app.errorhandler(404)
def nf(_): return page('Page not found', '<div class="box"><p>That page does not exist. <a href="/home">Go home</a>.</p></div>'), 404


if __name__ == '__main__':
    ip = '127.0.0.1'
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('10.255.255.255', 1)); ip = s.getsockname()[0]; s.close()
    except OSError:
        pass
    port = int(os.environ.get('PORT', 8080))
    print('\n  Your data is saved in: %s' % DATA)
    print('\n  ROBLOX 2014 server running\n  This PC:       http://localhost:%d\n  Other devices: http://%s:%d  (same wifi)\n' % (port, ip, port))
    app.run(host='0.0.0.0', port=port)
