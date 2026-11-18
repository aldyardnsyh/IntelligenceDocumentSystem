# AI SPEC — API-Only RAG (konsep P1/P2)

> Owner: aiml · Fase: P1/P2 · Bahasa: Indonesia
> Artefak **baru**. `docs/AI_SPEC.md` sengaja tidak disentuh (statusnya: tidak dipakai pada Fase A).
> Bukan implementasi. Tidak ada kode aplikasi yang diubah, tidak ada test/build yang dijalankan.
> Angka yang tidak bersumber dari repo ditandai **`UNVERIFIED`** dan tidak dijadikan klaim.

---

## 0. Pertanyaan pertama: apakah ini benar-benar butuh AI/API?

Sebelum mendesain, saya perlu meluruskan satu hal yang tersirat di brief: *"pipeline chunking → retrieval → reranking → BM25 kurang efisien karena pakai model lokal"*.

Pernyataan itu **tidak sepenuhnya benar secara teknis**, dan saya tidak mau menyetujuinya tanpa data:

| Komponen | Jenis | Apakah model ML? | Bisa "pindah ke API"? |
|---|---|---|---|
| Chunking (`chunker.py`, `legal.py`) | aturan regex + batas paragraf/Pasal | **Tidak** | Tidak relevan — memang tidak ada modelnya |
| Cleanup / word-fusion (`cleanup.py`) | aturan deterministik | **Tidak** | Tidak relevan |
| BM25 + tokenisasi + stemming Sastrawi | inverted index + algoritma skoring | **Tidak** | Tidak relevan — dan `RETRIEVAL-TUNING.md:109-110` menyatakan mesin indeks eksternal justru menambah biaya |
| Embedding (`embedding.py:98`) | model, ~90 MB, CPU | Ya | Bisa, tapi **local justru nol biaya** (`embedding.py:3-6`) |
| Rerank (`reranker.py:53`) | cross-encoder, ~1.1 GB RAM | Ya | Bisa — ini kandidat paling masuk akal |
| Generation (`openai_compatible.py`) | LLM | Ya | **Sudah pakai API saat ini** |

Jadi ada dua keinginan yang **berbeda** dan sering tertukar:

1. **"Hilangkan backend FastAPI yang harus dijalankan."** Ini alasan yang sah dan kuat.
2. **"Ganti model lokal dengan API karena lebih efisien."** Ini **tidak** terbukti. Untuk embedding, komentar di repo sendiri (`embedding.py:3-6`) menyatakan modelnya ~90 MB, jalan di CPU, nol biaya, dan data tidak keluar — *"tidak ada alasan memindahkannya ke API. Yang mahal adalah generation, bukan ini."*

Kesimpulan jujur: **alasan yang benar untuk desain API-only bukan "API lebih efisien", melainkan "tidak ada runtime untuk model lokal di klien".** Begitu backend FastAPI dihilangkan, `sentence-transformers` / `torch` tidak bisa berjalan di browser (model ratusan MB sampai ~1.1 GB untuk reranker, `reranker.py:26-29`), sehingga embedding dan rerank **terpaksa** menjadi panggilan API. Itu keputusan arsitektur, bukan penghematan. Saya akan menyajikannya apa adanya.

Bagian yang **tetap lokal/deterministik** dan alasannya:

- **Chunking & cleanup** — murni aturan (`chunker.py:12-15`, `legal.py:1-23`). Memanggil API untuk memecah teks hanya menambah latency, biaya, dan ketergantungan jaringan tanpa menambah kualitas. Header konteks per Pasal (`legal.py:12-18`) justru adalah sinyal yang dikonsumsi embedding — memindahkannya ke API tidak mengubah isi sinyalnya.
- **BM25, tokenisasi, stemming Sastrawi** — satu inverted index in-memory sudah memadai pada skala korpus saat ini; `RETRIEVAL-TUNING.md:109-110` secara eksplisit memperingatkan agar tidak menambah mesin indeks eksternal. Stemming harus seragam dokumen/query (`.env.example:192-194`, `RETRIEVAL-TUNING.md:17-18`, `:106`) — memindahkannya ke API justru berisiko memecah keseragaman itu.
- **Gerbang ambang, RRF, batas per dokumen** — logika keputusan, bukan model. Tetap di klien.

Apa yang **benar-benar perlu API** dalam desain tanpa backend: embedding (karena tidak ada model lokal), rerank (alasan sama + menghemat ~1.1 GB RAM klien), generation (sudah demikian).

