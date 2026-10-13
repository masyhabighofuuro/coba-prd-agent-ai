# Aplikasi Pencatatan Barang Masuk & Keluar Merchandise

Aplikasi web sederhana untuk mencatat barang merchandise masuk/keluar, menjawab: **kapan, siapa pengirim, siapa penerima, dan siapa penjual**.

## Cara Menjalankan

```bash
pip install -r requirements.txt
python app.py
```

Buka `http://127.0.0.1:5000` di Chrome. Tabel database dibuat dan data seed dimuat otomatis saat database pertama kali kosong (file `app.db` di folder proyek).

### Kredensial contoh (default pengembangan)

| Variabel env | Nilai default | Keterangan |
|---|---|---|
| `APP_USERNAME` | `admin` | Nama akun bersama |
| `APP_PASSWORD` | `admin123` | Password (disimpan sebagai hash, bukan teks biasa) |
| `SECRET_KEY` | acak per-startup | **Wajib diisi di produksi** agar sesi tetap valid antar-restart |
| `FLASK_DEBUG` | kosong | Set `1` untuk mode debug + auto-reload |
| `FLASK_HOST` | `127.0.0.1` | Alamat bind server; set `0.0.0.0` agar bisa diakses dari luar (mis. di dalam Docker) |
| `DB_PATH` | `app.db` di folder proyek | Lokasi file SQLite; dipakai untuk mengarahkan ke volume Docker |

Contoh dengan password kustom:

```bash
set APP_USERNAME=admin
set APP_PASSWORD=rahasiaTim
set SECRET_KEY=ganti-ini-di-produksi
python app.py
```

> Debug mode/reloader **mati secara default** agar tidak ada proses anak yang tertinggal; aktif hanya bila `FLASK_DEBUG=1`.

## Menjalankan dengan Docker

```bash
docker compose up --build
```

Kemudian buka `http://127.0.0.1:5000` di Chrome (login `admin` / `admin123`).

- Container memakai `FLASK_HOST=0.0.0.0` sehingga port bisa diakses dari host.
- Database disimpan di volume `./data/app.db` (di luar image) sehingga data tetap ada walau container dihapus; file ini juga bisa dibuka DBeaver dari host.
- Hentikan dengan `docker compose down`, atau `docker compose up -d` untuk latar belakang.
- Jangan menjalankan `python app.py` dan Docker bersamaan — keduanya memakai port 5000.
- Ganti `SECRET_KEY` di `docker-compose.yml` sebelum dipakai di produksi.

## Membuka Database via DBeaver

SQLite tidak butuh server terpisah; DBeaver membaca file `.db` langsung.

1. **New Database Connection** → pilih **SQLite** → **Next**.
2. **Path**: arahkan ke file database sesuai mode yang dipakai:
   - Mode `python app.py`: `C:\Porto Proyek\coba-prd-agent-ai\app.db`
   - Mode Docker: `C:\Porto Proyek\coba-prd-agent-ai\data\app.db`
3. **Test Connection** → **Finish**. Tabel `items`, `transactions`, `stock_opnames`, `stock_opname_items` akan muncul.

> Hindari mengubah data dari DBeaver saat aplikasi sedang menulis (risiko lock SQLite). Untuk inspeksi/query aman.

## Fitur

