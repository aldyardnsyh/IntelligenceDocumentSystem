# Kontrak API

Dokumen ini adalah sumber kebenaran bentuk request/response yang dikonsumsi
frontend `frontend/`. Ditolak dari `frontend/src/types/api.ts`, jadi kalau
frontend berubah, dokumen ini harus ikut berubah.

Status tiap endpoint:

| Kolom | Arti |
| --- | --- |
| `UI` | Dipakai halaman atau komponen frontend |
| `Publik` | Bisa dipanggil tanpa sesi (healthcheck, login, logout) |
| `Tersedia` | Ada di backend, belum dipakai UI |
| `Hanya lokal` | Dikerjakan Next.js, tidak perlu ada di FastAPI |

---

## 1. Ringkasan endpoint

| Method | Path | Status | Dipakai di |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/verify` | UI | `login/actions.ts` (hanya saat backend terhubung) |
| GET | `/api/v1/documents` | UI | sidebar chat, `/documents` |
| POST | `/api/v1/documents/upload` | UI | `/documents`, `/chat` |
| GET | `/api/v1/documents/{id}` | UI | `/documents/[id]` (metadata saja) |
| GET | `/api/v1/documents/{id}/status` | UI | polling status ingestion |
| GET | `/api/v1/documents/{id}/chunks` | UI | `/documents/[id]` (daftar chunk, terpaginasi) |
| DELETE | `/api/v1/documents/{id}` | UI | `/documents`, `/documents/[id]` |
| POST | `/api/v1/chat/query` | UI | `/chat` (SSE) |
| GET | `/api/v1/chat/sessions` | UI | sidebar chat |
| DELETE | `/api/v1/chat/sessions` | UI | `/settings` zona berbahaya |
| PATCH | `/api/v1/chat/sessions/{session_id}` | UI | ubah nama satu percakapan |
| DELETE | `/api/v1/chat/sessions/{session_id}` | UI | hapus satu percakapan |
| GET | `/api/v1/chat/{session_id}/history` | UI | `/chat/[sessionId]` |
| DELETE | `/api/v1/chat/{session_id}` | Tersedia | tidak dipakai UI |
| GET | `/api/v1/settings` | UI | `/settings` |
| PUT | `/api/v1/settings` | UI | `/settings` (debounce 800 ms) |
| GET | `/api/v1/analytics/summary` | UI | `/analytics` |
| GET | `/api/v1/analytics/logs` | UI | `/analytics` |
| GET | `/api/v1/health` | Publik | healthcheck, halaman login (boot_id) |
| POST | `/api/logout` | Hanya lokal | header, route handler Next.js |

### Alasan beberapa endpoint ada di luar alur utama

Endpoint berikut tidak muncul di halaman utama, tapi UI yang sudah ada tidak
bisa jalan tanpanya:

- **`GET /api/v1/documents`**. `/documents` dan sidebar `/chat` harus
  menampilkan daftar dokumen beserta statusnya. Tanpa endpoint ini, polling
  status tidak punya sumber.
- **`GET /api/v1/documents/{id}`**. `/documents/[id]` butuh metadata dokumen
  dan parameter ingestion sekaligus, supaya angka yang ditampilkan di
  halaman itu bukan konstanta tebakan. Daftar chunk diambil terpisah lewat
  `GET /documents/{id}/chunks`, supaya dokumen besar tidak mengirim seluruh
  isinya sekaligus.
- **`GET /api/v1/chat/sessions`**. Sidebar menampilkan "Riwayat Sesi" dengan
  judul otomatis dari pertanyaan pertama. `GET /chat/{id}/history` hanya bisa
  dibaca kalau `id` sudah diketahui, sedangkan daftar id tidak tersedia.
- **`DELETE /api/v1/chat/sessions`**. Menghapus **seluruh** sesi sekaligus,
  berbeda dari `DELETE /chat/{session_id}` yang hanya mereset satu sesi.
- **`PATCH /api/v1/chat/sessions/{session_id}`** dan
  **`DELETE /api/v1/chat/sessions/{session_id}`**. Mengubah nama dan menghapus
  satu percakapan dari sidebar. Perhatikan bahwa `DELETE /chat/{session_id}`
  punya bentuk yang mirip, jadi perbedaan path-nya penting:
  `/chat/sessions/{id}` mengubah judul dan menghapus isi percakapan,
  sedangkan `/chat/{session_id}` hanya mereset memori percakapan itu. Router
  harus tidak menganggap `/chat/sessions/...` sebagai `session_id`.

---

## 2. Format error

Semua endpoint non-2xx memakai bentuk yang sama:

```json
{ "detail": "Deskripsi yang bisa ditampilkan ke pengguna", "code": "slug_galat" }
```

`detail` ditulis untuk dibaca orang, bukan untuk log. Frontend memakainya
apa adanya sebagai pesan di UI.

| HTTP | Code umum | Arti |
| --- | --- | --- |
| 400 | `invalid_request` | Masukan tidak valid |
| 401 | `session_expired` | Sesi akses sudah berakhir |
| 413 | `file_too_large` | Berkas melewati 10 MB |
| 422 | `unprocessable` | Validasi field gagal |
| 429 | `rate_limited` | Rate limit kena. Wajib mengirim header `Retry-After` |
| 507 | `insufficient_storage` | Kuota dokumen habis: batas jumlah atau total ukuran |
| 5xx | `internal` | Gangguan server, layak dicoba ulang |

Frontend hanya melakukan retry otomatis untuk 408, 5xx, dan kegagalan
jaringan. 404 atau 422 tidak akan membaik dengan dicoba ulang.

**507 dikecualikan dari retry** walaupun berawalan 5. Kuota penyimpanan yang
penuh tidak berubah karena dicoba lagi, jadi percobaan ulang hanya membuat
pengguna menunggu lebih lama sebelum melihat pesan yang sama. Pesannya
ditampilkan apa adanya, karena backend sudah menyebut angka batas dan
tindakan yang harus diambil (hapus dokumen lama di halaman Dokumen).

### Dokumentasi interaktif

`/docs`, `/redoc`, dan `/openapi.json` **mati secara default**. Ketiganya
dinyalakan bersama lewat `API_DOCS_ENABLED=1`.

Skema OpenAPI memuat seluruh bentuk request dan response termasuk nama field
internal, dan `/docs` membiarkan siapa pun mencoba endpoint tanpa menulis
kode. Untuk aplikasi yang menampilkan dokumen pribadi, itu permukaan yang
tidak perlu terbuka. Ketiganya dikendalikan satu sakelar supaya tidak ada
jalur yang lupa ditutup: membiarkan `/openapi.json` hidup akan membocorkan
hal yang sama lewat jalur lain.

Halaman `/about` menautkan ke dokumentasi ini lewat
`NEXT_PUBLIC_API_DOCS_URL`. Kalau sakelarnya mati, tautan itu harus
dikosongkan juga, kalau tidak pengguna diarahkan ke halaman 404.

---

## 3. Auth

### `POST /api/v1/auth/verify`

```json
// request
{ "passcode": "string" }