---

## 1. Kontrak antarmuka 3 panggilan API

Semua panggilan memakai pola transport yang **sudah ada di repo**: `httpx.AsyncClient` bersama per instance, header `authorization: Bearer <api_key>`, `content-type: application/json`, `httpx.Timeout(timeout, connect=5.0)` (`openai_compatible.py:45-63`). Klasifikasi status juga dipakai ulang: 429 → retryable + `retry_after`, 401/403 → bukan retryable, 404 → bukan retryable, ≥500 → retryable (`openai_compatible.py:94-126`).

> **Catatan lintas fungsi (blocking):** bila tidak ada backend, `api_key` harus disimpan di klien. Itu secara fundamental berbeda dari model saat ini di mana rahasia hanya hidup di environment/VPS (`DECISIONS.md:88-90`). Konsekuensi dan opsinya ada di §4 dan §7.

### 1(a) Embedding — `POST {base_url}/embeddings`

Bentuk request generik (OpenAI-compatible):

```jsonc
{
  "model": "<nama model>",
  "input": ["teks chunk 1", "teks chunk 2", ...]   // batch
}
```

Bentuk respons generik:

```jsonc
{
  "data": [
    { "index": 0, "embedding": [0.01, -0.02, ...] },
    { "index": 1, "embedding": [...] }
  ],
  "model": "<nama model>"
}
```

Aturan yang **wajib dipertahankan** dari `embedding.py`:

1. **Batch, bukan satu per satu.** `embed_documents` mengirim daftar sekaligus (`embedding.py:31, 83`); ukuran batch mengikuti `EMBEDDING_BATCH_SIZE` (= 16 di `config.py:245`). Batch menghemat round-trip.
2. **Normalisasi vektor** sebelum disimpan/dibandingkan — lokal memakai `normalize_embeddings=True` (`embedding.py:129, 152`). Cosine dihitung ulang di sisi klien dengan normalisasi eksplisit seperti `cosine_similarity` (`vector_store.py:98-104`), karena tidak boleh mengasumsikan provider sudah menormalisasi. **`UNVERIFIED`** apakah provider API tertentu sudah mengembalikan vektor ternormalisasi — tetap normalisasi di klien.
3. **Dimensi dicek saat inisialisasi**, bukan saat query gagal. Lokal melakukan probe dan menaikkan `ValueError` bila dimensi tidak cocok (`embedding.py:127-138`). API-only harus melakukan probe yang sama sekali: satu permintaan kecil saat startup, bandingkan `len(data[0].embedding)` dengan `EMBEDDING_DIMENSION` (= 768, `.env.example:129`).
4. **Prefix E5 asimetris hanya untuk keluarga E5.** Lokal menyetel `self._uses_e5_prefix = "e5" in model.lower()` dan memakai `"query: "` / `"passage: "` (`embedding.py:119, 140-148`). Penjelasannya tegas: model lain (bge, gte, MiniLM) **dilatih tanpa prefix**; menyuntiknya hanya menggeser teks (`embedding.py:116-118`). Maka:
   - Jika model API mengandung `e5` → terapkan prefix asimetris persis seperti lokal.
   - Jika tidak → **jangan** tambahkan prefix.
   - Apakah provider API tertentu benar-benar memakai konvensi E5 → **`UNVERIFIED`**, wajib dicek ke dokumentasi provider sebelum dipakai, bukan ditebak dari nama model.

Fallback bila embedding API gagal: **hashing deterministik** (`embedding.py:38-95`) sudah tersedia dan dijamin jalan tanpa jaringan. Konsekuensinya harus dinyatakan jujur: cosine dari hashing hanya mendekati tumpang tindih token, **tidak menangkap parafrase** (`embedding.py:54-56`), dan kualitasnya di bawah embedding sungguhan (`embedding.py:58-60`). Jangan diam-diam memakainya tanpa label — repo sudah melaporkan status fallback lewat health/flag `embedding_is_fallback` (`routes.py:1244-1256`).

### 1(b) Rerank — kontrak generik

Bentuk request generik yang diinginkan (alasannya: menjaga antarmuka `Reranker.rerank(question, candidates, top_k) -> list[(int, float)]`, `reranker.py:41-50`):

```jsonc
{
  "model": "<nama model rerank>",
  "query": "pertanyaan pengguna",
  "documents": ["kandidat chunk 1", "kandidat chunk 2", ...],
  "top_n": 8
}
```

