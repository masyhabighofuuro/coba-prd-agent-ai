"""Aplikasi Pencatatan Barang Masuk & Keluar Merchandise.

Jalankan dengan: python app.py
Tabel dibuat dan data seed dimuat otomatis bila database masih kosong.
"""
import os
import sqlite3
import secrets
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Flask, g, redirect, render_template, request, session,
    url_for, flash, abort,
)
from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Lokasi file SQLite bisa dioverride lewat env (dipakai Docker volume).
DB_PATH = os.environ.get("DB_PATH") or os.path.join(BASE_DIR, "app.db")
WIB = timezone(timedelta(hours=7))

# Kredensial akun bersama. Diambil dari environment variable.
APP_USERNAME = os.environ.get("APP_USERNAME", "admin")

# Password default disimpan sebagai HASH (bukan teks biasa).
DEFAULT_PASSWORD_HASH = (
    "pbkdf2:sha256:1000000$8MrbMAtcJtdkeylw"
    "$9a350ffa250ccc846c6d648946d155566508f0475c25d3000378b929dc4f9e75"
)
# Bila APP_PASSWORD diisi (teks biasa lewat env), hash dibuat saat runtime.
_env_password = os.environ.get("APP_PASSWORD")
APP_PASSWORD_HASH = (
    generate_password_hash(_env_password) if _env_password else DEFAULT_PASSWORD_HASH
)

SESSION_HOURS = 8
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 5 * 60

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_HOURS),
    SESSION_REFRESH_EACH_REQUEST=True,
    WTF_CSRF_TIME_LIMIT=None,
)
csrf = CSRFProtect(app)

if not os.environ.get("SECRET_KEY"):
    app.logger.warning(
        "SECRET_KEY tidak diisi, memakai kunci acak sementara (sesi hilang saat restart). "
        "Set environment variable SECRET_KEY untuk produksi."
    )

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    nama TEXT NOT NULL,
    kategori TEXT NOT NULL,
    varian TEXT,
    satuan TEXT NOT NULL,
    stok INTEGER NOT NULL DEFAULT 0,
    stok_min INTEGER NOT NULL DEFAULT 0,
    harga INTEGER,
    catatan TEXT,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    jenis TEXT NOT NULL CHECK (jenis IN ('IN', 'OUT')),
    jumlah INTEGER NOT NULL,
    tanggal TEXT NOT NULL,
    pengirim TEXT,
    penerima TEXT,
    penjual TEXT,
    dicatat_oleh TEXT NOT NULL,
    catatan TEXT,
    created_at TEXT NOT NULL,
    reversal_of INTEGER,
    opname_id INTEGER,
    FOREIGN KEY (item_id) REFERENCES items (id)
);

CREATE TABLE IF NOT EXISTS stock_opnames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tanggal TEXT NOT NULL,
    petugas TEXT NOT NULL,
    catatan TEXT
);

CREATE TABLE IF NOT EXISTS stock_opname_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opname_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    stok_sistem INTEGER NOT NULL,
    stok_fisik INTEGER NOT NULL,
    selisih INTEGER NOT NULL,
    keterangan TEXT,
    FOREIGN KEY (opname_id) REFERENCES stock_opnames (id),
    FOREIGN KEY (item_id) REFERENCES items (id)
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_wib():
    return datetime.now(WIB)


def now_str():
    return now_wib().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return now_wib().strftime("%Y-%m-%d")


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    # Migrasi ringan untuk database lama (tanpa kolom pembatalan/opname).
    cols = {r[1] for r in db.execute("PRAGMA table_info(transactions)")}
    for col in ("reversal_of", "opname_id"):
        if col not in cols:
            db.execute(f"ALTER TABLE transactions ADD COLUMN {col} INTEGER")
    # Satu transaksi hanya boleh dibatalkan satu kali (aman walau diklik bersamaan).
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_trans_reversal "
        "ON transactions (reversal_of) WHERE reversal_of IS NOT NULL"
    )
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------
SEED_ITEMS = [
    # sku, nama, kategori, varian, satuan, stok_awal, stok_min, harga
    ("KOS-001", "Kaos Polos Katun", "Pakaian", "Hitam / L", "pcs", 120, 20, 65000),
    ("KOS-002", "Kaos Polos Katun", "Pakaian", "Putih / M", "pcs", 90, 20, 65000),
    ("HOD-001", "Hoodie Fleece", "Pakaian", "Navy / L", "pcs", 60, 15, 175000),
    ("HOD-002", "Hoodie Fleece", "Pakaian", "Abu / XL", "pcs", 45, 15, 175000),
    ("TOP-001", "Topi Baseball", "Aksesoris", "-", "pcs", 80, 15, 55000),
    ("TOT-001", "Tote Bag Kanvas", "Aksesoris", "Natural", "pcs", 70, 15, 45000),
    ("TUM-001", "Tumbler Stainless", "Minuman", "500 ml", "pcs", 55, 10, 85000),
    ("MUG-001", "Mug Keramik", "Minuman", "Putih", "pcs", 100, 20, 35000),
    ("STK-001", "Stiker Pack", "Aksesoris", "Pack A", "pack", 200, 50, 15000),
    ("PIN-001", "Pin Enamel", "Aksesoris", "Logo", "pcs", 150, 40, 20000),
    ("LAN-001", "Lanyard", "Aksesoris", "Polos", "pcs", 130, 30, 25000),
    ("NOT-001", "Notebook A5", "Alat Tulis", "Garis", "pcs", 90, 25, 30000),
]

