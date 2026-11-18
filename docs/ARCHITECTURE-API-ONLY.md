# ARCHITECTURE — API-Only (tanpa backend yang dijalankan)

> Dokumen **baru**, melengkapi `docs/ARCHITECTURE.md` (profil demo fixture, tidak ditimpa).
> Fase P1 (feasibility pre-check). Owner: architect. Bahasa: Indonesia.
> Repo aktif **read-only** terhadap kode dalam dokumen ini. Tidak ada implementasi yang ditulis di sini.
> Semua klaim teknis di bawah ditautkan ke file/baris yang dibaca. Yang belum diverifikasi ditandai **UNVERIFIED**, bukan ditebak.

## 1. Metadata

| Field | Nilai |
|---|---|
| Owner | architect (lane ARCHITECT) |
| Fase | P1 — feasibility pre-check |
| Lingkup | Kelayakan konsep: seluruh fitur jalan tanpa server yang dikelola; komponen berat dipanggil lewat `base_url` + `api_key` |
| Sumber dibaca | `docs/BRIEF.md`, `docs/ARCHITECTURE.md`, `docs/RETRIEVAL-TUNING.md`, `docs/DECISIONS.md`, `frontend/src/lib/api/config.ts`, `backend/app/providers/embedding.py`, `backend/app/services/retrieval/reranker.py`, `backend/.env.example` |
| Di luar lingkup | Implementasi, desain UI, perubahan requirement, penulisan `docs/AI_SPEC.md` / `docs/DECISIONS.md` / `docs/STATE.json` |
| Status `docs/STATE.json` saat dibaca | `released` (diberikan dalam brief; tidak dibuka/diubah) |

---

## 2. Verdict

**FEASIBLE_WITH_CHANGES**

Konsep ini layak secara arsitektural, tetapi **bukan "FEASIBLE" murni** dan **bukan pula "seluruh fitur sempurna tanpa ada server apa pun"** seperti yang diminta user secara verbatim.

Alasan verdict:

1. **Generation dan vision/OCR sudah berbasis API di kode saat ini.** `LLM_PROVIDER` menerima `groq | openai_compatible | ollama | sglang` (`backend/.env.example:42-54`), dan `OPENAI_COMPATIBLE_BASE_URL` + `OPENAI_COMPATIBLE_API_KEY` sudah ada (`.env.example:65-70`). Vision juga sudah bisa lewat `VISION_PROVIDER=groq` (`.env.example:80-95`). Dua komponen berat ini tinggal dipindah pemanggilnya, bukan dibangun ulang.
2. **Embedding dan rerank masih lokal dan belum punya provider API.** `build_embedding_provider()` hanya mengenal `SentenceTransformerEmbeddingProvider` dan `HashingEmbeddingProvider` (`embedding.py:185-217`); `build_reranker()` hanya mengenal `CrossEncoderReranker` dan `NoopReranker` (`reranker.py:109-141`). Antarmukanya sudah abstrak (`EmbeddingProvider` di `embedding.py:24-36`, `Reranker` di `reranker.py:41-50`), jadi bisa diganti — tapi **implementasi provider API belum ada**. Ini pekerjaan baru, bukan konfigurasi.
3. **Risiko paling senyap ada di parity, bukan di ketersediaan.** Kode lokal menyimpan aturan yang tidak boleh hilang saat dipindah ke API: prefix asimetris E5 (`query: ` / `passage: `) di `embedding.py:140-156`, dimensi 768 yang diverifikasi keras di `embedding.py:122-138`, dan fakta bahwa cross-encoder membaca pertanyaan + kandidat **bersamaan dalam satu forward pass** (`reranker.py:15-19`, `reranker.py:77-78`). Jika API yang dipilih tidak menyediakan ini, retrieval diam-diam memburuk tanpa error.
4. **"Tanpa backend" harus diterjemahkan ulang menjadi "tanpa server yang dikelola".** Opsi yang direkomendasikan (§5, opsi B) memakai fungsi serverless Vercel sebagai proxy kredensial. Itu tetap kode sisi server, tetapi tidak ada FastAPI/Chroma/SQLite/Redis yang harus dijalankan dan dioperasikan — sesuai maksud user "tidak bergantung pada backend lah pokoknya", bukan "nol kode server".
5. **Dua fitur tidak bisa "sempurna" tanpa negara sisi server:** riwayat sesi lintas perangkat dan audit log terpusat. Keduanya harus dinegosiasi ulang atau diberi label jujur (§6). Menjanjikan keduanya tanpa server adalah klaim yang tidak bisa ditunjukkan ke kode mana pun.