Bentuk respons generik yang **dinormalisasi oleh adapter klien** menjadi `[(index, skor), ...]` terurut menurun:

```jsonc
{
  "results": [
    { "index": 3, "relevance_score": 0.91 },
    { "index": 0, "relevance_score": 0.84 }
  ]
}
```

**Peringatan `UNVERIFIED` (blocking untuk implementasi):** format di atas adalah *kontrak target*, bukan format terverifikasi. Provider rerank populer memakai bentuk berbeda — misalnya Cohere memakai field `query`/`documents` dengan respons berisi `index` + `relevance_score`, sementara Jina memakai `query`/`documents` dengan struktur `results.result.index` / `score`. **Keduanya belum diverifikasi terhadap provider yang akan dipakai.** Sebelum kode ditulis, ambil satu contoh request/respons nyata dari dokumentasi provider dan kunci adapter ke situ. Jangan menggeneralisasi dari satu provider ke provider lain.

Aturan yang wajib dipertahankan dari `reranker.py` dan `retriever.py`:

- Rerank **hanya mengurutkan ulang** kandidat yang sudah lolos ambang, tidak boleh menambah kandidat baru (`retriever.py:588-595`). Ini adalah gerbang anti-halusinasi — memindahkannya ke sebelum ambang akan mengangkat chunk di bawah ambang.
- Kembalikan **indeks + skor**, bukan teks, supaya pemanggil tetap memegang metadata asli (`reranker.py:70-72`). Adapter API harus memetakan `index` dari respons ke indeks lokal dengan hati-hati: beberapa provider mengembalikan indeks sesuai urutan input, yang lain mengurutkan ulang — **`UNVERIFIED`**, harus dibuktikan dengan satu contoh respons.
- Kegagalan API rerank **tidak boleh menggagalkan jawaban**. Lokal melakukan ini dengan `try/except` dan kembali ke urutan RRF (`retriever.py:606-618`, `reranker.py:112-115`). Klien API melakukan hal yang sama: fallback = urutan fusi apa adanya.

### 1(c) Generation — kontrak OpenAI-compatible yang sudah ada

Sudah diimplementasikan di `backend/app/providers/openai_compatible.py`: `POST /chat/completions` dengan `model`, `messages` (system + user), `temperature`, `max_tokens`, `stream` (`openai_compatible.py:81-92`), autentikasi Bearer, dan shared client (`:45-63`). Tidak ada desain baru yang diperlukan untuk bentuk request/respons — yang berubah hanyalah **lokasi pemanggilan** (dari backend ke klien).

Yang harus ikut dipindah bersama generation agar tidak hilang: prompt guard (`PROMPT_GUARD_THRESHOLD=0.5`, `.env.example:118-119`) dan batas konteks (`MAX_CONTEXT_CHARS=8000`, `.env.example:190`). Keduanya saat ini dijalankan di backend; dalam desain tanpa backend keduanya menjadi tanggung jawab lapisan klien.

### 1(d) Retry, timeout, cache — kebijakan bersama

| Aspek | Kebijakan | Sumber / alasan |
|---|---|---|
| Timeout | `httpx.Timeout(t, connect=5.0)`, `t` per fungsi: embedding lebih pendek, generation lebih panjang | pola `openai_compatible.py:58-62` |
| Retry | Hanya untuk 429 (hormati `retry_after`) dan ≥500. **Jangan retry 401/403/404** | klasifikasi `openai_compatible.py:94-126` |
| Jumlah retry | Maksimal 2 percobaan tambahan, exponential backoff + jitter | batas anti-stuck global; hindari loop pada kredensial salah |
| Cache embedding | Cache oleh **hash teks + signature model** (lihat §4), bukan oleh teks saja | `embedding.py:87-95` memakai cache teks dengan batas 2048; di API-only kunci harus menyertakan signature agar model berganti tidak memakai vektor lama |
| Cache generation | `CACHE_TTL_SECONDS=1800` sudah ada (`.env.example:156`) — pakai ulang, tapi **jangan cache jawaban yang memuat data sensitif** tanpa redaksi | privasi, lihat §6 |
| Fallback embedding | hashing deterministik + label "mode terbatas" | `embedding.py:38-95`, `routes.py:1244-1256` |
| Fallback rerank | urutan RRF apa adanya | `retriever.py:610-618` |
| Fallback generation | respons "tidak dapat menjawab" + state UI, **bukan** mengarang | prinsip anti-halusinasi `retriever.py:376-378` |

