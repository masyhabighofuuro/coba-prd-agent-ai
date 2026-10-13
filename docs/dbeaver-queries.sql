-- ===========================================================================
-- dbeaver-queries.sql
-- Kumpulan query SELECT (read-only) untuk inspeksi database aplikasi
-- Pencatatan Barang Masuk & Keluar Merchandise.
--
-- Cara pakai di DBeaver:
--   1. Buat koneksi SQLite ke: C:\Porto Proyek\coba-prd-agent-ai\data\app.db
--   2. Aktifkan "Read-only connection".
--   3. Buka file ini sebagai SQL script, lalu jalankan query yang diinginkan.
--
-- CATATAN: file ini hanya berisi SELECT, tidak mengubah data/skema apa pun.
-- ===========================================================================


-- (a) Daftar barang dengan stok <= stok minimum (barang stok menipis).
--     Barang yang sudah dihapus (soft delete) tidak ditampilkan.
--     Diurutkan dari yang paling kritis (selisih stok terkecil).
SELECT
    sku,
    nama,
    kategori,
    varian,
    satuan,
    stok,
    stok_min,
    (stok - stok_min) AS selisih,
    harga
FROM items
WHERE is_deleted = 0
  AND stok <= stok_min
ORDER BY (stok - stok_min) ASC, nama ASC;


-- (b) Riwayat transaksi lengkap dengan nama barang, terbaru di atas.
--     Termasuk penanda apakah transaksi sudah dibatalkan (id transaksi pembatalnya).
SELECT
    t.id,
    t.tanggal,
    t.created_at,
    i.sku                AS item_sku,
    i.nama               AS nama_barang,
    t.jenis,
    t.jumlah,
    i.satuan,
    t.pengirim,
    t.penerima,
    t.penjual,
    t.dicatat_oleh,
    t.catatan,
    v.id                 AS dibatalkan_oleh_id
FROM transactions t
JOIN items i ON i.id = t.item_id
LEFT JOIN transactions v ON v.reversal_of = t.id
ORDER BY t.tanggal DESC, t.id DESC;


-- (c) Transaksi yang sudah dibatalkan beserta transaksi pembatalannya.
--     t = transaksi asli, v = transaksi lawan yang dibuat saat pembatalan.
SELECT
    t.id                 AS id_asli,
    t.tanggal            AS tanggal_asli,
    i.nama               AS nama_barang,
    t.jenis              AS jenis_asli,
    t.jumlah             AS jumlah_asli,
    t.dicatat_oleh       AS pencatat_asli,
    v.id                 AS id_pembatalan,
    v.tanggal            AS tanggal_pembatalan,
    v.jenis              AS jenis_pembatalan,
    v.jumlah             AS jumlah_pembatalan,
    v.catatan            AS alasan_pembatalan,
    v.dicatat_oleh       AS pencatat_pembatalan
FROM transactions t
JOIN transactions v ON v.reversal_of = t.id
JOIN items i ON i.id = t.item_id
ORDER BY v.tanggal DESC, v.id DESC;


-- (d) Transaksi hasil penyesuaian stock opname (opname_id tidak null).
--     Transaksi ini dibuat otomatis saat selisih opname disimpan.
SELECT
    t.id,
    t.tanggal,
    i.sku                AS item_sku,
    i.nama               AS nama_barang,
    t.jenis,
    t.jumlah,
    i.satuan,
    o.id                 AS opname_id,
    o.tanggal            AS tanggal_opname,
    o.petugas,
    t.catatan,
    t.dicatat_oleh
FROM transactions t
JOIN items i ON i.id = t.item_id
JOIN stock_opnames o ON o.id = t.opname_id
WHERE t.opname_id IS NOT NULL
ORDER BY t.tanggal DESC, t.id DESC;


-- (e) Ringkasan setiap stock opname: tanggal, petugas,
--     jumlah item dicek, dan jumlah item yang berselisih.
SELECT
    o.id                 AS opname_id,
    o.tanggal,
    o.petugas,
    o.catatan,
    COUNT(oi.id)         AS jumlah_item_dicek,
    SUM(CASE WHEN oi.selisih <> 0 THEN 1 ELSE 0 END) AS jumlah_item_selisih
FROM stock_opnames o
LEFT JOIN stock_opname_items oi ON oi.opname_id = o.id
GROUP BY o.id, o.tanggal, o.petugas, o.catatan
ORDER BY o.tanggal DESC, o.id DESC;


-- (f) Total barang masuk dan total barang keluar per barang.
--     Hanya menghitung transaksi yang valid (bukan pembatalan). Baris
--     hasil penyesuaian opname (opname_id) tetap ikut terhitung sebagai
--     masuk/keluar sesuai jenisnya.
SELECT
    i.sku,
    i.nama,
    i.satuan,
    i.stok               AS stok_saat_ini,
    COALESCE(SUM(CASE WHEN t.jenis = 'IN'  THEN t.jumlah ELSE 0 END), 0) AS total_masuk,
    COALESCE(SUM(CASE WHEN t.jenis = 'OUT' THEN t.jumlah ELSE 0 END), 0) AS total_keluar
FROM items i
LEFT JOIN transactions t ON t.item_id = i.id
WHERE i.is_deleted = 0
GROUP BY i.id, i.sku, i.nama, i.satuan, i.stok
ORDER BY i.nama ASC;
