# Penyetelan Retrieval — Review & Rekomendasi

Fase P6, peran arsitektur retrieval. Ini review terarah, bukan refactor: membandingkan
retrieval di repo ini dengan pola yang sudah terbukti di dua repo referensi
(asisten wisata desa dengan BM25 hibrid; pemindai dokumen dengan voting lintas
varian OCR), lalu memberi rekomendasi prioritas yang bisa dieksekusi.

Repo aktif **read-only** terhadap kode retrieval. Tidak ada implementasi diubah di sini.

## 1. Peta retrieval saat ini (repo aktif)

Pipeline: embedding pertanyaan → pencarian vektor + BM25 → Reciprocal Rank Fusion
(voktor bobot 1.0, kata kunci 0.6) → gerbang ambang pada **bukti mentah** → batas
per dokumen → rerank cross-encoder multibahasa → sitasi.

Yang **sudah sehat** dan jangan disentuh:
- Tokenisasi dokumen dan query memakai proses yang sama (stopwords + stemming
  Sastrawi seragam), sehingga kosakata keduanya bertemu (`text_processing.py`).
- Fusion berbasis peringkat (RRF), bukan penjumlahan skor mentah yang tak sebanding.
- Ambang dinilai pada bukti mentah (cosine / skor BM25 terskala), bukan pada skor
  fusion yang ternormalisasi — kalau di fusion, ambang di bawah 1.0 tak pernah menolak.
- Rerank berjalan **setelah** ambang, jadi tak bisa mengangkat kandidat di bawah
  ambang dan membatalkan gerbang anti-halusinasi.
- Ada jalur bukti lemah (kandidat terbaik tanpa gerbang, dengan label) dan pengumpul
  konteks sekitar (tetangga `chunk_index`), yang penting untuk rujukan silang ayat/pasal.

## 2. Gap vs rekomendasi

| # | Pola referensi | Ada? | Penting untuk dokumen legal | Usulan implementasi | Kompleksitas |
|---|---|---|---|---|---|
| 1 | Query expansion (kamus padanan, ±190 entri dwiarah) | **Tidak** | Sangat penting | Kamus padanan istilah→istilah dokumen; diterapkan saat query sebelum tokenisasi; bobot token hasil ekspansi lebih rendah | Rendah–Sedang |
| 2 | Reranker dedup per dokumen + penalti duplikat + diversitas | **Sebagian** (batas per dokumen ada, tapi sebelum rerank; rerank tanpa dedup) | Penting | Dedup/diversitas dalam reranker: maks N potongan per dokumen, penalti potongan yang tumpang tindih | Sedang |
| 3 | Bobot judul + bonus cakupan judul penuh | **Tidak** (indeks hanya isi chunk) | Penting (multi-dokumen) | Indeks BM25 juga nama dokumen; bonus chunk yang dokumennya mencakup seluruh istilah inti query | Sedang |
| 4 | Entitas toleran salah ketik (edit distance, fuzzy ≥ N huruf) | **Tidak** di jalur query | Penting untuk nama/istilah | Koreksi istilah query ke entitas korpus lewat jarak edit, hanya untuk kata panjang, ambang ketat | Sedang |
| 5 | Voting lintas varian OCR | Ada padanannya (rescan celah + eskalasi vision, `ocr_engine`) | — | Sudah tercakup di ingestion; bukan gap retrieval | — |

Catatan kompleksitas:
- Rendah–Sedang = murni lapisan query/retrieval, tanpa ubah skema indeks.
- Sedang = menyentuh indeks/skor atau reranker, butuh uji regresi peringkat.

## 3. Tiga rekomendasi teratas (dampak vs biaya)

### Rekomendasi 1 — Query expansion istilah legal (dampak tinggi, biaya rendah–sedang)

Dokumen legal Indonesia konsisten memakai istilah teknis yang tak pernah sepenting
secara leksikal dengan cara pengguna bertanya. Sastrawi hanya menyeragamkan imbuhan,
bukan makna, jadi pasangan ini **tetap berbeda token setelah stemming**:

- "pengaduan" → stem "adu"; "keluhan" → stem "keluhan". Tidak pernah bertemu di BM25.
  Pengguna: *"cara mengajukan keluhan"* vs dokumen: *"mekanisme pengaduan masyarakat"*.
- "Penyelenggara" vs "pengelola" → dua token berbeda, padahal sering merujuk pihak sama.
- "masyarakat" (umum) vs "konsumen" / "pengguna layanan".
- "tata cara" vs "prosedur" vs "mekanisme"; "sls" (SLA) vs "waktu penyelesaian";
  "standar pelayanan" vs "standar layanan".

Usulan: kamus padanan satu arah (istilah umum pengguna → istilah kanonik dokumen),
diterapkan ke query saja. Token dari ekspansi diberi bobot lebih rendah (mis. 0.5×)
supaya tak mendominasi pasal yang memuat istilah aslinya. Mulai dari ±40–60 entri
domain layanan publik, bukan 190 sekaligus.