---

## 2. Konsep retrieval baru (tanpa backend)

### 2.1 Urutan tahap — dipertahankan, bukan diubah

Urutan saat ini sudah benar dan **saya tidak mengubahnya tanpa alasan terukur** (`RETRIEVAL-TUNING.md:16-25`, `:99-110`; `retriever.py:350-503`):

```
query
 → [BARU] query expansion kamus legal (ke query saja)
 → embed query (API / fallback hashing)
 → pencarian vektor + BM25 (lokal, di klien)
 → RRF (bobot vektor 1.0, kata kunci 0.6)
 → gerbang ambang pada BUKTI MENTAH (max(cosine, BM25 terskala))
 → batas per dokumen
 → rerank (API / fallback urutan fusi)
 → [BARU] dedup/diversitas pasca-rerank
 → pengumpul konteks tetangga (CONTEXT_WINDOW_CHUNKS=1)
 → generation (API)
 → sitasi
```

Prinsip yang **tidak boleh diubah** (`RETRIEVAL-TUNING.md:99-110`): RRF + bobot 1.0/0.6 dan saturasi BM25 `k=4`; ambang pada bukti mentah (`retriever.py:462-477`); rerank **setelah** ambang; tokenisasi/stemming seragam; tanpa mesin indeks eksternal. Memindah eksekusi ke klien mengubah *tempat*, bukan *urutan* dan bukan *bobot*.

Yang berubah hanya implementasi: `vector_hits` duluan berasal dari `self._store.query()` (`retriever.py:391-396`), sekarang dari array vektor di IndexedDB/KV yang dihitung dengan cosine lokal (`vector_store.py:98-109`); `keyword_hits` tetap dari inverted index lokal.

### 2.2 Candidate count, ambang, dedup

- **Candidate count** tetap `max(top_k * 4, rerank_candidates)` (`retriever.py:390`), dengan `rerank_candidates = 8` (`.env.example:180`) dan `top_k` default 5 (`.env.example:144`). Artinya pada default: `max(20, 8) = 20` kandidat sebelum RRF. Angka ini **tidak saya ubah** karena ia sudah memberi ruang bagi RRF dan reranker; mengecilkan akan menurunkan recall, memperbesar akan menaikkan biaya rerank API secara linear. Perubahan apa pun harus lewat evaluasi §5.
- **Gerbang ambang** tetap `strongest_evidence = max(vector_score, normalized_keyword)` lalu `if strongest_evidence < threshold: continue` (`retriever.py:473-477`). Threshold default 0.82, rentang 0.75–0.92 (`.env.example:152-154`). `WEAK_EVIDENCE_FLOOR=0.60` tetap untuk jalur "bukti terbatas" (`.env.example:182-185`, `retriever.py:505-521`). **Peringatan:** angka 0.82 dikalibrasi untuk cosine embedding sungguhan; bila fallback hashing aktif, skala skornya berbeda — `DECISIONS.md:119-122` sudah mencatat insiden persis ini pada mode demo (skor 0.286 vs ambang 0.82). Desain API-only harus menjaga pemisahan skala ambang antara mode embedding-sungguhan dan mode fallback.
- **Batas per dokumen** tetap `max(2, ...)` (`retriever.py:438-442`).
- **Dedup/diversitas (Rekomendasi 2, `RETRIEVAL-TUNING.md:65-79`)** diterapkan **setelah** rerank, bukan menggantikan batas per dokumen: maks N potongan per dokumen di hasil akhir dan penalti pasangan dengan tumpang tindih teks tinggi. Jangan dedup hanya karena satu dokumen — itu akan membuang kelanjutan ayat (`RETRIEVAL-TUNING.md:78-79`).

### 2.3 Tiga rekomendasi lama tetap relevan