### Perubahan wajib sebelum layak rilis

| ID | Perubahan wajib | Bukti / alasan | Owner |
|---|---|---|---|
| W-01 | Putuskan penempatan kredensial (opsi A/B/C di §5). Ini **blocking** — menyangkut rahasia, biaya, dan data pribadi | `docs/BRIEF.md:36-42` (batasan keras), `.env.example:69-70`, `:239-240` | orchestrator → user |
| W-02 | Verifikasi provider API punya: embedding multilingual ≈ `intfloat/multilingual-e5-base`, dimensi 768, kompatibel prefix E5; **dan** endpoint rerank berpasangan | `embedding.py:119`, `:122-138`, `:140-156`; `reranker.py:15-19`, `:65-84` | backend/aiml |
| W-03 | Jaga parity tokenisasi (stopwords + stemming Sastrawi) antara Python dan browser | `docs/RETRIEVAL-TUNING.md:16-19`, `:106`; `.env.example:192-194` | frontend/aiml |
| W-04 | Uji regresi peringkat sebelum/sesudah pada `evaluation/dataset.json` — target minimal: posisi pertama tetap 7/11, bukan kembali ke 4/11 | `docs/RETRIEVAL-TUNING.md:120-126`; `reranker.py:19` | qa/aiml |
| W-05 | Jaga kelima invarian retrieval yang dilarang diubah tanpa data (RRF bobot 1.0/0.6, ambang pada bukti mentah, rerank setelah ambang, tokenisasi seragam, tanpa mesin indeks eksternal) | `docs/RETRIEVAL-TUNING.md:16-25`, `:99-110` | architect (guard) |
| W-06 | Beri label UI yang jujur: mana yang lewat API pihak ketiga, mana yang lokal, dan bahwa riwayat hanya di perangkat ini | `docs/BRIEF.md:38-40`; `docs/ARCHITECTURE.md:39`, `:60-63` | frontend |

Tidak ada blocker arsitektural yang membuat stack tidak layak. W-01 adalah blocker **keputusan**, bukan blocker kelayakan teknis — karena itu `blocking: true` di handoff.

---

## 3. Peta komponen baru

### 3.1 Tetap di browser (komputasi lokal, nol biaya per query)

| Komponen | Keadaan sekarang | Keadaan baru | Catatan / bukti |
|---|---|---|---|
| Chunking | Fixture: `chunkText` 500/50 (`docs/ARCHITECTURE.md:74`) | Tetap lokal, tapi **harus diselaraskan** dengan chunking legal backend per Pasal, `LEGAL_CHUNK_MAX_CHARS=900` (`.env.example:133-139`) | Deviasi 500/50 vs 900/Pasal belum terselesaikan — W-03 |
| BM25 in-memory | Sudah lokal di backend; di fixture memakai `scoreChunk` tumpang tindih kata (`docs/ARCHITECTURE.md:60`) | Pindah ke browser sebagai inverted index + Sastrawi | `docs/RETRIEVAL-TUNING.md:109-110` melarang mesin indeks eksternal pada skala ini — ini justru mendukung tetap di browser |
| RRF | Bobot vektor 1.0 / kata kunci 0.6, berbasis peringkat | Tetap lokal, **jangan diubah** | `docs/RETRIEVAL-TUNING.md:12-14`, `:101-102` |
| Gerbang ambang | Ambang pada bukti mentah, bukan skor fusion | Tetap lokal; 0.82 (`.env.example:152`), weak floor 0.60 (`:185`), batas per dokumen, tetangga ±1 (`:188`), `MAX_CONTEXT_CHARS=8000` (`:190`) | `docs/RETRIEVAL-TUNING.md:20-25` |
| State / sesi / analytics ringan | `localStorage` key `ida.mock.v1` (`docs/ARCHITECTURE.md:54,74`) | Tetap `localStorage`/IndexedDB, **tanpa sinkronisasi** | Konsekuensi: sesi tidak lintas perangkat (§6) |
| PDF parsing teks | pdf.js **belum ada** (`docs/ARCHITECTURE.md:76`, C-01 `:220`) | Tetap lokal via pdf.js (dynamic import, R-06/R-07 `:232-233`) | Halaman hasil pindai tetap butuh OCR — lihat baris OCR di bawah |
| Penyusunan sitasi & jawaban "tidak ditemukan" | Fixture ekstraktif (`docs/ARCHITECTURE.md:60`) | Tetap lokal: sitasi dirakit dari chunk hasil rerank, aturan anti-halusinasi tidak berubah | `docs/RETRIEVAL-TUNING.md:22-23` |

