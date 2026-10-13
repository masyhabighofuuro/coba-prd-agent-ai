"""Uji fungsi aplikasi lewat app.test_client() (tanpa menjalankan server).

Jalankan: python tests/smoke_test.py
Menggunakan database sementara; tidak menyentuh app.db produksi.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ["SECRET_KEY"] = "test-secret"
os.environ["APP_USERNAME"] = "admin"
os.environ["APP_PASSWORD"] = "admin123"

import app as m

TMP = tempfile.mkdtemp()
m.DB_PATH = os.path.join(TMP, "app.db")
m.app.config["WTF_CSRF_ENABLED"] = False
m.app.config["TESTING"] = True
m.bootstrap()

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


def body(resp):
    return resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 1. Semua halaman tanpa login -> /login
# ---------------------------------------------------------------------------
for path in ("/", "/items", "/items/new", "/transactions/in", "/transactions/out", "/transactions"):
    r = m.app.test_client().get(path)
    check(f"tanpa login: {path} -> redirect /login",
          r.status_code == 302 and "/login" in r.headers["Location"])

# ---------------------------------------------------------------------------
# 2. Login: salah ditolak, benar diterima
# ---------------------------------------------------------------------------
c = m.app.test_client()
r = c.post("/login", data={"username": "admin", "password": "salah"}, follow_redirects=True)
check("login salah: pesan error jelas", "Username atau password salah" in body(r))

r = c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
html = body(r)
check("login benar: menuju beranda", "Beranda" in html)

# ---------------------------------------------------------------------------
# 3. Modal stock opname wajib dibaca
# ---------------------------------------------------------------------------
check("modal opname muncul setelah login", "Stock Opname Terakhir" in html)
check("modal berisi tombol saya sudah baca", "Saya sudah baca" in html)
r = c.get("/items", follow_redirects=True)
check("halaman lain diblokir sebelum baca -> kembali ke beranda", "Beranda" in body(r))

r = c.post("/opname/ack", follow_redirects=True)
check("setelah baca, modal hilang", "Stock Opname Terakhir" not in body(r))
r = c.get("/items", follow_redirects=True)
check("setelah baca, daftar barang bisa diakses", "Daftar Barang" in body(r))

# ---------------------------------------------------------------------------
# 4. CRUD barang
# ---------------------------------------------------------------------------
r = c.post("/items/new", data={
    "sku": "N-001", "nama": "Gelang", "kategori": "Aksesoris",
    "varian": "Biru", "satuan": "pcs", "stok_awal": "10",
    "stok_min": "5", "harga": "10000", "catatan": "",
}, follow_redirects=True)
check("tambah barang berhasil", "berhasil ditambahkan" in body(r))

r = c.post("/items/new", data={
    "sku": "N-001", "nama": "Gelang 2", "kategori": "Aksesoris",
    "varian": "", "satuan": "pcs", "stok_awal": "1",
    "stok_min": "0", "harga": "", "catatan": "",
}, follow_redirects=True)
check("SKU duplikat ditolak", "sudah dipakai" in body(r))

r = c.post("/items/1/edit", data={
    "sku": "KOS-001", "nama": "Kaos Polos Hitam", "kategori": "Pakaian",
    "varian": "Hitam / L", "satuan": "pcs", "stok_min": "20",
    "harga": "70000", "catatan": "",
}, follow_redirects=True)
check("ubah barang berhasil", "berhasil diperbarui" in body(r))
r = c.get("/items/1")
check("edit tidak mengubah stok (stok hanya lewat transaksi)", "140 pcs" in body(r))

# ---------------------------------------------------------------------------
# 5. Barang masuk: stok bertambah
# ---------------------------------------------------------------------------
r = c.post("/transactions/in", data={
    "item_id": "1", "jumlah": "5", "tanggal": "2026-10-01",
    "pengirim": "Supplier X", "penerima": "Gudang",
    "dicatat_oleh": "Budi", "catatan": "t",
}, follow_redirects=True)
check("catat barang masuk", "berhasil dicatat" in body(r))
r = c.get("/items/1")
check("stok bertambah setelah masuk (140+5=145)", "145 pcs" in body(r))
check("transaksi masuk menampilkan pengirim/penerima/pencatat",
      "Supplier X" in body(r) and "Gudang" in body(r) and "Budi" in body(r))

# ---------------------------------------------------------------------------
# 6. Barang keluar: penjual wajib, stok tidak boleh negatif
# ---------------------------------------------------------------------------
r = c.post("/transactions/out", data={
    "item_id": "1", "jumlah": "1", "tanggal": "2026-10-01",
    "pengirim": "Gudang", "penerima": "B", "dicatat_oleh": "C", "catatan": "",
}, follow_redirects=True)
check("keluar tanpa penjual ditolak", "penjual wajib diisi" in body(r))

r = c.post("/transactions/out", data={
    "item_id": "1", "jumlah": "9999", "tanggal": "2026-10-01",
    "pengirim": "Gudang", "penerima": "B", "penjual": "P",
    "dicatat_oleh": "C", "catatan": "",
}, follow_redirects=True)
check("keluar melebihi stok ditolak", "Stok tidak cukup" in body(r))

r = c.post("/transactions/out", data={
    "item_id": "1", "jumlah": "8", "tanggal": "2026-10-01",
    "pengirim": "Gudang", "penerima": "Buyer A", "penjual": "Penjual B",
    "dicatat_oleh": "C", "catatan": "x",
}, follow_redirects=True)
check("catat barang keluar", "berhasil dicatat" in body(r))
r = c.get("/items/1")
check("stok berkurang setelah keluar (145-8=137)", "137 pcs" in body(r))
check("transaksi keluar menampilkan penjual", "Penjual B" in body(r))

# ---------------------------------------------------------------------------
# 7. Cari & filter
# ---------------------------------------------------------------------------
r = c.get("/items?q=hoodie")
check("cari menemukan hoodie", "Hoodie" in body(r))
r = c.get("/items?q=tidakAda")
check("cari tanpa hasil menampilkan pesan", "Tidak ada barang yang cocok" in body(r))
r = c.get("/items?kategori=Pakaian")
check("filter kategori", "Pakaian" in body(r))
r = c.get("/transactions?jenis=IN&q=Kain")
check("riwayat: filter jenis + pencarian", "Kain Nusantara" in body(r))
r = c.get("/transactions?dari=2026-09-01&sampai=2026-09-15")
check("riwayat: rentang tanggal", "transaksi ditampilkan" in body(r))

# ---------------------------------------------------------------------------
# 8. Badge stok menipis (seed: 2 barang stok <= stok_min)
# ---------------------------------------------------------------------------
r = c.get("/items")
check("badge stok menipis tampil", "Stok menipis" in body(r))

# ---------------------------------------------------------------------------
# 9. Soft delete + riwayat tetap utuh
# ---------------------------------------------------------------------------
r = c.get("/items/1")
check("dialog konfirmasi hapus ada", "Hapus barang" in body(r))
r = c.post("/items/1/delete", follow_redirects=True)
check("hapus barang (soft delete)", "telah dihapus" in body(r))
r = c.get("/items/1")
check("barang terhapus tidak bisa diakses detail", r.status_code == 404)
r = c.get("/items?q=KOS")
check("barang terhapus tidak muncul di daftar", "Kaos Polos Hitam" not in body(r))
r = c.get("/transactions?q=KOS-001")
check("riwayat transaksi barang terhapus tetap ada", "KOS-001" in body(r))

# ---------------------------------------------------------------------------
# 10. Logout -> login lagi -> modal opname muncul kembali (status di sesi)
# ---------------------------------------------------------------------------
r = c.post("/logout", follow_redirects=True)
check("logout menuju halaman login", "Masuk dengan akun bersama tim" in body(r))
r = c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
check("modal muncul kembali setelah login ulang", "Stock Opname Terakhir" in body(r))

# ---------------------------------------------------------------------------
# 11. Limit percobaan login gagal (5x -> lockout 5 menit)
# ---------------------------------------------------------------------------
cl = m.app.test_client()
for _ in range(5):
    cl.post("/login", data={"username": "admin", "password": "x"}, follow_redirects=True)
r = cl.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
check("percobaan ke-6 diblokir walaupun password benar",
      "Terlalu banyak percobaan gagal" in body(r) and r.status_code == 429)
m._login_attempts.clear()
r = cl.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
check("setelah reset lockout, login berhasil", "Beranda" in body(r))

# ---------------------------------------------------------------------------
# 12. Proteksi CSRF aktif
# ---------------------------------------------------------------------------
m.app.config["WTF_CSRF_ENABLED"] = True
c2 = m.app.test_client()
c2.post("/login", data={"username": "admin", "password": "admin123"})
r = c2.post("/opname/ack", data={})
check("POST tanpa token CSRF ditolak", r.status_code == 400)
m.app.config["WTF_CSRF_ENABLED"] = False

# ---------------------------------------------------------------------------
# 13-16. Stok atomik, pembatalan transaksi, stock opname, migrasi DB lama
# ---------------------------------------------------------------------------
import sqlite3
import threading


def q(sql, *args):
    con = sqlite3.connect(m.DB_PATH)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def stok(item_id):
    return q("SELECT stok FROM items WHERE id = ?", item_id)[0][0]


def login_client():
    cx = m.app.test_client()
    cx.post("/login", data={"username": "admin", "password": "admin123"})
    cx.post("/opname/ack")
    return cx


def trx(cx, jenis, item_id, jumlah, **extra):
    data = {"item_id": str(item_id), "jumlah": str(jumlah), "tanggal": "2026-10-02",
            "pengirim": "A", "penerima": "B", "penjual": "P", "dicatat_oleh": "T", "catatan": ""}
    data.update(extra)
    return cx.post("/transactions/" + jenis, data=data, follow_redirects=True)


N = q("SELECT id FROM items WHERE sku = 'N-001'")[0][0]   # stok 10 dari langkah 4

# 13. Dua barang keluar bersamaan untuk stok yang sama: hanya satu boleh lolos
clients = [login_client(), login_client()]
barrier = threading.Barrier(2)
hasil = []


def kirim(cx):
    barrier.wait()
    hasil.append("berhasil dicatat" in body(trx(cx, "out", N, 10)))


ths = [threading.Thread(target=kirim, args=(cx,)) for cx in clients]
[t.start() for t in ths]
[t.join() for t in ths]
check("13a. dua OUT bersamaan: tepat satu berhasil", sorted(hasil) == [False, True])
check("13b. stok tidak negatif setelah OUT bersamaan (0)", stok(N) == 0)
r = trx(clients[0], "in", N, 1, tanggal="31-12-2026")
check("13c. format tanggal salah ditolak", "Format tanggal tidak valid" in body(r))

# 14. Pembatalan transaksi
cx = login_client()
trx(cx, "in", N, 5)
trx(cx, "out", N, 5)
t_in, t_out = [row[0] for row in q(
    "SELECT id FROM transactions WHERE item_id = ? ORDER BY id DESC LIMIT 2", N)][::-1]
r = cx.get(f"/transactions/{t_in}/void")
check("14a. halaman pembatalan tampil", "Batalkan Transaksi" in body(r))
r = cx.post(f"/transactions/{t_in}/void", data={"dicatat_oleh": "", "alasan": ""}, follow_redirects=True)
check("14b. pembatalan tanpa pencatat/alasan ditolak", "Alasan pembatalan wajib diisi" in body(r))
r = cx.post(f"/transactions/{t_in}/void", data={"dicatat_oleh": "X", "alasan": "salah"}, follow_redirects=True)
check("14c. batal barang masuk yang sudah keluar ditolak (stok tidak cukup)",
      "Stok tidak cukup" in body(r) and stok(N) == 0)
r = cx.post(f"/transactions/{t_out}/void", data={"dicatat_oleh": "X", "alasan": "salah input"}, follow_redirects=True)
check("14d. batal barang keluar: stok kembali (0 -> 5)", "berhasil dibatalkan" in body(r) and stok(N) == 5)
r = cx.post(f"/transactions/{t_out}/void", data={"dicatat_oleh": "X", "alasan": "lagi"}, follow_redirects=True)
check("14e. tidak bisa dibatalkan dua kali", "sudah pernah dibatalkan" in body(r) and stok(N) == 5)
r = cx.post(f"/transactions/{t_in}/void", data={"dicatat_oleh": "X", "alasan": "salah"}, follow_redirects=True)
check("14f. batal barang masuk saat stok cukup (5 -> 0)", "berhasil dibatalkan" in body(r) and stok(N) == 0)
rev_id = q("SELECT id FROM transactions WHERE reversal_of = ?", t_in)[0][0]
r = cx.get(f"/transactions/{rev_id}/void", follow_redirects=True)
check("14g. transaksi pembatalan tidak bisa dibatalkan lagi", "tidak bisa dibatalkan lagi" in body(r))
r = cx.get(f"/items/{N}")
check("14h. riwayat menampilkan penanda Dibatalkan & Pembatalan", "Dibatalkan" in body(r) and "Pembatalan #" in body(r))
check("14i. riwayat asli tetap utuh (transaksi tidak dihapus)",
      len(q("SELECT id FROM transactions WHERE id IN (?, ?)", t_in, t_out)) == 2)
r = cx.get("/transactions")
check("14j. halaman riwayat memuat tombol Batalkan", "Batalkan" in body(r))

# 15. Form stock opname
r = cx.get("/opname/new")
check("15a. form opname baru tampil", "Stock Opname Baru" in body(r) and f"fisik_{N}" in body(r))
base = {"tanggal": "2026-10-03", "petugas": "Dewi", "catatan": "uji", f"sistem_{N}": "0", f"fisik_{N}": "3"}
r = cx.post("/opname/new", data=base, follow_redirects=True)
check("15b. selisih tanpa keterangan ditolak", "Keterangan wajib diisi" in body(r) and stok(N) == 0)
r = cx.post("/opname/new", data={"tanggal": "2026-10-03", "petugas": "Dewi"}, follow_redirects=True)
check("15c. opname tanpa stok fisik ditolak", "minimal untuk satu barang" in body(r))
r = cx.post("/opname/new", data={**base, f"ket_{N}": "ketemu di rak lain"}, follow_redirects=True)
check("15d. opname valid: stok disesuaikan (0 -> 3)", "Stock opname berhasil disimpan" in body(r) and stok(N) == 3)
adj = q("SELECT jenis, jumlah, opname_id FROM transactions WHERE item_id = ? ORDER BY id DESC LIMIT 1", N)[0]
check("15e. penyesuaian tercatat sebagai transaksi IN +3 bertanda opname", adj[0] == "IN" and adj[1] == 3 and adj[2])
r = cx.post("/opname/new", data={**base, f"fisik_{N}": "2", f"ket_{N}": "x"}, follow_redirects=True)
check("15f. angka sistem usang (stok sudah berubah) ditolak, tidak ada yang disimpan",
      "berubah setelah form dibuka" in body(r) and stok(N) == 3)
r = cx.get("/opname")
check("15g. daftar opname memuat opname baru", "Dewi" in body(r) and "Opname Baru" in body(r))
op_id = q("SELECT MAX(id) FROM stock_opnames")[0][0]
r = cx.get(f"/opname/{op_id}")
check("15h. detail opname tampil", "ketemu di rak lain" in body(r))
r = cx.get(f"/transactions/{adj and q('SELECT id FROM transactions WHERE opname_id = ?', op_id)[0][0]}/void", follow_redirects=True)
check("15i. penyesuaian opname tidak bisa dibatalkan", "tidak bisa dibatalkan" in body(r))

# 16. Migrasi database lama (tanpa kolom reversal_of/opname_id)
old = os.path.join(TMP, "lama.db")
con = sqlite3.connect(old)
con.executescript("""
CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT NOT NULL UNIQUE, nama TEXT NOT NULL,
  kategori TEXT NOT NULL, varian TEXT, satuan TEXT NOT NULL, stok INTEGER NOT NULL DEFAULT 0,
  stok_min INTEGER NOT NULL DEFAULT 0, harga INTEGER, catatan TEXT, is_deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL,
  jenis TEXT NOT NULL CHECK (jenis IN ('IN','OUT')), jumlah INTEGER NOT NULL, tanggal TEXT NOT NULL,
  pengirim TEXT, penerima TEXT, penjual TEXT, dicatat_oleh TEXT NOT NULL, catatan TEXT,
  created_at TEXT NOT NULL, FOREIGN KEY (item_id) REFERENCES items (id));
""")
con.commit()
con.close()
asli = m.DB_PATH
m.DB_PATH = old
m.init_db()
m.init_db()  # idempoten
kolom = {row[1] for row in q("PRAGMA table_info(transactions)")}
m.DB_PATH = asli
check("16. migrasi DB lama menambah kolom reversal_of & opname_id (aman dijalankan ulang)",
      {"reversal_of", "opname_id"} <= kolom)

# ---------------------------------------------------------------------------
# Ringkasan
# ---------------------------------------------------------------------------
failed = [name for name, ok in RESULTS if not ok]
print("\n==== Ringkasan: %d/%d lolos ====" % (len(RESULTS) - len(failed), len(RESULTS)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)