| Rekomendasi | Perlakuan di desain API-only | Catatan |
|---|---|---|
| 1. Query expansion kamus legal | **Tetap lokal & deterministik**, diterapkan ke query sebelum tokenisasi; token ekspansi bobot < token asli | `RETRIEVAL-TUNING.md:43-63`. Mulai ±40–60 entri, bukan 190. Kamus ini bukan model — tidak perlu API. |
| 2. Dedup/diversitas di reranker | **Tetap**, tapi pindah ke pasca-rerank di klien | `RETRIEVAL-TUNING.md:65-79`. Rerank API mengembalikan urutan; dedup di klien setelahnya. |
| 3. Bobot judul dokumen di BM25 | **Tetap lokal**: daftarkan token nama dokumen ke setiap chunk dengan penambah frekuensi kecil | `RETRIEVAL-TUNING.md:81-97`. Cara termurah tanpa ubah struktur indeks — persis cocok untuk klien tanpa backend. Beri bonus cakupan penuh, bukan bobot besar. |

Rekomendasi 4 (entitas toleran salah ketik, `RETRIEVAL-TUNING.md:34`) juga tetap lokal; tidak dibahas lebih lanjut karena bukan bagian dari tiga rekomendasi yang diminta.

---

## 3. Perubahan skema penyimpanan

### 3.1 Dua opsi

| Dimensi | IndexedDB (browser) | Serverless KV |
|---|---|---|
| Lokasi data | Per-perangkat, per-browser | Terpusat di penyedia |
| Biaya | Nol biaya layanan | Ada biaya layanan — **`UNVERIFIED`**, tergantung provider |
| Portabilitas | Buruk: pindah browser = indeks hilang, harus re-ingest | Baik: satu indeks untuk semua perangkat |
| Risiko kehilangan | User bisa menghapus data browser; kuota browser | Terkontrol provider |
| Privasi | Dokumen tidak keluar dari perangkat (lebih baik) | Dokumen/vektor dikirim ke penyedia |
| Kecocokan dengan DECISIONS | Selaras dengan `DECISIONS.md:88-90`: rahasia tidak di server, permukaan publik tetap bersih | Menambah layanan eksternal + permukaan rahasia baru |
| Konsekuensi "tanpa backend" | ✅ benar-benar tanpa backend | ⚠️ masih ada layanan (walau serverless) |

**Rekomendasi aiml (bukan keputusan final — butuh keputusan user):** IndexedDB sebagai penyimpanan utama untuk korpus per-user, karena menjaga janji "tanpa backend" dan tidak menambah permukaan rahasia. Serverless KV hanya bila requirement berubah menjadi "indeks bersama lintas perangkat/akun". Ini bukan klaim bahwa IndexedDB lebih murah secara absolut — itu **perlu diukur** dari ukuran korpus nyata (batas `MAX_DOCUMENTS=200`, `MAX_FILE_SIZE_BYTES=10 MB`, `.env.example:197-200`).

### 3.2 Pencegahan vektor lama dipakai diam-diam

Di repo ada dua mekanisme yang harus **diturunkan**, bukan dihapus:

1. `embedding_provider_key(settings) -> (model, dimension, use_local_embedding)` (`embedding.py:177-182`) — kunci singleton provider.
2. `embedding_signature(settings) -> "sentence-transformers:{model}" | "hashing-fallback:{dim}"` (`vector_store.py:75-95`) — ditulis ke metadata koleksi; bila berubah, indeks lama ditandai mismatch dan perlu reindex (`.env.example:126-127`, `routes.py:1277`).

Masalahnya: kedua bentuk itu berasumsi `use_local_embedding` bernilai boolean. Di desain API-only, `use_local_embedding` selalu **false** untuk jalur API, sehingga `embedding_signature` akan selalu menghasilkan `hashing-fallback:{dim}` — **inkarnasi baru tidak akan terbedakan dari fallback lama**, dan vektor model A bisa dibandingkan dengan vektor model B tanpa error. Gejalanya persis seperti yang diperingatkan `vector_store.py:80-85`: dokumen berstatus `ready`, pertanyaan wajar, jawaban ngawur — tanpa satu pun error.

Signature baru yang diusulkan (konsep, bukan kode):

```
api:{provider}:{model}:{dimension}:{prefix_mode}:{normalization}
```

- `provider` — nama layanan (mencegah model dengan nama sama di provider berbeda dianggap sama).
- `model` — nama model dari respons `/embeddings` (`data[0].model`), bukan hanya dari konfigurasi, supaya drift server terdeteksi.
- `dimension` — hasil probe nyata, bukan nilai config saja (`embedding.py:127-138`).
- `prefix_mode` — `e5-asymmetric` | `none` (lihat §1(a)); perubahan prefix mengubah ruang vektor.
- `normalization` — `l2-client` | `as-is`; karena normalisasi dilakukan di klien (`vector_store.py:98-104`).