### 3.2 Menjadi panggilan API (network, lewat proxy — lihat §5 opsi B)

| Komponen | Provider saat ini | Perubahan | Bukti |
|---|---|---|---|
| Embedding dokumen | `SentenceTransformerEmbeddingProvider`, `intfloat/multilingual-e5-base`, 768 dim, CPU (`embedding.py:98-166`; `.env.example:128-131`) | Ganti dengan provider API di balik antarmuka `EmbeddingProvider` (`embedding.py:24-36`). **Wajib** kirim `passage: ` saat index, `query: ` saat query, normalisasi, cek dimensi 768 | `embedding.py:119`, `:122-138`, `:140-156` |
| Embedding query | Sama, prefix `query: ` (`embedding.py:145`) | Panggilan API terpisah per query (bisa digabung batch bila banyak query) | `embedding.py:164-166` |
| Rerank | `CrossEncoderReranker`, `BAAI/bge-reranker-v2-m3`, 8 kandidat (`.env.example:177-180`) | Ganti dengan endpoint yang menerima **pasangan** `(question, candidate)` dan mengembalikan skor; urutan indeks tetap dipakai pemanggil | `reranker.py:41-50`, `:65-84`; `.env.example:180` |
| Generation | SUDAH API: `LLM_PROVIDER=openai_compatible`, `OPENAI_COMPATIBLE_*` (`.env.example:42-70`) | Tidak ada perubahan provider; hanya jalur pemanggil yang berpindah ke proxy | `.env.example:47,69-70` |
| Vision / OCR halaman pindai | SUDAH API: `VISION_PROVIDER=groq`, `VISION_MODEL=...llama-4-scout...` (`.env.example:80-95`) | Tetap lewat API; PP-OCR lokal (`OCR_ENGINE=auto`, `.env.example:101-108`) **tidak bisa** dijalankan di browser apa adanya — lihat UNVERIFIED §7 | `.env.example:85-108` |
| Prompt-injection guard | `PROMPT_GUARD_ENABLED=1`, model `meta-llama/llama-prompt-guard-2-86m` (`.env.example:112-119`) | **Jangan hilang.** Ikut dipanggil lewat proxy sebelum konteks masuk LLM | `.env.example:117-119` |

Catatan jujur dari kode: `embedding.py:1-7` secara eksplisit berargumen embedding lokal itu ~90 MB, CPU, nol biaya, dan data tidak keluar mesin — "tidak ada alasan memindahkannya ke API; yang mahal adalah generation, bukan ini." Ini **bukan** alasan untuk menolak permintaan user, tetapi wajib disampaikan: memindahkan embedding ke API menambah biaya dan mengirim teks dokumen keluar tanpa manfaat biaya. Keputusan tetap di user lewat W-01.

### 3.3 Yang harus hilang dari jalur API-only

| Komponen | Bukti keberadaan | Konsekuensi penghapusan |
|---|---|---|
| FastAPI (server yang dijalankan) | `docs/ARCHITECTURE.md:90`, `.env.example` seluruh konfigurasi server | Endpoint `POST /analytics/evaluate` ikut hilang — jalur eval harus dipindah ke CI (`docs/RETRIEVAL-TUNING.md:121`) |
| ChromaDB server + `CHROMA_PERSIST_DIR=./data/chroma` | `docs/ARCHITECTURE.md:92`; `.env.example:226` | Indeks vektor pindah ke memori/IndexedDB browser; volume lama **jangan dihapus** (§8) |
| SQLite server/volume `SQLITE_FALLBACK_PATH=./data/metadata.db` | `docs/ARCHITECTURE.md:93`; `.env.example:227` | `query_logs`, sesi, dan eval runs tidak lagi terpusat (`.env.example:160-164`) |
| Redis / Upstash `REDIS_URL`, `UPSTASH_REDIS_URL/TOKEN` | `.env.example:205-219` | Session memory hilang; `.env.example:210-213` sendiri sudah mengakui isi percakapan hilang saat restart |
| Caddy / origin VPS untuk demo | `docs/ARCHITECTURE.md:89`, `:45` (`*.vercel.app` tak bisa diarahkan ke origin lain) | Demo sepenuhnya di Vercel; produksi VPS tetap bertahan menurut `docs/BRIEF.md:34` |