Kenapa nomor satu: menyentuh kegagalan recall paling sering, biayanya kecil (kamus +
satu transformasi query), dan risikonya rendah karena bobot token ekspansi bisa
diturunkan kalau peringkat memburuk.

### Rekomendasi 2 — Diversitas & dedup di reranker (dampak sedang–tinggi, biaya sedang)

Saat ini rerank hanya mengurutkan ulang kandidat yang sudah lolos ambang dan batas per
dokumen; ia **tidak** mengenali dua potongan yang nyaris identik dari dokumen yang sama
(ayat yang berlanjut antar chunk, atau pasal dengan redaksi berulang). Akibatnya slot
top_k bisa terisi potongan yang saling menimpa, dan jawaban kehilangan keberagaman
pasal/klausul — padahal pertanyaan legal sering butuh beberapa pasal berbeda.

Usulan: setelah rerank, terapkan dedup/diversitas — maksimal N potongan per dokumen
di hasil akhir (proportional ke top_k, lantai 2 seperti perilaku batas per dokumen
sekarang) dan penalti untuk pasangan potongan dengan tumpang tindih tinggi. Urutan
dalam dokumen tetap dipertahankan agar konteks sekitar tak terpecah.

Risiko: kehilangan kelanjutan ayat bila dedup terlalu agresif. Mitigasi: dedup hanya
pada kandidat yang tumpang tindih teksnya, bukan sekadar satu dokumen.

### Rekomendasi 3 — Bobot judul & bonus cakupan judul penuh (dampak sedang, biaya sedang)

Saat ini pencarian BM25 hanya melihat isi chunk; nama dokumen tidak ikut diskor. Untuk
chat multi-dokumen, pertanyaan seperti *"Perpres mengenai ekonomi syariah"* seharusnya
diberi bonus pada chunk yang dokumennya memuat nama itu — sekarang hanya kebetulan
cocok lewat isi. Ini pola terbukti mengalahkan dokumen yang kebetulan memakai kata
basa-basi pada isinya.

Usulan: indeks BM25 menerima nama dokumen sebagai medan terpisah; beri bonus skor pada
chunk milik dokumen yang **mencakup seluruh istilah inti** pertanyaan di namanya (bonus
cakupan penuh), bonus lebih kecil untuk kecocokan sebagian. Karena indeks BM25 memakai
satu inverted index, cara termurah adalah mendaftarkan token nama dokumen ke setiap
chunk dokumen itu dengan penambah frekuensi kecil — tanpa mengubah struktur data.

Risiko: menggeser peringkat pada mode multi-dokumen; perlu uji regresi peringkat pada
dataset evaluasi. Pada mode satu dokumen (chat privat per dokumen) efeknya netral karena
semua kandidat satu nama.

## 4. Yang TIDAK perlu diubah

- **RRF + bobot (1.0 vs 0.6) dan saturasi BM25 `k=4`.** Sudah benar dan beralasan;
  peringkat tak berubah oleh penskalaan monoton. Jangan diutak-atik tanpa data.
- **Gerbang ambang pada bukti mentah.** Sudah tepat; memindahkannya ke skor fusion
  akan mematikan penolakan.
- **Rerank setelah ambang.** Sudah benar.
- **Tokenisasi/stemming seragam dokumen-query.** Sudah benar; jangan ganti stemmer.
- **Pipa OCR multi-varian & voting.** Bukan wilayah retrieval; sudah ditangani lewat
  konfigurasi ingestion di luar cakupan review ini.
- **Jangan tambahkan kerangka pencarian khusus / mesin indeks eksternal.** Pada skala
  korpus saat ini, inverted index in-memory memadai; migrasi hanya menambah biaya.

## 5. Estimasi risiko / regresi

| Rekomendasi | Risiko utama | Mitigasi |
|---|---|---|
| 1. Query expansion | Ekspansi terlalu agresif mendongkrak pasal yang memuat padanan kata tapi bukan topiknya | Bobot token ekspansi < token asli; ambang bukti tetap di bukti mentah sehingga kandidat lemah tetap tersaring; mulai dari kamus kecil |
| 2. Dedup reranker | Membuang kelanjutan ayat / konteks sekitar penting | Dedup hanya pasangan dengan tumpang tindih teks tinggi; lantai per dokumen menjaga jawaban multi-pasal |
| 3. Bobot judul | Menggeser peringkat mode multi-dokumen; kebocoran sinyal nama ke korpus tak bertitel | Bonus cakupan penuh saja (bukan bobot besar); uji regresi pada dataset evaluasi sebelum dipakai |

Risiko melintang: ketiganya menyentuh peringkat, jadi semua butuh **uji regresi
peringkat** pada dataset evaluasi yang sudah ada (`evaluation/dataset.json`,
`POST /analytics/evaluate`) sebelum dan sesudah perubahan — bukan hanya uji "ada
hasilnya". Terapkan satu demi satu, ukur, baru lanjut, agar sebab-akibatnya terlacak.

Urutan eksekusi yang disarankan: **1 → 2 → 3** (dampak/biaya menurun, dan 1 paling
isolasi perubahannya).