Aturan: signature disimpan **sekali per indeks** di metadata IndexedDB/KV. Saat startup, hitung signature aktif, bandingkan. Beda → **tandai indeks stale, wajib re-embed seluruh korpus**, jangan pernah mencampur vektor lama dan baru (prinsip `embedding.py:171-174`: "tanpa itu, test atau reload konfigurasi diam-diam memakai provider milik konfigurasi lama"). Tampilkan status stale di UI, mirip `embedding_mismatch` di health (`routes.py:1277-1298`).

---

## 4. Rencana evaluasi terukur

Prinsip: **tulis cara mengukur, bukan klaim hasil.** Tidak ada angka metrik yang saya sebut sebagai "hasil" di dokumen ini.

### 4.1 Dataset

- `backend/evaluation/dataset.json` — 11 entri; 3 di antaranya ber-`ground_truth` "TIDAK ADA JAWABAN" (baris 43-55) → dipakai sebagai kasus **harus menolak**.
- `backend/evaluation/dataset-perpres.json` — 22 entri, kategori `fakta`, `definisi`, `struktur`, `sintesis`, `outofbox`, `edge`; field `expected_behavior` = `answer` / `refuse` / `smalltalk`; field `expected_pasal` (mis. `[12]`, `[2]`, `[5]`) → memungkinkan penilaian pada level **Pasal**, bukan sekadar nama dokumen.
- Kontrak pemuatan dan validasi sudah ada di `evaluation.py:132-140` (`question` + `ground_truth` wajib, bentuk array JSON).

### 4.2 Metrik — pakai yang sudah di repo, tambahkan yang belum

Metrik yang **sudah dihitung** di `evaluation.py:47-129`:

| Metrik | Definisi di repo | Cara pakai di desain API-only |
|---|---|---|
| `hit_rate` | persentase pertanyaan yang menemukan dokuben benar (`:66-71`) | proxy recall@5 — dihitung pada 5 chunk hasil akhir |
| `precision` | dari sumber yang diambil, berapa yang dokumen benar; hanya untuk entri dengan `document_name` (`:74-98`) | precision@1 / @5; entri tanpa `document_name` tidak dihitung nol (`:78-82`) |
| `refusal_rate` | persentase "tidak ada jawaban" yang benar ditolak (`:108-113`) | dihitung dari 3 entri `dataset.json` + entri `expected_behavior=refuse` di perpres |
| `leaked` | jumlah yang seharusnya ditolak tapi dijawab (`:116-118`) | **gate keras**: harus 0 atau tidak naik dari baseline |

Metrik yang **perlu ditambahkan** (belum ada di `evaluation.py`):

- **recall@5 (level Pasal)** — memanfaatkan `expected_pasal`: apakah Pasal yang diharapkan muncul di 5 chunk teratas. Ini lebih tajam daripada `hit_rate` level dokumen untuk korpus satu dokumen (Perpres), di mana semua chunk punya `document_name` sama sehingga `precision` level dokumen tidak diskriminatif.
- **precision@1 (level Pasal)** — apakah chunk posisi pertama berasal dari `expected_pasal`.
- **hallucination rate** — untuk entri `answer`, bandingkan jawaban terhadap `ground_truth`: apakah angka/nomor Pasal/pihak dalam jawaban didukung oleh ground truth dan oleh chunk bersitasi. Entri `TIDAK ADA JAWABAN` yang tetap dijawab dihitung sebagai halusinasi (sudah tercakup `leaked`, tapi metrik ini memperluas ke klaim angka yang salah pada entri `answer`). Cara penilaiannya bisa rule-based (cek token angka/nomor Pasal) atau model-based — **pilihannya perlu disepakati sebelum run**, agar tidak berganti-ganti setelah melihat hasil.

### 4.3 Gate regresi sebelum/sesudah