**Tidak dihapus:** jalur produksi VPS. `docs/BRIEF.md:34` menetapkan produksi tetap di VPS. Arsitektur API-only ini diposisikan sebagai **profil ketiga** di samping demo-fixture dan produksi-VPS, bukan pengganti produksi.

---

## 4. Data flow end-to-end (penanda network)

Legenda: **[L]** = lokal di browser, **[N]** = butuh jaringan (lewati proxy §5 opsi B).

```
upload PDF [L]
  → pdf.js ekstrak teks [L]                       (docs/ARCHITECTURE.md:76, :220)
  → halaman pindai? → OCR vision [N]              (.env.example:85-95)  ▲ UNVERIFIED OCR lokal di browser
  → chunk legal per Pasal ~900 char [L]           (.env.example:133-139) ▲ deviasi 500/50 vs 900
  → embed dokumen: "passage: " + teks [N]         (embedding.py:140-156; .env.example:128-129)
  → indeks vektor + BM25 in-memory [L]            (RETRIEVAL-TUNING.md:109-110)
        Chroma dihapus; tidak ada disk server
  ─────────────────────────────────────────────
  query pengguna [L]
  → embed query: "query: " + teks [N]             (embedding.py:145, :164-166)
  → BM25 (Sastrawi) + vector cosine [L]           (RETRIEVAL-TUNING.md:17-19; .env.example:192-194)
  → RRF rangk, bobot 1.0 / 0.6 [L]                (RETRIEVAL-TUNING.md:12-14, :101-102)
  → gerbang ambang pada bukti mentah [L]          (.env.example:152, :185; RETRIEVAL-TUNING.md:20-21)
        · 0.82 tolak, weak floor 0.60 beri label "bukti terbatas"
        · batas per dokumen + tetangga ±1 + MAX_CONTEXT_CHARS=8000
  → rerank pasangan (query, kandidat), 8 kandidat [N]  (reranker.py:65-84; .env.example:180)
        · WAJIB setelah ambang — jangan balik urutan (RETRIEVAL-TUNING.md:22-23)
        · tanpa endpoint rerank → NoopReranker → 4/11, bukan 7/11 (reranker.py:19, :87-102)
  → prompt-guard [N]                              (.env.example:112-119)
  → generate + streaming [N]                      (.env.example:42-70; streaming timer: ARCHITECTURE.md:62)
  → sitasi + "tidak ditemukan" [L]                (RETRIEVAL-TUNING.md:22-25)
  → log query + analytics [L]                     (localStorage; .env.example:164, :242-247 tidak ada server)
```

Titik network berjumlah 5: OCR (bersyarat), embed dokumen, embed query, rerank, guard+generate. BM25 → RRF → ambang sengaja tetap lokal supaya biaya tidak membengkak dan aturan anti-halusinasi tidak berpindah ke pihak ketiga.

---

## 5. Tiga opsi penempatan kredensial

### Opsi A — API key di browser / `localStorage`

| Aspek | Penilaian jujur |
|---|---|
| Mekanisme | User menempelkan key di UI; disimpan `localStorage`, dikirim langsung ke provider |
| Biaya operasional | Nol server, tapi **tagihan tidak terbatas**: tidak ada pembatasan per pengunjung |
| Rahasia | Key dapat dibaca oleh siapa pun yang membuka demo (bundle/`localStorage`/DevTools). Melanggar semangat `docs/BRIEF.md:38` meski key tidak di-commit |
| CORS | Provider harus mengizinkan origin `*.vercel.app` — **UNVERIFIED** per provider |
| Audit / rotasi | Tidak ada jejak pemakaian per pengunjung; rotasi harus dilakukan manual di setiap perangkat |
| Cocok untuk | Pengembangan lokal satu pengguna. **Tidak cocok** untuk demo publik yang ditautkan dari website pribadi (`docs/BRIEF.md:30-31`) |