// 200
{ "ok": true, "expires_in": 86400 }
```

- Gagal: `401` dengan `detail` generik. Jangan bedakan "passcode salah" dari
  "passcode tidak ada", itu membocorkan informasi.
- Terlalu banyak percobaan: `429` + header `Retry-After` dalam detik
  (percobaan ke-6 ditolak).
- Cookie sesi: HTTP-only, `SameSite=Lax`, `Secure` di produksi, `Max-Age=86400`.

**Catatan arsitektur.** Frontend juga memasang cookie gerbang sendiri
(`ida_gate`) lewat server action, hanya untuk menentukan boleh/tidaknya
merender halaman. Cookie itu bukan kredensial. Kalau backend terhubung, seluruh
keputusan ada di backend.

---

## 4. Documents

### `GET /api/v1/documents`

```json
{
  "id": "doc_...",
  "filename": "laporan.pdf",
  "page_count": 34,
  "size_bytes": 4404019,
  "status": "ready",
  "uploaded_at": "2026-09-29T02:15:00Z",
  "error_message": null,
  "chunk_count": 142
}
```

`status`: `uploading` | `processing` | `ready` | `failed`.
`error_message` hanya terisi saat `status = failed`, dan pesannya harus
actionable (misal: "Berkas PDF terenkripsi tidak bisa dibaca").

`page_count` boleh `null` untuk berkas tanpa paginasi (TXT, Markdown).
`chunk_count` boleh `null` selama masih diproses.

### `POST /api/v1/documents/upload`

`multipart/form-data` dengan satu field bernama `file`.
Toleransi: PDF, TXT, MD. Maks 10 MB.

```json
// 202
{ "id": "doc_...", "filename": "laporan.pdf", "status": "processing", "...": "..." }
```

Jawaban boleh `202 Accepted`: ingestion berjalan asinkron. Jangan menunggu
sampai `ready`.

### `GET /api/v1/documents/{id}`

Hanya metadata dokumen, **tanpa** daftar chunk. Bentuknya `DocumentSummary`
ditambah:

```json
{
  "ingestion": {
    "splitter": "RecursiveCharacterTextSplitter",
    "chunk_size": 500,
    "chunk_overlap": 50,
    "embedding_model": "all-MiniLM-L6-v2",
    "vector_store": "chroma"
  }
}
```

`ingestion` dibaca apa adanya oleh `/documents/[id]`. Isinya harus nilai yang
benar-benar dipakai saat ingestion, bukan konstanta tebakan.

Mengapa chunk tidak disertakan: satu dokumen bisa menghasilkan ribuan chunk,
dan mengirim semuanya dalam satu respons membuat halaman detail tidak
terpakai. Endpoint terpisah di bawah yang aman dibaca.

### `GET /api/v1/documents/{id}/chunks`

```
?page=1&page_size=10&q=klausul
```

`q` bersifat opsional. Kalau diisi, filter berlaku pada **isi chunk**,
case-insensitive. String kosong tidak perlu dikirim; frontend menghapusnya
dari query.

```json
{
  "items": [
    { "id": "doc_..._c1", "chunk_index": 0, "page_number": 1,
      "content": "isi chunk", "token_count": 128 }
  ],
  "total": 142,
  "page": 1,
  "page_size": 10
}
```

`total` adalah jumlah hasil **setelah** filter, bukan jumlah seluruh dokumen.
Frontend memakai `total` untuk menghitung jumlah halaman, jadi kalau `total`
menghitung sebelum filter, navigasinya salah.

Aturan tambahan:

- `page` dimulai dari 1. Melewati halaman terakhir tidak boleh error;
  kembalikan `items: []` dengan `total` yang benar.
- `page_size` default 10, maksimum 100.
- Urutan `items` harus konsisten, misalnya `chunk_index` menaik, supaya
  halaman tidak saling bertumpang tindih.
- Pencarian sebaiknya memakai full-text index, bukan `ILIKE '%q%'` di atas
  seluruh tabel, karena `%` di depan membuat indeks tidak terpakai.
- Field `content` boleh dipotong di server kalau isinya sangat panjang, tapi
  kalau begitu ada field `truncated: true`. Untuk sekarang kirim utuh.

### `DELETE /api/v1/documents/{id}`

`204 No Content`. Menghapus dokumen, seluruh chunk, dan seluruh entri vector
store-nya. Cache query yang mereferensikan dokumen ikut di-invalidate. Jika ada
sesi aktif yang menunjuk dokumen itu, hapus juga sitasinya dari riwayat.

---

## 5. Chat

### `POST /api/v1/chat/query`

`Content-Type: application/json`, `Accept: text/event-stream`.

```json
// request
{
  "session_id": "ses_..." | null,
  "question": "apa isi klausul 14?",
  "document_id": "doc_..." | null,
  "document_ids": ["doc_...", "doc_..."] | null,
  "allow_ungrounded": false
}
```

| Field | Wajib? | Arti |
| --- | --- | --- |
| `session_id` | tidak | `null` = sesi baru; server yang membuat id-nya |
| `question` | ya | 1-8000 karakter, tidak boleh kosong |
| `document_id` | tidak | **scope dokumen**: kalau diisi, retrieval hanya mencari di dokumen itu (chat privat per dokumen). `404` kalau dokumen tidak ada, `409` kalau belum `ready` |
| `document_ids` | tidak | **scope beberapa dokumen**, maksimal 20. Kalau diisi, retrieval hanya mencari di dokumen-dokumen itu. `404` kalau ada id yang tidak dikenal (pesan menyebut id mana), `409` kalau ada yang belum `ready`. Kalau `document_id` juga diisi, `document_id` yang dipakai karena itu scope yang lebih sempit |
| `allow_ungrounded` | tidak | `true` = kalau tidak ada konteks, LLM menjawab dari pengetahuan umum dengan label; `false` = mode ketat ("tidak ditemukan") |

Jawaban berupa SSE. Setiap event dipisahkan baris kosong ganda, dan payload
-nya adalah satu objek JSON pada baris `data:`.

```text
data: {"type":"session","session_id":"ses_abc123"}