1. **Baseline** — jalankan pipeline saat ini (backend) üzerinde kedua dataset, simpan `summary()` (`evaluation.py:120-129`) ke file hasil. Ini titik perbandingan, bukan target yang saya karang.
2. **Sesudah** — jalankan pipeline API-only pada dataset yang sama, dengan konfigurasi identik (`top_k=5`, `threshold=0.82`, `candidate_count=20`, RRF 1.0/0.6, stemming on).
3. **Gate** — bandingkan; ambang penurunan yang diizinkan **harus ditetapkan sebelum run** oleh user/QA, bukan saya. Yang saya rekomendasikan sebagai *prinsip gate* (bukan angka baru):
   - `leaked` tidak boleh meningkat.
   - `refusal_rate`, `hit_rate`, `precision` tidak boleh turun.
   - recall@5/Pasal dan precision@1/Pasal tidak boleh turun.
   - bila turun, lakukan perubahan **satu demi satu** dan ukur lagi, sesuai `RETRIEVAL-TUNING.md:120-123` ("terapkan satu demi satu, ukur, baru lanjut, agar sebab-akibatnya terlacak").
4. **Urutan eksperimen** — `RETRIEVAL-TUNING.md:125-126`: query expansion → dedup → bobot judul. Untuk desain API-only, tambahkan satu langkah isolasi di awal: **ganti embedding lokal→API saja**, ukur; lalu **ganti rerank lokal→API saja**, ukur. Ini memisahkan efek perpindahan model dari efek tiga rekomendasi lama.

---

## 5. Estimasi biaya & latensi (rumus, tanpa angka mengarang)

Semua harga **tidak saya isi**. Variabel `H_embed`, `H_rerank`, `H_gen` (harga per 1 juta token) dan `L_net` (latensi jaringan per round-trip) bersifat **`UNVERIFIED`** — ambil dari faktur/dokumentasi provider yang benar-benar dipakai.

### 5.1 Rumus

**Embedding (ingest):**

```
token_chunk ≈ karakter_chunk / 4
   (heuristik kasar dari chunker.py:43-49; numerik 4 adalah perkiraan, bukan hitungan token nyata)
biaya_embed ≈ (Σ token_chunk / 1_000_000) × H_embed
```

Dengan `LEGAL_CHUNK_MAX_CHARS=900` (`.env.example:138`), sebuah chunk penuh ≈ 900/4 = **225 token (perkiraan kasar)**. Jumlah chunk ≈ total karakter dokumen / 900, dipotong per Pasal (`legal.py`). Ingat: token nyata dari tokenrouter.ai.id API bisa berbeda dari heuristik ini.

**Embedding (query):** 1 query per pertanyaan, umumnya jauh lebih kecil dari chunk — biayanya mengecil, tapi latency `L_net` tetap ada.

**Rerank:**

```
token_rerank ≈ (token_query + token_chunk) × candidate_count
candidate_count = max(top_k × 4, 8)        # retriever.py:390, .env.example:180
biaya_rerank ≈ (token_rerank / 1_000_000) × H_rerank
```

Pada default `top_k=5`, `candidate_count=20` → 20 pasangan query+chunk per pertanyaan. Ini komponen yang **bertambah** dibanding lokal, karena lokal tidak mengenakan biaya per pasangan. Bandingkan dengan biaya RAM lokal ~1.1 GB (`reranker.py:26-27`) yang hilang.

**Generation:**

```
biaya_gen ≈ (token_prompt + token_output) / 1_000_000 × H_gen
token_prompt dibatasi MAX_CONTEXT_CHARS=8000 (.env.example:190)
```

**Latensi:**

```
latensi_total ≈ L_net_embed + (L_net_rerank) + L_net_gen + komputasi_lokal(BM25 + RRF + dedup)
```

Sebagai pembanding terukur dari repo: rerank lokal menambah **150–400 ms per query di CPU** (`reranker.py:26-27`, `.env.example:174-176`), embedding query lokal **di bawah 100 ms CPU** (`.env.example:125-126`). Angka-angka ini adalah **baseline lokal yang sudah ada di repo**, bukan angka API — API perlu diukur dan dibandingkan terhadapnya.

### 5.2 Kapan local lebih murah

- **Embedding:** local hampir selalu lebih murah dalam uang, karena model ~90 MB, CPU, nol biaya (`embedding.py:3-6`). API menjadi "lebih murah" hanya jika biaya operasional server/VPS yang dihilangkan lebih besar daripada tagihan embedding — itu perhitungan **`UNVERIFIED`** tergantung infra user, dan tidak bisa saya jawab dari repo.
- **Rerank:** local menghemat biaya per-pasangan tetapi membayar ~1.1 GB RAM terus-menerus (`reranker.py:26-27`). API menukar RAM tetap dengan biaya variabel. Titik impasnya **perlu diukur** dari volume query nyata; saya tidak akan mengarang angka.
- **Generation:** sudah API saat ini; tidak ada perubahan biaya dari desain ini, hanya lokasi pemanggilan.
- **Jika klien adalah browser:** biaya komputasi lokal berpindah ke perangkat user (baterai/CPU). Itu bukan biaya uang, tapi bukan nol — perlu diuji pada perangkat low-end bila chunking/BM25 tetap di klien.