Verdict opsi A: **ditolak untuk demo publik**. Layak dipertahankan hanya sebagai jalur dev lokal.

### Opsi B — Fungsi serverless Vercel sebagai proxy tipis (tanpa server dikelola) — **DIREKOMENDASIKAN**

| Aspek | Penilaian jujur |
|---|---|
| Mekanisme | Frontend memanggil `/api/proxy/*` same-origin; fungsi menyimpan key di environment Vercel dan meneruskan ke provider |
| Rahasia | Key tidak pernah masuk repo dan tidak pernah dikirim ke browser — memenuhi `docs/BRIEF.md:38`, `docs/DECISIONS.md:88-90` |
| CORS | Problem CORS provider hilang karena browser hanya bicara ke origin itself. Provider ↔ fungsi tidak terikat CORS browser |
| Kontrol | Bisa pasang whitelist origin, rate limit per IP, batas ukuran body, dan `spend cap` di sisi fungsi + provider |
| Biaya | Penagihan API per query menjadi nyata dan harus dipantau; invocations fungsi juga masuk kuota — **UNVERIFIED** batas Hobby saat ini (catatan: `docs/ARCHITECTURE.md:40` menyebut 250 MB untuk bundle *backend*, bukan untuk fungsi; jangan dipakai sebagai angka fungsi) |
| Latensi | Cold start + hop tambahan menambah latensi pada embed/rerank/generate; rerank sudah 150-400 ms di CPU (`reranker.py:26-27`, `.env.example:174-176`) |
| Batasan | Fungsi tidak bisa menyimpan indeks vektor antar-invocation — tapi indeks memang sengaja tetap di browser (§3.1), jadi ini bukan masalah |
| Risiko | Masih ada "kode server", walau tidak ada server yang dijalankan/operasikan. Harus dijelaskan ke user supaya tidak terasa seperti pengkhianatan terhadap "tanpa backend" |

### Opsi C — Tetap FastAPI di VPS

| Aspek | Penilaian jujur |
|---|---|
| Mekanisme | Frontend → rewrite `/api/v1/*` (`frontend/src/lib/api/config.ts:17-27`) → FastAPI; generation & vision **sudah** API-ready (`.env.example:42-95`) |
| Rahasia | Key di env VPS; CORS dijaga `CORS_ORIGINS` dan nilai `*` ditolak saat start (`.env.example:8-14`) |
| Kontrol | Rate limit `QUERY_MAX_PER_SESSION=20` / 60 detik (`.env.example:157-158`), audit `query_logs` 90 hari (`:164`), Langfuse (`:242-247`) semuanya masih ada |
| Biaya | Paling rendah untuk embedding (nol, lokal — `embedding.py:1-7`), tapi tetap ada biaya VPS |
| Konsekuensi | **Bertentangan dengan permintaan user** ("tidak bergantung pada backend"). Tetap dipertahankan sebagai profil produksi menurut `docs/BRIEF.md:34` dan sebagai baseline perbandingan |

### Rekomendasi dan konsekuensinya

**Pilih opsi B, dengan komputasi ringan (chunking, BM25, RRF, ambang, sitasi) tetap di browser.**

Alasan: satu-satunya opsi yang secara bersamaan (i) menghilangkan server yang harus dijalankan, (ii) menjaga key keluar dari repo dan browser, (iii) menyelesaikan CORS, dan (iv) memberi tempat untuk rate limit + spend cap. Opsi A gagal pada (ii); opsi C gagal pada (i). Opsi B juga selaras dengan `docs/ARCHITECTURE.md:47` — backend memang tidak bisa dipindah ke serverless karena torch/Chroma/SQLite, **tetapi** setelah komponen berat itu diganti API, alasan tersebut hilang; yang tersisa hanyalah proxy tipis tanpa model.