data: {"type":"token","value":"Menurut Klausul 14.1"}

data: {"type":"citations","value":[ ... ]}

data: {"type":"not_found"}

data: {"type":"done","response_time_ms":1420}
```

| Event | Wajib? | Arti |
| --- | --- | --- |
| `session` | ya | dikirim sekali di awal kalau sesi baru dibuat |
| `token` | ya | potongan teks. Frontend menempelkan apa adanya |
| `citations` | kalau ada sumber | daftar sitasi untuk jawaban ini |
| `not_found` | kalau di bawah ambang | menggantikan jawaban dengan pesan tidak ditemukan |
| `ungrounded` | kalau mode longgar dipakai | dikirim **sebelum** token pertama: jawaban berikut datang dari pengetahuan umum model, bukan dari dokumen |
| `done` | ya | penanda stream selesai |
| `error` | kalau gagal | `{ "type":"error","message":"...","retry_after_seconds":30 }` |

Aturan yang tidak boleh dilanggar:

- `not_found` dikirim **setelah** retrieval dan **sebelum** panggilan LLM.
  Kalau `token` sudah sempat terkirim lalu ternyata `not_found`,
  jawabannya terlambat dihentikan.
- `ungrounded` dikirim **sebelum** token pertama. Label yang datang setelah
  jawaban sudah terbaca terlambat untuk mencegah salah paham.
- Jawaban `ungrounded` **tidak boleh** disertai `citations`. Jawaban dari
  pengetahuan umum tidak memakai sumber mana pun; menampilkan sumber di
  bawahnya membuatnya terlihat bersumber.
- Jawaban yang menolak ("tidak ditemukan") juga tidak dikirim bersama
  `citations`, meski retrieval sempat meloloskan chunk.
- `citations` berisi `document_name` dan `page_number`. `page_number` boleh
  `null` untuk berkas tanpa paginasi; frontend lalu menampilkan nomor chunk.
- Setelah event `done`, stream ditutup.

### `GET /api/v1/chat/sessions`

```json
{
  "id": "ses_abc123",
  "title": "pertanyaan pertama pengguna, dipotong 60 karakter",
  "created_at": "2026-09-29T02:20:00Z",
  "last_active_at": "2026-09-29T02:31:00Z",
  "message_count": 6,
  "document_id": "doc_..." | null
}
```

`document_id` adalah scope sesi: kalau terisi, sesi itu hanya mencari di
dokumen tersebut (chat privat per dokumen); `null` berarti sesi lintas
dokumen. Sesi lama yang dibuat sebelum fitur ini ada dibaca sebagai `null`,
bukan error.

Urut `last_active_at` menurun. Hanya sesi yang masih hidup di memory store
(TTL default 1 jam) yang dikembalikan; sesi yang sudah kedaluwarsa
tidak dikembalikan dan frontend menampilkannya sebagai daftar kosong, bukan
error.

### `GET /api/v1/chat/{session_id}/history`

```json
{
  "session": { "...": "..." },
  "messages": [
    { "id": "msg_...", "role": "assistant", "content": "...",
      "created_at": "...", "citations": [], "not_found": false,
      "ungrounded": false }
  ]
}
```

`ungrounded: true` berarti jawaban itu datang dari pengetahuan umum model.
Frontend **wajib** menampilkan labelnya, termasuk saat riwayat dibuka ulang.
Label yang hanya ada saat streaming dan hilang setelah reload membuat jawaban
lama terlihat bersumber.

Sesi tidak ada atau sudah kedaluwarsa: `404`. Frontend menampilkan
`ErrorState`, bukan halaman kosong.

### `DELETE /api/v1/chat/sessions`

`204 No Content`. Menghapus seluruh sesi milik pengguna aktif.
Ini endpoint berbeda dari `DELETE /chat/{session_id}` yang hanya satu sesi.

### `PATCH /api/v1/chat/sessions/{session_id}`

```json
// request
{ "title": "Audit klausul kontrak Q3" }