# sku, jenis, jumlah, days_ago, pengirim, penerima, penjual, dicatat_oleh, catatan
SEED_TRANSACTIONS = [
    ("KOS-001", "IN", 50, 28, "PT Kain Nusantara", "Gudang Pusat", "", "Budi Santoso", "Restock kaos hitam."),
    ("MUG-001", "IN", 60, 26, "CV Keramik Jaya", "Gudang Pusat", "", "Siti Aminah", "Kedatangan mug pesanan."),
    ("HOD-001", "IN", 25, 24, "PT Sandang Makmur", "Gudang Pusat", "", "Budi Santoso", "Restock hoodie navy."),
    ("STK-001", "IN", 100, 22, "Percetakan Cahaya", "Gudang Pusat", "", "Andi Wijaya", "Cetak stiker batch baru."),
    ("TUM-001", "IN", 30, 20, "PT Stainless Indo", "Gudang Pusat", "", "Dewi Lestari", "Restock tumbler."),
    ("LAN-001", "IN", 80, 18, "Percetakan Cahaya", "Gudang Pusat", "", "Rizky Pratama", "Lanyard event."),
    ("NOT-001", "IN", 50, 16, "PT Kertas Prima", "Gudang Pusat", "", "Siti Aminah", "Notebook tambahan."),
    ("TOP-001", "IN", 40, 14, "PT Sandang Makmur", "Gudang Pusat", "", "Budi Santoso", "Restock topi."),
    ("KOS-001", "OUT", 30, 25, "Gudang Pusat", "Koperasi Karyawan", "Rizky Pratama", "Andi Wijaya", "Penjualan koperasi."),
    ("KOS-002", "OUT", 40, 21, "Gudang Pusat", "Toko Online", "Maya Sari", "Siti Aminah", "Pesanan marketplace."),
    ("HOD-001", "OUT", 15, 19, "Gudang Pusat", "Event Kampus", "Fajar Nugroho", "Budi Santoso", "Bazar kampus."),
    ("STK-001", "OUT", 130, 17, "Gudang Pusat", "Stand Bazar", "Maya Sari", "Dewi Lestari", "Stiker souvenir bazar."),
    ("TUM-001", "OUT", 25, 12, "Gudang Pusat", "Toko Online", "Maya Sari", "Putri Ramadhani", "Pesanan online."),
    ("PIN-001", "OUT", 70, 11, "Gudang Pusat", "Stand Bazar", "Fajar Nugroho", "Nurul Hidayah", "Pin untuk bazar."),
    ("STK-001", "OUT", 120, 10, "Gudang Pusat", "Koperasi Karyawan", "Rizky Pratama", "Andi Wijaya", "Setoran koperasi."),
    ("MUG-001", "OUT", 35, 9, "Gudang Pusat", "Koperasi Karyawan", "Rizky Pratama", "Siti Aminah", "Penjualan koperasi."),
    ("TOT-001", "OUT", 20, 8, "Gudang Pusat", "Toko Online", "Maya Sari", "Putri Ramadhani", "Pesanan marketplace."),
    ("PIN-001", "OUT", 45, 6, "Gudang Pusat", "Event Kampus", "Maya Sari", "Agus Salim", "Souvenir event."),
    ("TOP-001", "OUT", 30, 5, "Gudang Pusat", "Stand Bazar", "Fajar Nugroho", "Nurul Hidayah", "Topi bazar."),
    ("LAN-001", "OUT", 40, 4, "Gudang Pusat", "Event Kampus", "Maya Sari", "Agus Salim", "Lanyard peserta."),
    ("HOD-002", "OUT", 10, 3, "Gudang Pusat", "Toko Online", "Rizky Pratama", "Budi Santoso", "Pesanan online."),
    ("NOT-001", "OUT", 15, 2, "Gudang Pusat", "Koperasi Karyawan", "Maya Sari", "Siti Aminah", "Notebook koperasi."),
]

# tanggal_days_ago, petugas, catatan, [(sku, sistem, fisik, keterangan)]
SEED_OPNAMES = [
    (
        20,
        "Siti Aminah",
        "Opname rutin bulanan gudang pusat.",
        [
            ("MUG-001", 110, 111, "Kelebihan 1 pcs, retur belum tercatat."),
            ("STK-001", 210, 208, "Kurang 2 pack, kemungkinan salah hitung saat bazar."),
        ],
    ),
    (
        14,
        "Budi Santoso",
        "Opname gudang depan menjelang pengiriman besar.",
        [
            ("TUM-001", 55, 53, "Dua tumbler rusak dan tidak layak jual."),
            ("KOS-001", 135, 136, "Satu kaos pengembalian belum dicatat."),
        ],
    ),
    (
        8,
        "Dewi Lestari",
        "Opname menjelang event gathering.",
        [
            ("PIN-001", 62, 60, "Dua pin hilang saat pemasangan stand."),
            ("TOT-001", 55, 56, "Satu tote bag bonus belum tercatat."),
            ("STK-001", 70, 68, "Dua pack stiker rusak dan dibuang."),
        ],
    ),
]