Konsekuensi yang harus diterima:
1. Kredensial tetap ada, hanya pindah ke environment Vercel — bukan "tanpa kredensial".
2. Biaya per query menjadi variabel dan wajib ada pagu (W-01).
3. Kualitas retrieval bergantung pada provider pihak ketiga; jaminan 7/11 tidak lagi berada di tangan repo (W-02, W-04).
4. Teks dokumen dan pertanyaan dikirim ke pihak ketiga — ini menyangkut data pribadi dan harus disetujui (W-01, `blocking: true`).
5. Narasi UI harus berubah: bukan "tanpa backend", melainkan **"tanpa server dikelola; model dipanggil lewat API"**.

---

## 6. Fitur yang berisiko tidak "sempurna" + mitigasi nyata

| # | Fitur | Mengapa tidak sempurna tanpa server | Mitigasi nyata | Bukti |
|---|---|---|---|---|
| F-01 | Riwayat sesi lintas perangkat | State hanya `localStorage` per browser; Redis dihapus | Terima sebagai batas, beri label "riwayat di perangkat ini"; sediakan ekspor/impor JSON. Bila mutlak diperlukan, Supabase — tapi **jalurnya belum ditutup test** | `docs/ARCHITECTURE.md:54`; `.env.example:205-219`, `:229-240` |
| F-02 | Upload besar (10 MB/berkas, 200 berkas, total 1 GB) | Indeks vektor 768-float per chunk tidak muat di `localStorage` 5 MB; kuotaexact **UNVERIFIED** | IndexedDB, batch embed dengan konkurensi terbatas, progress + pesan gagal; turunkan kuota profil API-only, jangan janji 1 GB | `.env.example:196-203`; R-09 `docs/ARCHITECTURE.md:235` |
| F-03 | CORS provider | Embedding/rerank langsung dari browser butuh allowlist origin | Seluruh panggilan melewati proxy opsi B → same-origin | `frontend/src/lib/api/config.ts:23-27`; `docs/ARCHITECTURE.md:45` |
| F-04 | Rate limit & biaya | `QUERY_MAX_PER_SESSION` hilang bersama FastAPI | Rate limit per IP di fungsi + `spend cap` di provider + rotasi key; tampilkan sisa kuota di UI bila bisa | `.env.example:157-158` |
| F-05 | Audit log terpusat | `query_logs` (retensi 90 hari) dan Langfuse butuh server | Log lokal berlabel, atau kirim trace ke Langfuse **lewat proxy** (perlu key sensitif → ikut W-01); kalau tidak, nyatakan di `/about` sebagai gap | `.env.example:160-164`, `:242-247`; `docs/DECISIONS.md:79-81` |
| F-06 | Evaluasi RAGAS / regresi peringkat | `POST /analytics/evaluate` ikut hilang | Jalankan eval di CI memakai GitHub Secrets (bukan browser), bandingkan dengan `evaluation/dataset.json` sebelum promosi | `docs/RETRIEVAL-TUNING.md:120-126`; `docs/ARCHITECTURE.md:61` |
| F-07 | Prompt-injection guard | Mudah terlewat saat memindah pipeline | Jadikan guard langkah wajib sebelum generate; uji bahwa konten berisiko tidak disitasi | `.env.example:112-119` |
| F-08 | Parity tokenisasi Sastrawi | Jika JS berbeda dari Python, peringkat bergeser tanpa error | Uji peringkat pada dataset yang sama (W-04); jangan ganti stemmer | `docs/RETRIEVAL-TUNING.md:17-19`, `:106`, `:120-123` |
| F-09 | Prefix & dimensi embedding | Salah prefix/dimensi membuat cosine meledak dan retrieval kosong | Pertahankan `query: `/`passage: `, cek 768 saat inisialisasi, uji parity | `embedding.py:119`, `:122-138`, `:140-156` |
| F-10 | Rerank lokal 7/11 | Banyak endpoint OpenAI-compatible tidak punya rerank | Verifikasi W-02; bila tidak ada, jangan diam-diam pakai `NoopReranker` — minta keputusan user: turunkan harapan kualitas atau tetap FastAPI hanya untuk rerank | `reranker.py:19`, `:87-102`; `.env.example:177-180` |
| F-11 | Klaim "semua fitur jalan" | Demo tidak boleh berpura-pura jadi produksi | Pisahkan blok klaim di `/about`; label angka sebagai estimasi/log lokal | `docs/BRIEF.md:39`; `docs/ARCHITECTURE.md:60-63`, `:221` |