- **Login wajib** untuk semua halaman; 1 akun bersama, tanpa registrasi/role.
- **Modal Stock Opname Terakhir** muncul setiap selesai login dan wajib dikonfirmasi ("Saya sudah baca") sebelum memakai fitur lain.
- **Barang**: tambah, ubah (semua field kecuali stok), hapus (soft delete + konfirmasi), cari, filter kategori, urutkan, badge "Stok menipis" (stok ≤ stok minimum), halaman detail berisi riwayat transaksi.
- **Barang Masuk / Keluar**: dropdown barang yang bisa dicari, nama pengirim/penerima (+penjual wajib untuk keluar), pencatat diisi manual, stok berubah otomatis; keluar ditolak jika stok tidak cukup.
- **Pembatalan transaksi**: tombol *Batalkan* di Riwayat/detail barang. Transaksi asli tidak dihapus; sistem mencatat transaksi lawannya (alasan + pencatat wajib) dan menandai yang asli "Dibatalkan". Satu transaksi hanya bisa dibatalkan sekali; membatalkan barang masuk yang sebagian sudah keluar ditolak.
- **Stock opname**: menu *Opname* untuk input stok fisik per barang, melihat daftar dan detail opname. Selisih wajib diberi keterangan, stok sistem otomatis disesuaikan, dan penyesuaiannya tercatat sebagai transaksi bertanda "Opname".
- **Stok atomik**: pengecekan dan perubahan stok dalam satu perintah SQL, jadi dua input bersamaan tidak bisa membuat stok negatif.
- **Riwayat**: filter jenis, rentang tanggal, barang, dan pencarian nama pengirim/penerima/penjual/pencatat, terbaru di atas.
- **Keamanan**: CSRF pada semua form (termasuk login & logout), parameterized query (SQLite), sesi `HttpOnly` + `SameSite=Lax`, kedaluwarsa 8 jam tanpa aktivitas, limit 5 percobaan login gagal lalu lockout 5 menit.

## Data Seed

- 12 barang merchandise (kaos, hoodie, topi, tote bag, tumbler, mug, stiker, pin, lanyard, notebook, dll.), termasuk 2 barang stok menipis.
- 22 transaksi masuk/keluar dalam 30 hari terakhir (nama orang Indonesia).
- 3 stock opname (terbaru ~1 minggu lalu) dengan beberapa item selisih + keterangan.
- Konsisten: stok saat ini = stok awal + total masuk − total keluar.

## Struktur & Pengujian

```
app.py                     Aplikasi Flask (config, db, seed, auth, rute)
templates/                 Jinja2 + Bootstrap 5
tests/smoke_test.py        Uji fungsi via app.test_client() (tanpa server)
Dockerfile                 Image aplikasi (python:3.13-slim)
docker-compose.yml         Orkestrasi container + volume data/app.db
.dockerignore              Berkas yang tidak perlu masuk image
```

Uji fungsional (login redirect, lockout, modal opname, validasi stok, CSRF, stok bersamaan, pembatalan, form opname, migrasi database lama):

```bash
python tests/smoke_test.py
```

## Keputusan / Asumsi

1. "Pertama kali buka aplikasi" diartikan **setiap kali selesai login** — modal opname tampil di tiap sesi login baru, status bacanya disimpan di sesi (bukan database).
2. Karena 1 akun dipakai bersama, **nama pencatat diisi manual** di setiap transaksi.
3. **Penjual** wajib diisi untuk barang keluar, opsional/selama ini kosong untuk barang masuk.
4. Stock opname diinput lewat form *Opname*; barang yang kolom stok fisiknya dikosongkan dianggap tidak dicek. Bila stok sistem berubah setelah form dibuka, penyimpanan ditolak seluruhnya agar angka selisih tidak salah. Data seed opname hanya contoh dan angka "stok sistem"-nya tidak dihitung ulang dari transaksi seed.
5. **Stok awal** saat tambah barang langsung mengisi stok item tanpa membuat transaksi; setelah itu stok hanya berubah lewat transaksi masuk/keluar.
6. Limit percobaan login memakai pencatatan **in-memory per alamat IP** — cukup untuk server pengembangan; untuk multi-proses/produksi perlu penyimpanan bersama.
7. Barang terhapus (soft delete) tidak bisa diakses via detail dan disembunyikan dari daftar/dropdown, tapi riwayat transaksinya tetap tampil.
8. Kategori pada form barang berupa input bebas (ada saran dari kategori yang sudah ada).
9. Waktu dihitung dalam zona **WIB (UTC+7)** untuk tanda waktu; tanggal transaksi diisi manual via input tanggal.

## Di Luar Scope (sengaja tidak dibuat)

Banyak akun/role, registrasi, lupa password, laporan/grafik, ekspor Excel/PDF, upload foto, pembatalan penyesuaian opname, notifikasi email, multi-gudang.