---

## 6. Catatan AI security & privasi (reringkas, bukan review penuh)

- **Prompt injection:** dokumen yang di-upload adalah data tak tepercaya. Pisahkan instruksi sistem dari isi chunk; jangan biarkan teks dokumen mengubah perilaku generation. Guard sudah ada (`PROMPT_GUARD_THRESHOLD=0.5`, `.env.example:118-119`) dan wajib ikut ke klien.
- **Kredensial di browser (blocking):** memindahkan `api_key` ke klien memperbesar blast radius. Opsi yang perlu diputuskan user: (a) kunci di browser dengan batas kuota/rotasi, (b) proxy tipis serverless yang menyimpan kunci — tapi itu mengembalikan sebagian "backend", (c) BYOK — user mengisi kunci sendiri di UI. `DECISIONS.md:88-90` menetapkan rahasia hanya di environment; desain ini berpotensi bertentangan dengan keputusan itu dan **wajib** dibawa ke user.
- **Privasi:** desain IndexedDB menjaga dokumen tetap di perangkat, tetapi embed/rerank/generate mengirim teks ke provider. Pastikan tidak ada PII yang dikirim tanpa dasar; log prompt/respons harus diredaksi. `CACHE_TTL_SECONDS=1800` (`.env.example:156`) boleh dipakai untuk cache, tapi jangan cache jawaban sensitif.
- **Output:** sanitasi sebelum dirender; sitasi harus tetap mengacu ke chunk asli (`retriever.py:483-498`), bukan ke teks hasil generate.

---

## 7. Ringkasan keputusan yang **tidak** saya ambil sendiri

1. **Penyimpanan:** IndexedDB vs serverless KV (§3.1) — berdampak pada portabilitas dan biaya; butuh keputusan user.
2. **Kredensial API di browser** (§1, §6) — bertentangan dengan `DECISIONS.md:88-90`; butuh keputusan user.
3. **Ambang penurunan metrik gate regresi** (§4.3) — saya sengaja tidak mengarang angka; user/QA yang menetapkan sebelum run.
4. **Format request/respons rerank provider tertentu** (§1(b)) — `UNVERIFIED`, harus diverifikasi sebelum implementasi.
5. **Harga per 1M token** (§5) — `UNVERIFIED`, ambil dari provider nyata.

---

## Handoff

```yaml
from: aiml
to: agentic
phase: P1
type: deliverable
refs: [docs/AI_SPEC-API-ONLY.md]
summary: Konsep API-only RAG: embedding & rerank wajib jadi API karena tidak ada runtime model lokal, tapi chunking/cleanup/BM25/tokenisasi tetap deterministik lokal — "API lebih efisien" tidak terbukti untuk embedding. Urutan retrieval, bobot RRF 1.0/0.6, dan gerbang ambang pada bukti mentah dipertahankan; tiga rekomendasi lama tetap diadaptasi. Signature embedding diperluas agar model API baru tidak memakai vektor lama diam-diam.
evidence: docs/AI_SPEC-API-ONLY.md; docs/RETRIEVAL-TUNING.md:16-25,99-110,120-126; backend/app/providers/embedding.py:3-6,38-60,116-119,127-138,171-182; backend/app/services/retrieval/reranker.py:19-30,41-50; backend/app/services/retrieval/retriever.py:390,438-477,503,588-618; backend/app/services/retrieval/vector_store.py:75-104; backend/app/providers/openai_compatible.py:45-63,81-126; backend/.env.example:128-138,152-154,177-194; backend/app/services/evaluation.py:47-129; backend/evaluation/dataset.json:43-55; backend/evaluation/dataset-perpres.json:1-200; docs/DECISIONS.md:88-90,119-122
blocking: true
needs: Keputusan user atas (1) kredensial API di browser vs proxy/BYOK — bertentangan dengan DECISIONS.md:88-90, (2) IndexedDB vs serverless KV, (3) ambang gate regresi metrik sebelum evaluasi; verifikasi format rerank provider dan harga per 1M token (UNVERIFIED) sebelum kode ditulis.
```