---

## 7. Yang belum terverifikasi (UNVERIFIED — jangan dijadikan kepastian)

| # | Pertanyaan | Kenapa penting |
|---|---|---|
| U-01 | Apakah `OPENAI_COMPATIBLE_BASE_URL` milik user benar-benar menyediakan endpoint Embeddings | Menentukan apakah W-02 bisa dipenuhi tanpa provider baru. `.env.example:69-70` hanya menamai variabel, bukan kemampuan endpoint |
| U-02 | Apakah provider tersebut menyediakan endpoint **rerank berpasangan** | Kalau tidak, F-10 terjadi |
| U-03 | Apakah model embedding yang ditawarkan setara `intfloat/multilingual-e5-base` (Bahasa Indonesia, 768 dim, prefix E5) | `embedding.py:100-105`, `:119`, `.env.example:122-129` |
| U-04 | CORS/domain allowlist provider untuk origin Vercel | Opsi A benar-benar mustahil jikaProvider tidak mengizinkan |
| U-05 | Limit ukuran/eksekusi fungsi Vercel Hobby saat ini | Jangan pakai angka 250 MB dari `docs/ARCHITECTURE.md:40` — itu untuk bundle backend, bukan fungsi |
| U-06 | PP-OCR / RapidOCR bisa jalan di browser | `.env.example:101-106` mengasumsikan Python (`pip install -e .[ocr]`). Browser mungkin perlu WASM/JS lain yang belum ada di repo |
| U-07 | Implementasi Sastrawi JS yang hasilnya identik dengan Python | `docs/RETRIEVAL-TUNING.md:17-19` mensyaratkan tokenisasi identik |
| U-08 | Perilaku kuota `localStorage`/IndexedDB untuk ribuan vektor 768-dimensi | F-02 |
| U-09 | Biaya aktual embedding + rerank + guard + generate per 1.000 query | W-01 butuh angka untuk menetapkan pagu |

Semua UNVERIFIED di atas harus dicek sebelum W-01 ditutup. Menjawabnya dengan asumsi adalah sumber regresi paling mungkin.

---

## 8. Jalur migrasi bertahap (reversible, tanpa hapus data)

Prinsip: **tambah jalur, uji parity, baru matikan jalur lama**. Tidak ada perubahan skema yang merusak data; volume lama di VPS tetap utuh sampai parity dinyatakan lulus.

| Langkah | Aksi | Reversible dengan | Gate lanjut |
|---|---|---|---|
| M0 — Beku baseline | Tag versi saat ini. Catat metrik dari `evaluation/dataset.json` + `POST /analytics/evaluate` ( recall@5, posisi pertama 7/11 ) | Tag git | Baseline terekam (`docs/RETRIEVAL-TUNING.md:121`) |
| M1 — Provider API di backend, di belakang flag baru | Tambah opsi provider API untuk embedding/rerank tanpa menghapus `SentenceTransformerEmbeddingProvider` / `CrossEncoderReranker` | Flag_provider=local | Parity prefix 768 dan skor rerank terhadap baseline |
| M2 — Proxy tipis di Vercel | Deploy `/api/proxy/*`, key di env Vercel. Frontend masih `isMockMode=1` (`config.ts:35`). Uji CORS, batas body, rate limit, pagu | Hapus fungsi / Kosongkan env | Key tidak muncul di bundle; `check-secrets.mjs` lulus (`docs/DECISIONS.md:88`) |
| M3 — Port komputasi ringan ke browser | Chunking, BM25, RRF, ambang, sitasi di `frontend/src/lib/mock/store.ts`. Samakan 500/50 → keputusan chunking legal 900 | Sakelar `NEXT_PUBLIC_USE_BACKEND` | Peringkat identik dengan backend pada dataset yang sama (W-03, W-04) |
| M4 — Nyalakan profil API-only | Embed/rerank/generate/guard lewat proxy; OCR bersyarat lewat vision | Kembali ke `isMockMode=1` atau `USE_BACKEND=1` | 7/11 bertahan; label UI benar (W-06) |
| M5 — Matikan runtime lama **hanya untuk profil API-only** | FastAPI/Chroma/Redis tidak dijalankan untuk profil ini. **Jangan hapus** `./data/chroma`, `./data/metadata.db`, atau image produksi VPS | Nyalakan lagi compose lama | `docs/BRIEF.md:34` tetap terpenuhi: produksi VPS tidak tersentuh |
| M6 — Operasional | Pantau biaya, kuota, error provider; rotasi key; jalankan eval CI tiap perubahan ranking | Rollback ke M4/M3 | `docs/ARCHITECTURE.md:228-236` (R-06…R-10) tetap jadi checklist |