def seed_db():
    """Isi database hanya bila masih kosong."""
    db = get_db()
    count = db.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
    if count:
        return

    # Hitung stok akhir = stok_awal + total IN - total OUT agar konsisten.
    net = {}
    for sku, jenis, jumlah, *_ in SEED_TRANSACTIONS:
        net[sku] = net.get(sku, 0) + (jumlah if jenis == "IN" else -jumlah)

    item_id = {}
    for sku, nama, kategori, varian, satuan, stok_awal, stok_min, harga in SEED_ITEMS:
        stok_akhir = stok_awal + net.get(sku, 0)
        if stok_akhir < 0:
            raise RuntimeError(f"Seed tidak konsisten: stok {sku} negatif")
        cur = db.execute(
            """INSERT INTO items
               (sku, nama, kategori, varian, satuan, stok, stok_min, harga, catatan,
                is_deleted, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (sku, nama, kategori, varian, satuan, stok_akhir, stok_min, harga,
             None, now_str(), now_str()),
        )
        item_id[sku] = cur.lastrowid

    today = now_wib()
    for sku, jenis, jumlah, days_ago, pengirim, penerima, penjual, dicatat, catatan in SEED_TRANSACTIONS:
        tanggal = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        created = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            """INSERT INTO transactions
               (item_id, jenis, jumlah, tanggal, pengirim, penerima, penjual,
                dicatat_oleh, catatan, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id[sku], jenis, jumlah, tanggal, pengirim, penerima,
             penjual or None, dicatat, catatan, created),
        )

    for days_ago, petugas, catatan, rows in SEED_OPNAMES:
        tanggal = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        cur = db.execute(
            "INSERT INTO stock_opnames (tanggal, petugas, catatan) VALUES (?, ?, ?)",
            (tanggal, petugas, catatan),
        )
        opname_id = cur.lastrowid
        for sku, sistem, fisik, keterangan in rows:
            db.execute(
                """INSERT INTO stock_opname_items
                   (opname_id, item_id, stok_sistem, stok_fisik, selisih, keterangan)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (opname_id, item_id[sku], sistem, fisik, fisik - sistem, keterangan),
            )

    db.commit()


# ---------------------------------------------------------------------------
# Proteksi login & gerbang modal stock opname
# ---------------------------------------------------------------------------
PUBLIC_ENDPOINTS = {"login", "static"}

# Statistik percobaan login (in-memory, cukup untuk server pengembangan).
_login_attempts = {}
_login_lock = threading.Lock()


def _client_key():
    return request.remote_addr or "unknown"


def _check_lockout():
    with _login_lock:
        entry = _login_attempts.get(_client_key())
        if not entry:
            return 0
        locked_until, _count = entry
        remaining = int((locked_until - now_wib().timestamp()))
        return max(0, remaining)


def _record_failure():
    with _login_lock:
        key = _client_key()
        locked_until, count = _login_attempts.get(key, (0, 0))
        count += 1
        if count >= MAX_LOGIN_ATTEMPTS:
            locked_until = now_wib().timestamp() + LOCKOUT_SECONDS
            count = 0
        _login_attempts[key] = (locked_until, count)


def _clear_failures():
    with _login_lock:
        _login_attempts.pop(_client_key(), None)


@app.before_request
def guard():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if request.endpoint is None:
        return None
    if not session.get("user"):
        return redirect(url_for("login", next=request.path))
    # Gerbang modal stock opname: sampai dikonfirmasi, hanya halaman utama.
    if not session.get("opname_ack"):
        allowed = {"index", "ack_opname", "logout"}
        if request.endpoint not in allowed:
            return redirect(url_for("index"))
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Filter template
# ---------------------------------------------------------------------------
@app.template_filter("tgl")
def fmt_tanggal(value):
    """Ubah 'YYYY-MM-DD' menjadi 'dd-mm-yyyy'."""
    if not value:
        return "-"
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        return value


@app.template_filter("tglwaktu")
def fmt_tanggal_waktu(value):
    if not value:
        return "-"
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S").strftime("%d-%m-%Y %H:%M")
    except ValueError:
        return value


@app.template_filter("rupiah")
def fmt_rupiah(value):
    if value in (None, ""):
        return "-"
    return "Rp " + f"{int(value):,}".replace(",", ".")


@app.template_filter("angka")
def fmt_angka(value):
    if value in (None, ""):
        return "-"
    return f"{int(value):,}".replace(",", ".")


# ---------------------------------------------------------------------------
# Util
# ---------------------------------------------------------------------------
def parse_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def row_to_dict(row):
    return {k: row[k] for k in row.keys()}


def form_to_dict(form):
    keys = ["sku", "nama", "kategori", "varian", "satuan",
            "stok_awal", "stok_min", "harga", "catatan"]
    return {k: form.get(k, "") for k in keys}


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


def latest_opname():
    """Ambil stock opname terakhir beserta ringkasan dan item selisih."""
    db = get_db()
    op = db.execute(
        "SELECT * FROM stock_opnames ORDER BY tanggal DESC, id DESC LIMIT 1"
    ).fetchone()
    if not op:
        return None
    rows = db.execute(
        """SELECT soi.*, i.nama, i.sku, i.satuan
           FROM stock_opname_items soi
           JOIN items i ON i.id = soi.item_id
           WHERE soi.opname_id = ?
           ORDER BY ABS(soi.selisih) DESC, i.nama""",
        (op["id"],),
    ).fetchall()
    total = len(rows)
    selisih = [r for r in rows if r["selisih"] != 0]
    return {
        "opname": op,
        "total_item": total,
        "jumlah_selisih": len(selisih),
        "rows": selisih,
    }


def kategori_list():
    db = get_db()
    rows = db.execute(
        "SELECT DISTINCT kategori FROM items WHERE is_deleted = 0 ORDER BY kategori"
    ).fetchall()
    return [r["kategori"] for r in rows]


def active_items():
    db = get_db()
    return db.execute(
        "SELECT * FROM items WHERE is_deleted = 0 ORDER BY nama, varian"
    ).fetchall()


# ---------------------------------------------------------------------------
# Autentikasi
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("index"))

    if request.method == "POST":
        remaining = _check_lockout()
        if remaining > 0:
            menit = max(1, remaining // 60)
            flash(f"Terlalu banyak percobaan gagal. Coba lagi dalam {menit} menit.", "danger")
            return render_template("login.html"), 429

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if username == APP_USERNAME and check_password_hash(APP_PASSWORD_HASH, password):
            _clear_failures()
            session.clear()
            session.permanent = True
            session["user"] = username
            session["opname_ack"] = False
            target = safe_next(request.args.get("next") or request.form.get("next"))
            return redirect(target or url_for("index"))

        _record_failure()
        flash("Username atau password salah", "danger")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("Anda telah keluar.", "info")
    return redirect(url_for("login"))


@app.route("/opname/ack", methods=["POST"])
@login_required
def ack_opname():
    session["opname_ack"] = True
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Halaman utama
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def index():
    db = get_db()
    total_item = db.execute(
        "SELECT COUNT(*) AS c FROM items WHERE is_deleted = 0"
    ).fetchone()["c"]
    low_stock = db.execute(
        "SELECT COUNT(*) AS c FROM items WHERE is_deleted = 0 AND stok <= stok_min"
    ).fetchone()["c"]
    total_stok = db.execute(
        "SELECT COALESCE(SUM(stok), 0) AS c FROM items WHERE is_deleted = 0"
    ).fetchone()["c"]
    recent = db.execute(
        """SELECT t.*, i.nama AS item_nama, i.sku AS item_sku, i.satuan AS item_satuan
           FROM transactions t JOIN items i ON i.id = t.item_id
           ORDER BY t.tanggal DESC, t.id DESC LIMIT 8"""
    ).fetchall()
    low_items = db.execute(
        """SELECT * FROM items WHERE is_deleted = 0 AND stok <= stok_min
           ORDER BY stok - stok_min LIMIT 5"""
    ).fetchall()
    show_modal = not session.get("opname_ack")
    summary = latest_opname() if show_modal else None
    return render_template(
        "index.html",
        total_item=total_item,
        low_stock=low_stock,
        total_stok=total_stok,
        recent=recent,
        low_items=low_items,
        summary=summary,
        show_modal=show_modal,
    )


# ---------------------------------------------------------------------------
# Barang
# ---------------------------------------------------------------------------
@app.route("/items")
@login_required
def items_list():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    kategori = (request.args.get("kategori") or "").strip()
    sort = request.args.get("sort") or "nama"
    order = (request.args.get("order") or "asc").lower()
    if order not in ("asc", "desc"):
        order = "asc"
    sortable = {
        "sku": "sku", "nama": "nama", "kategori": "kategori",
        "varian": "varian", "stok": "stok",
    }
    sort_col = sortable.get(sort, "nama")

    where = ["is_deleted = 0"]
    params = []
    if q:
        where.append("(nama LIKE ? OR sku LIKE ? OR kategori LIKE ? OR varian LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    if kategori:
        where.append("kategori = ?")
        params.append(kategori)

    sql = (
        "SELECT * FROM items WHERE " + " AND ".join(where)
        + f" ORDER BY {sort_col} {order.upper()}"
    )
    items = db.execute(sql, params).fetchall()
    return render_template(
        "items.html",
        items=items,
        q=q,
        kategori=kategori,
        kategori_opsi=kategori_list(),
        sort=sort,
        order=order,
    )


@app.route("/items/new", methods=["GET", "POST"])
@login_required
def item_new():
    if request.method == "POST":
        form = request.form
        data, errors = validate_item(form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("item_form.html", item=form_to_dict(form),
                                   kategori_opsi=kategori_list(), mode="new")

        db = get_db()
        db.execute(
            """INSERT INTO items
               (sku, nama, kategori, varian, satuan, stok, stok_min, harga,
                catatan, is_deleted, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (data["sku"], data["nama"], data["kategori"], data["varian"],
             data["satuan"], data["stok"], data["stok_min"], data["harga"],
             data["catatan"], now_str(), now_str()),
        )
        db.commit()
        flash(f"Barang '{data['nama']}' berhasil ditambahkan.", "success")
        return redirect(url_for("items_list"))

    return render_template("item_form.html", item={},
                           kategori_opsi=kategori_list(), mode="new")


@app.route("/items/<int:item_id>")
@login_required
def item_detail(item_id):
    db = get_db()
    item = db.execute(
        "SELECT * FROM items WHERE id = ? AND is_deleted = 0", (item_id,)
    ).fetchone()
    if not item:
        abort(404)
    history = db.execute(
        """SELECT t.*, v.id AS voided_by FROM transactions t
           LEFT JOIN transactions v ON v.reversal_of = t.id
           WHERE t.item_id = ?
           ORDER BY t.tanggal DESC, t.id DESC""",
        (item_id,),
    ).fetchall()
    return render_template("item_detail.html", item=item, history=history)


@app.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def item_edit(item_id):
    db = get_db()
    item = db.execute(
        "SELECT * FROM items WHERE id = ? AND is_deleted = 0", (item_id,)
    ).fetchone()
    if not item:
        abort(404)

    if request.method == "POST":
        form = request.form
        data, errors = validate_item(form, for_edit=True, item_id=item_id)
        if errors:
            for e in errors:
                flash(e, "danger")
            merged = row_to_dict(item)
            merged.update(form_to_dict(form))
            return render_template("item_form.html", item=merged,
                                   kategori_opsi=kategori_list(), mode="edit")

        db.execute(
            """UPDATE items SET sku = ?, nama = ?, kategori = ?, varian = ?,
               satuan = ?, stok_min = ?, harga = ?, catatan = ?, updated_at = ?
               WHERE id = ?""",
            (data["sku"], data["nama"], data["kategori"], data["varian"],
             data["satuan"], data["stok_min"], data["harga"], data["catatan"],
             now_str(), item_id),
        )
        db.commit()
        flash(f"Barang '{data['nama']}' berhasil diperbarui.", "success")
        return redirect(url_for("item_detail", item_id=item_id))

    return render_template("item_form.html", item=row_to_dict(item),
                           kategori_opsi=kategori_list(), mode="edit")


@app.route("/items/<int:item_id>/delete", methods=["POST"])
@login_required
def item_delete(item_id):
    db = get_db()
    item = db.execute(
        "SELECT * FROM items WHERE id = ? AND is_deleted = 0", (item_id,)
    ).fetchone()
    if not item:
        abort(404)
    db.execute(
        "UPDATE items SET is_deleted = 1, updated_at = ? WHERE id = ?",
        (now_str(), item_id),
    )
    db.commit()
    flash(f"Barang '{item['nama']}' telah dihapus.", "success")
    return redirect(url_for("items_list"))


def validate_item(form, for_edit=False, item_id=None):
    errors = []
    sku = (form.get("sku") or "").strip()
    nama = (form.get("nama") or "").strip()
    kategori = (form.get("kategori") or "").strip()
    varian = (form.get("varian") or "").strip() or None
    satuan = (form.get("satuan") or "").strip()
    stok_min = parse_int(form.get("stok_min"))
    harga_raw = (form.get("harga") or "").strip()
    catatan = (form.get("catatan") or "").strip() or None

    if not sku:
        errors.append("Kode barang (SKU) wajib diisi.")
    if not nama:
        errors.append("Nama barang wajib diisi.")
    if not kategori:
        errors.append("Kategori wajib diisi.")
    if not satuan:
        errors.append("Satuan wajib diisi.")
    if stok_min is None or stok_min < 0:
        errors.append("Stok minimum harus berupa angka 0 atau lebih.")

    harga = None
    if harga_raw:
        harga = parse_int(harga_raw)
        if harga is None or harga < 0:
            errors.append("Harga jual harus berupa angka 0 atau lebih.")

    stok = None
    if not for_edit:
        stok = parse_int(form.get("stok_awal"), 0)
        if stok is None or stok < 0:
            errors.append("Stok awal harus berupa angka 0 atau lebih.")
            stok = 0

    db = get_db()
    if sku:
        if for_edit:
            dup = db.execute(
                "SELECT id FROM items WHERE sku = ? AND id != ?", (sku, item_id)
            ).fetchone()
        else:
            dup = db.execute("SELECT id FROM items WHERE sku = ?", (sku,)).fetchone()
        if dup:
            errors.append(f"Kode barang '{sku}' sudah dipakai.")

    data = {
        "sku": sku, "nama": nama, "kategori": kategori, "varian": varian,
        "satuan": satuan, "stok_min": stok_min if stok_min is not None else 0,
        "harga": harga, "catatan": catatan,
    }
    if not for_edit:
        data["stok"] = stok if stok is not None else 0
    return data, errors


# ---------------------------------------------------------------------------
# Transaksi
# ---------------------------------------------------------------------------
def _render_transaction(jenis):
    db = get_db()
    items = active_items()
    preselect = parse_int(request.args.get("item_id"))
    return render_template(
        "transaction_form.html",
        jenis=jenis,
        items=items,
        today=today_str(),
        preselect=preselect,
    )


@app.route("/transactions/in", methods=["GET", "POST"])
@login_required
def trans_in():
    if request.method == "POST":
        return _save_transaction("IN")
    return _render_transaction("IN")


@app.route("/transactions/out", methods=["GET", "POST"])
@login_required
def trans_out():
    if request.method == "POST":
        return _save_transaction("OUT")
    return _render_transaction("OUT")


def _save_transaction(jenis):
    db = get_db()
    form = request.form
    item_id = parse_int(form.get("item_id"))
    jumlah = parse_int(form.get("jumlah"))
    tanggal = (form.get("tanggal") or "").strip()
    pengirim = (form.get("pengirim") or "").strip()
    penerima = (form.get("penerima") or "").strip()
    penjual = (form.get("penjual") or "").strip()
    dicatat_oleh = (form.get("dicatat_oleh") or "").strip()
    catatan = (form.get("catatan") or "").strip() or None

    errors = []
    item = None
    if item_id:
        item = db.execute(
            "SELECT * FROM items WHERE id = ? AND is_deleted = 0", (item_id,)
        ).fetchone()
    if not item:
        errors.append("Barang wajib dipilih.")
    if jenis == "OUT" and not penjual:
        errors.append("Nama penjual wajib diisi untuk barang keluar.")
    if jumlah is None or jumlah <= 0:
        errors.append("Jumlah harus berupa angka lebih dari 0.")
    if not tanggal:
        errors.append("Tanggal wajib diisi.")
    elif not valid_date(tanggal):
        errors.append("Format tanggal tidak valid.")
    if not pengirim:
        errors.append("Nama pengirim wajib diisi.")
    if not penerima:
        errors.append("Nama penerima wajib diisi.")
    if not dicatat_oleh:
        errors.append("Nama pencatat wajib diisi.")

    if not errors and item:
        # Stok diubah dalam 1 statement SQL (cek + ubah sekaligus), sehingga dua
        # input bersamaan tidak bisa sama-sama lolos dan membuat stok negatif.
        if not apply_stock_change(db, item_id, jenis, jumlah):
            fresh = db.execute(
                "SELECT stok, satuan FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            errors.append(
                f"Stok tidak cukup. Stok tersedia {fresh['stok']} {fresh['satuan']}, "
                f"diminta {jumlah}."
            )

    if errors:
        for e in errors:
            flash(e, "danger")
        return render_template(
            "transaction_form.html",
            jenis=jenis,
            items=active_items(),
            today=today_str(),
            preselect=item_id,
            form=form,
        )

    db.execute(
        """INSERT INTO transactions
           (item_id, jenis, jumlah, tanggal, pengirim, penerima, penjual,
            dicatat_oleh, catatan, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, jenis, jumlah, tanggal, pengirim, penerima,
         penjual or None, dicatat_oleh, catatan, now_str()),
    )
    db.commit()
    label = "masuk" if jenis == "IN" else "keluar"
    flash(
        f"Barang {label} '{item['nama']}' sebanyak {jumlah} {item['satuan']} berhasil dicatat.",
        "success",
    )
    return redirect(url_for("trans_in" if jenis == "IN" else "trans_out"))


@app.route("/transactions")
@login_required
def history():
    db = get_db()
    jenis = (request.args.get("jenis") or "").strip()
    tanggal_dari = (request.args.get("dari") or "").strip()
    tanggal_sampai = (request.args.get("sampai") or "").strip()
    item_id = parse_int(request.args.get("item_id"))
    q = (request.args.get("q") or "").strip()

    where = []
    params = []
    if jenis in ("IN", "OUT"):
        where.append("t.jenis = ?")
        params.append(jenis)
    if tanggal_dari:
        where.append("t.tanggal >= ?")
        params.append(tanggal_dari)
    if tanggal_sampai:
        where.append("t.tanggal <= ?")
        params.append(tanggal_sampai)
    if item_id:
        where.append("t.item_id = ?")
        params.append(item_id)
    if q:
        where.append(
            "(t.pengirim LIKE ? OR t.penerima LIKE ? OR t.penjual LIKE ? "
            "OR t.dicatat_oleh LIKE ? OR t.catatan LIKE ?)"
        )
        like = f"%{q}%"
        params += [like, like, like, like, like]

    sql = (
        """SELECT t.*, i.nama AS item_nama, i.sku AS item_sku, i.satuan AS item_satuan,
                  v.id AS voided_by
           FROM transactions t JOIN items i ON i.id = t.item_id
           LEFT JOIN transactions v ON v.reversal_of = t.id"""
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.tanggal DESC, t.id DESC"

    transactions = db.execute(sql, params).fetchall()
    return render_template(
        "history.html",
        transactions=transactions,
        jenis=jenis,
        dari=tanggal_dari,
        sampai=tanggal_sampai,
        item_id=item_id or "",
        q=q,
        items=active_items(),
    )


# ---------------------------------------------------------------------------
# Util stok atomik
# ---------------------------------------------------------------------------
class StokBerubah(Exception):
    """Stok barang berubah antara form dibuka dan disimpan."""


def valid_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def apply_stock_change(db, item_id, jenis, jumlah):
    """Ubah stok dalam satu statement SQL. Mengembalikan False bila stok tidak cukup."""
    if jenis == "IN":
        cur = db.execute(
            "UPDATE items SET stok = stok + ?, updated_at = ? WHERE id = ?",
            (jumlah, now_str(), item_id),
        )
    else:
        cur = db.execute(
            "UPDATE items SET stok = stok - ?, updated_at = ? WHERE id = ? AND stok >= ?",
            (jumlah, now_str(), item_id, jumlah),
        )
    return cur.rowcount == 1


# ---------------------------------------------------------------------------
# Pembatalan (koreksi) transaksi
# ---------------------------------------------------------------------------
@app.route("/transactions/<int:trans_id>/void", methods=["GET", "POST"])
@login_required
def trans_void(trans_id):
    """Batalkan transaksi dengan mencatat transaksi lawannya (riwayat asli tetap utuh)."""
    db = get_db()
    t = db.execute(
        """SELECT t.*, i.nama AS item_nama, i.sku AS item_sku, i.satuan AS item_satuan,
                  i.is_deleted AS item_deleted, v.id AS voided_by
           FROM transactions t
           JOIN items i ON i.id = t.item_id
           LEFT JOIN transactions v ON v.reversal_of = t.id
           WHERE t.id = ?""",
        (trans_id,),
    ).fetchone()
    if not t:
        abort(404)

    problem = None
    if t["voided_by"]:
        problem = f"Transaksi #{trans_id} sudah pernah dibatalkan."
    elif t["reversal_of"]:
        problem = "Transaksi pembatalan tidak bisa dibatalkan lagi. Catat transaksi baru bila perlu."
    elif t["opname_id"]:
        problem = "Penyesuaian stock opname tidak bisa dibatalkan. Lakukan opname ulang."
    elif t["item_deleted"]:
        problem = "Barang ini sudah dihapus, transaksinya tidak bisa dibatalkan."
    if problem:
        flash(problem, "warning")
        return redirect(url_for("history"))

    if request.method == "POST":
        dicatat_oleh = (request.form.get("dicatat_oleh") or "").strip()
        alasan = (request.form.get("alasan") or "").strip()
        errors = []
        if not dicatat_oleh:
            errors.append("Nama pencatat wajib diisi.")
        if not alasan:
            errors.append("Alasan pembatalan wajib diisi.")

        if not errors:
            lawan = "OUT" if t["jenis"] == "IN" else "IN"
            if not apply_stock_change(db, t["item_id"], lawan, t["jumlah"]):
                errors.append(
                    "Stok tidak cukup untuk membatalkan barang masuk ini "
                    "(sebagian barangnya sudah keluar)."
                )
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("void_form.html", t=t, form=request.form)

        try:
            db.execute(
                """INSERT INTO transactions
                   (item_id, jenis, jumlah, tanggal, pengirim, penerima, penjual,
                    dicatat_oleh, catatan, created_at, reversal_of)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (t["item_id"], lawan, t["jumlah"], today_str(), t["penerima"],
                 t["pengirim"], t["penjual"], dicatat_oleh,
                 f"Pembatalan transaksi #{trans_id}: {alasan}", now_str(), trans_id),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            flash(f"Transaksi #{trans_id} sudah pernah dibatalkan.", "warning")
            return redirect(url_for("history"))
        flash(f"Transaksi #{trans_id} berhasil dibatalkan. Stok sudah dikoreksi.", "success")
        return redirect(url_for("history"))

    return render_template("void_form.html", t=t, form={})


# ---------------------------------------------------------------------------
# Stock opname
# ---------------------------------------------------------------------------
@app.route("/opname")
@login_required
def opname_list():
    db = get_db()
    rows = db.execute(
        """SELECT o.*, COUNT(oi.id) AS total_item,
                  COALESCE(SUM(CASE WHEN oi.selisih != 0 THEN 1 ELSE 0 END), 0) AS jumlah_selisih
           FROM stock_opnames o
           LEFT JOIN stock_opname_items oi ON oi.opname_id = o.id
           GROUP BY o.id
           ORDER BY o.tanggal DESC, o.id DESC"""
    ).fetchall()
    return render_template("opname_list.html", opnames=rows)


@app.route("/opname/<int:opname_id>")
@login_required
def opname_detail(opname_id):
    db = get_db()
    op = db.execute("SELECT * FROM stock_opnames WHERE id = ?", (opname_id,)).fetchone()
    if not op:
        abort(404)
    rows = db.execute(
        """SELECT soi.*, i.nama, i.sku, i.varian, i.satuan
           FROM stock_opname_items soi JOIN items i ON i.id = soi.item_id
           WHERE soi.opname_id = ?
           ORDER BY (soi.selisih = 0), i.nama""",
        (opname_id,),
    ).fetchall()
    return render_template("opname_detail.html", op=op, rows=rows)


@app.route("/opname/new", methods=["GET", "POST"])
@login_required
def opname_new():
    db = get_db()
    if request.method == "GET":
        return render_template("opname_form.html", items=active_items(),
                               today=today_str(), form={})

    form = request.form
    tanggal = (form.get("tanggal") or "").strip()
    petugas = (form.get("petugas") or "").strip()
    catatan = (form.get("catatan") or "").strip() or None
    errors = []
    if not valid_date(tanggal):
        errors.append("Tanggal opname tidak valid.")
    if not petugas:
        errors.append("Nama petugas wajib diisi.")

    rows = []  # (item, stok_sistem, stok_fisik, keterangan)
    for i in active_items():
        raw = (form.get(f"fisik_{i['id']}") or "").strip()
        if raw == "":
            continue  # barang yang tidak dicek dilewati
        fisik = parse_int(raw)
        sistem = parse_int(form.get(f"sistem_{i['id']}"))
        ket = (form.get(f"ket_{i['id']}") or "").strip() or None
        if fisik is None or fisik < 0:
            errors.append(f"Stok fisik {i['nama']} ({i['sku']}) harus angka 0 atau lebih.")
            continue
        if sistem is None:
            errors.append("Data form tidak lengkap, muat ulang halaman.")
            break
        if fisik != sistem and not ket:
            errors.append(f"Keterangan wajib diisi untuk barang yang selisih: {i['nama']} ({i['sku']}).")
        rows.append((i, sistem, fisik, ket))
    if not rows and not errors:
        errors.append("Isi stok fisik minimal untuk satu barang.")

    def tampilkan_ulang():
        for e in errors:
            flash(e, "danger")
        return render_template("opname_form.html", items=active_items(),
                               today=today_str(), form=form)

    if errors:
        return tampilkan_ulang()

    try:
        cur = db.execute(
            "INSERT INTO stock_opnames (tanggal, petugas, catatan) VALUES (?, ?, ?)",
            (tanggal, petugas, catatan),
        )
        opname_id = cur.lastrowid
        jumlah_selisih = 0
        for i, sistem, fisik, ket in rows:
            selisih = fisik - sistem
            # Stok hanya diganti bila masih sama dengan yang dilihat petugas di form.
            ok = db.execute(
                "UPDATE items SET stok = ?, updated_at = ? WHERE id = ? AND stok = ?",
                (fisik, now_str(), i["id"], sistem),
            ).rowcount
            if not ok:
                raise StokBerubah(i["nama"])
            db.execute(
                """INSERT INTO stock_opname_items
                   (opname_id, item_id, stok_sistem, stok_fisik, selisih, keterangan)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (opname_id, i["id"], sistem, fisik, selisih, ket),
            )
            if selisih:
                jumlah_selisih += 1
                # Penyesuaian dicatat sebagai transaksi agar riwayat tetap konsisten.
                db.execute(
                    """INSERT INTO transactions
                       (item_id, jenis, jumlah, tanggal, pengirim, penerima, penjual,
                        dicatat_oleh, catatan, created_at, opname_id)
                       VALUES (?, ?, ?, ?, 'Penyesuaian Opname', 'Penyesuaian Opname',
                               NULL, ?, ?, ?, ?)""",
                    (i["id"], "IN" if selisih > 0 else "OUT", abs(selisih), tanggal,
                     petugas, f"Opname #{opname_id}: {ket}", now_str(), opname_id),
                )
        db.commit()
    except StokBerubah as e:
        db.rollback()
        errors.append(
            f"Stok '{e}' berubah setelah form dibuka (ada transaksi lain). "
            "Tidak ada yang disimpan; cek ulang angka sistem lalu simpan kembali."
        )
        return tampilkan_ulang()

    flash(
        f"Stock opname berhasil disimpan: {len(rows)} barang dicek, "
        f"{jumlah_selisih} selisih, stok sudah disesuaikan.",
        "success",
    )
    return redirect(url_for("opname_detail", opname_id=opname_id))


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    if not session.get("user"):
        return redirect(url_for("login"))
    return render_template("404.html"), 404


@app.context_processor
def inject_globals():
    return {"app_username": session.get("user")}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def bootstrap():
    init_db()
    with app.app_context():
        seed_db()


if __name__ == "__main__":
    bootstrap()
    # Debug/reloader aktif hanya bila FLASK_DEBUG=1 (default: mati, tanpa anak proses).
    debug = os.environ.get("FLASK_DEBUG") == "1"
    # 127.0.0.1 agar hanya lokal; Docker memakai FLASK_HOST=0.0.0.0.
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    app.run(debug=debug, host=host, port=5000)