// 200
{ "id": "ses_...", "title": "Audit klausul kontrak Q3",
  "created_at": "...", "last_active_at": "...", "message_count": 6 }
```

Mengubah judul satu percakapan. Aturan yang harus dipegang backend:

- Judul hasil otomatis (potongan pertanyaan pertama) hanya dipakai **sampai
  user memberi nama sendiri**. Setelah ada `title` yang ditetapkan user,
  pertanyaan berikutnya **tidak boleh** menimpanya. Tanpa aturan ini, pengguna
  akan menemukan namanya kembali berubah sendiri setelah chat berikutnya.
- Panjang 1 sampai 80 karakter setelah whitespace berulang dirapikan.
  String kosong ditolak dengan `400`, bukan diterima lalu disimpan kosong.
- `last_active_at` **tidak** berubah. Mengubah nama bukan aktivitas percakapan.
- Sesi tidak ada: `404`.
- Balas dengan bentuk `ChatSession` lengkap, bukan cuma `{ "ok": true }`,
  supaya frontend bisa langsung menyelaraskan cache tanpa fetch ulang.

### `DELETE /api/v1/chat/sessions/{session_id}`

`204 No Content`. Menghapus satu percakapan beserta seluruh pesanannya.

- Hapus juga cache query yang memakai `session_id` di Redis.
- Hapus entri `sessions` di PostgreSQL.
- Sesi tidak ada: `404`. `404` di sini penting karena frontend memakai
  `404` untuk membedakan "sudah dihapus" dari "server gagal".

---

## 6. Settings

### `GET /api/v1/settings`

```json
{ "top_k": 5, "similarity_threshold": 0.5 }
```

### `PUT /api/v1/settings`

Request memakai sebagian dari bentuk di atas. Response mengembalikan nilai
final yang aktif, karena backend bisa melakukan clamping ke rentang yang
sah.

Rentang yang dipatuhi UI:

| Parameter | Min | Maks | Default |
| --- | --- | --- | --- |
| `top_k` | 3 | 10 | 5 |
| `similarity_threshold` | 0.50 | 0.90 | 0.50 |

Perubahan harus berlaku pada query berikutnya tanpa restart, jadi
backend tidak boleh menyimpan parameter ini di memori proses yang sudah
di-cache.

---

## 7. Analytics

### `GET /api/v1/analytics/summary`

```json
{
  "latest_eval": {
    "id": "eval_...", "precision": 0.82,
    "faithfulness": 0.91, "answer_relevance": 0.88,
    "run_at": "2026-09-28T03:00:00Z"
  },
  "latency": [ { "date": "2026-09-27", "avg_ms": 1420, "p95_ms": 2100 } ],
  "tokens": [ { "date": "2026-09-27", "input_tokens": 182400, "output_tokens": 66100 } ]
}
```

`latest_eval` **boleh `null`** kalau belum ada run evaluasi. Frontend
menampilkan empty state, bukan angka nol dan bukan angka contoh.
Satu-satunya sumber angka RAGAS adalah tabel `eval_runs`; jangan
mengarang dari sisi frontend.

`date` berformat `YYYY-MM-DD` dan berada di zona waktu yang sama dengan zona
waktu label sumbu chart. `tokens` adalah angka Consumption aktual dari
Langfuse, bukan estimasi panjang string.

### `GET /api/v1/analytics/logs?page=1&page_size=10`

```json
{
  "items": [
    { "id": "log_...", "session_id": "ses_...", "question": "...",
      "response_time_ms": 1420, "sources_count": 2,
      "created_at": "2026-09-29T02:31:00Z", "from_cache": false,
      "trace_id": "a1b2c3d4e5" }
  ],
  "total": 1489, "page": 1, "page_size": 10
}
```

`sources_count: 0` berarti retrieval tidak menemukan apa pun. Frontend
menandainya dengan teks "tidak ditemukan", bukan `0` polos.

**`trace_id`** adalah id trace Langfuse untuk panggilan LLM pada query itu.
Aturannya:

- `null` kalau tidak ada panggilan LLM: query dijawab dari cache,
  atau retrieval tidak menemukan apa pun sehingga LLM tidak dipanggil.
- String kosong **tidak boleh** dipakai sebagai pengganti `null`.
- Frontend tidak pernah membuat nilai ini di sisi klien. Kalau kolomnya masih
  kosong setelah RAGAS dan Langfuse terhubung, berarti tracing belum
  dikonfigurasi di backend.

Kolom ini perlu ada di tabel `query_logs` sebagai
`trace_id text null`, dengan indeks bila tabel besar. Gunanya supaya tabel log
di `/analytics` bisa ditautkan langsung ke tracing, yang selama ini jadi
kesenjangan antara dua dashboard.

---

## 8. Health

### `GET /api/v1/health`

```json
{
  "status": "ok",
  "llm": "ok", "vector_store": "ok", "memory": "ok",
  "version": "1.0.0",
  "fallback": {
    "vector_store": "chroma",
    "vector_store_persistent": true,
    "mode": "full",
    "boot_id": "987ee79b4819"
  }
}
```

`status` jadi `degraded` kalau ada komponen yang tidak terjangkau. Endpoint
ini harus menjawab dalam waktu pendek dan tidak boleh menyentuh LLM, karena
dipakai monitor.

Field `fallback` memberi tahu mode apa yang sedang aktif, bukan sekadar
"sehat atau tidak". `mode: "reduced"` berarti salah satu komponen berjalan
dalam mode fallback (misalnya vector store in-memory yang hilang saat
restart), dan operator tidak boleh mengira data sudah persisten padahal belum.

### `fallback.embedding_mismatch`

Field ini **hanya ada kalau ada masalah**, dan isinya pesan siap tampil:

```json
{
  "embedding_mismatch": "Koleksi 'chunks' diindeks dengan 'sentence-transformers:model-a', sedangkan yang aktif sekarang 'sentence-transformers:model-b'. Vektor dari model berbeda tidak bisa dibandingkan, jadi hasil pencarian akan ngawur. Jalankan `python -m scripts.reindex`, atau kembalikan EMBEDDING_MODEL ke nilai sebelumnya lalu unggah ulang dokumen."
}
```

Kapan muncul: saat model embedding yang dipakai saat indexing berbeda dari
yang aktif sekarang. Ini terjadi kalau `EMBEDDING_MODEL` diganti, atau kalau
`USE_LOCAL_EMBEDDING` diubah.

Kenapa penting: vektor dari model berbeda tidak bisa dibandingkan, dan
Chroma tidak tahu itu. Retrieval tetap berjalan tanpa error, tapi jawabannya
ngawur atau selalu "tidak ditemukan". Tanpa field ini, satu-satunya petunjuk
ada di log server, dan gejalanya mudah disalahartikan sebagai "dokumennya
aneh".

`status` ikut menjadi `degraded` saat field ini ada. Frontend menampilkannya
di header dengan gaya bahaya, bukan peringatan biasa, karena akibatnya lebih
serius daripada mode terbatas.

**Isinya sengaja terbatas.** Endpoint ini publik, dipanggil healthcheck dan
halaman login sebelum sesi ada. Yang dikirim hanya yang benar-benar dipakai
frontend: `mode` dan `vector_store_persistent` untuk peringatan "mode
terbatas" di header, `boot_id` untuk mendeteksi backend yang dijalankan
ulang. Nama repository, memory store, provider LLM, dan model embedding
**tidak** dikirim ke sini, karena itu memberi penyerang peta komponen
internal tanpa satu pun dipakai UI. Detail itu ada di log server saat
startup, tempat yang memang hanya bisa dibaca operator.

---

## 9. Zona waktu

Semua timestamp dari server dalam **UTC** dengan format ISO 8601 berakhiran
`Z`. Bucket harian pada `latency` dan `tokens` memakai `YYYY-MM-DD` dalam UTC.

Frontend memformatnya ke zona waktu browser pengguna, di satu helper saja
(`formatDateTime` dan `formatDay` di `src/lib/format.ts`), supaya sumbu chart,
timestamp di log, dan waktu unggah tidak pernah berbeda tanggal karena
masing-masing punya formatter sendiri.

Konsekuensi yang perlu diingat: bucket harian dihitung per hari UTC, jadi
untuk pengguna di UTC+7 atau lebih, sebagian data sebuah hari bisa masuk ke
dua bucket berbeda. Kalau ini mengganggu, perbaikannya di backend dengan
menggeser batas bucket ke zona waktu pelapor, **bukan** dengan menggeser
formatter di frontend.

---

## 10. Yang belum diputuskan

1. **`trace_id` di backend.** Bentuknya sudah ditetapkan di Section 7, tapi
   backend belum tentu mengisinya. Kalau RAGAS dan Langfuse belum terhubung,
   kolomnya akan `null` seluruhnya.
2. **Cache hit di UI.** `from_cache` sudah ada di kontrak tapi belum
   ditampilkan. Kalau nanti ditampilkan, harus jelas bedanya dari query biasa,
   karena "dari cache" memengaruhi perhitungan latency yang dilihat pengguna.
3. **Identitas pengguna.** Saat ini hanya satu passcode, jadi endpoint
   `chat/sessions` tidak punya parameter user. Kalau nanti ada multi-user,
   semua endpoint ini butuh scoping per user.

---

*Dokumen ini adalah living document, ikut berubah bersama kode.*