Rollback total: kembalikan `NEXT_PUBLIC_USE_BACKEND=1` dan nyalakan compose lama. Data tidak pernah dihapus di seluruh langkah — hanya jalur pemanggilan yang berpindah.

---

## 9. ADR ringkas

### ADR-API-001 — Arsitektur API-only dengan proxy serverless

- **Konteks.** User meminta konsep RAG yang tidak bergantung pada backend yang harus dijalankan, tetapi seluruh fitur tetap berjalan dan komponen berat memakai `base_url` + `api_key`. Generation dan vision sudah API-ready (`.env.example:42-95`); embedding dan rerank masih lokal (`embedding.py:98-166`, `reranker.py:53-84`). Rahasia dilarang masuk repo (`docs/BRIEF.md:38`). Backend tidak bisa dipindah ke serverless apa adanya (`docs/ARCHITECTURE.md:36-47`).
- **Alternatif dipertimbangkan.**
  1. Key di browser/localStorage — ditolak: key publik, tagihan tak terbatas, CORS UNVERIFIED.
  2. Proxy serverless Vercel — **dipilih**.
  3. FastAPI VPS — ditolak untuk tujuan ini, dipertahankan untuk produksi (`docs/BRIEF.md:34`).
  4. (Anti-bias) Semua di browser termasuk model via WASM — ditolak: model embedding/rerank berukuran ratusan MB sampai ~1,1 GB (`reranker.py:26-27`) dan tidak ada dukungan di repo; ini adalah alternatif yang dipertimbangkan dan alasan penolakannya.
- **Keputusan.** **FEASIBLE_WITH_CHANGES.** Komputasi ringan tetap di browser; embedding, rerank, generation, guard, dan OCR bersyarat lewat fungsi proxy Vercel; kredensial di environment Vercel; jalur produksi VPS tidak diubah. W-01…W-06 wajib sebelum rilis.
- **Konsekuensi.**
  - Positif: tanpa server dikelola, CORS teratasi, rahasia tidak di repo, biaya bisa dipagu.
  - Negatif: biaya per query nyata; kualitas retrieval bergantung provider; sesi lintas perangkat dan audit log tidak sempurna; narasi "tanpa backend" harus diperbaiki menjadi "tanpa server dikelola"; parity Sastrawi/E5/rerank harus diuji, bukan diandaikan.
  - Blocker keputusan: pilihan provider + persetujuan mengirim teks dokumen ke pihak ketiga + pagu biaya. **Eskalasi ke user via orchestrator.**

---

## 10. Ringkasan untuk eskalasi orchestrator

Tiga hal tidak bisa diputuskan lane ini tanpa user:

1. **Kredensial (A/B/C).** Rekomendasi: B. User perlu mengonfirmasi bahwa "base url + api key" berarti key disimpan di environment Vercel, bukan ditempel di UI — karena opsi A bertentangan dengan batasan rahasia `docs/BRIEF.md:38`.
2. **Data pribadi.** Teks chunk dan pertanyaan akan dikirim ke provider embedding/rerank/generation pihak ketiga. Perlu persetujuan eksplisit; `docs/BRIEF.md:40` melarang demo membuka data produksi — pastikan hanya dokumen demo yang dikirim.
3. **Biaya.** Perlu pagu harian/bulanan dan model fallback sebelum profil API-only diaktifkan (U-09 belum punya angka).

---

*Artefak ini melengkapi `docs/ARCHITECTURE.md` (demo fixture) dan tidak menimpa `docs/ARCHITECTURE_part2.md`. Tidak ada file kode, test, `docs/AI_SPEC.md`, `docs/DECISIONS.md`, atau `docs/STATE.json` yang ditulis oleh artefak ini.*
