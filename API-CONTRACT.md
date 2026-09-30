# Kontrak API

Dokumen ini adalah sumber kebenaran bentuk request/response yang dikonsumsi
frontend `frontend/`. Ditolak dari `frontend/src/types/api.ts`, jadi kalau
frontend berubah, dokumen ini harus ikut berubah.

Status tiap endpoint:

| Kolom | Arti |
| --- | --- |
| `Ada di PRD 6.8` | Sudah tercantum di PRD/SRS Section 6.8 |
| `Tambahan` | Dibutuhkan frontend tapi belum tercantum di PRD 6.8 |
| `Hanya lokal` | Dikerjakan Next.js, tidak perlu ada di FastAPI |

---

## 1. Ringkasan endpoint

| Method | Path | Status | Dipakai di |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/verify` | Ada di PRD 6.8 | `login/actions.ts` (hanya saat backend terhubung) |
| GET | `/api/v1/documents` | **Tambahan** | sidebar chat, `/documents` |
| POST | `/api/v1/documents/upload` | Ada di PRD 6.8 | `/documents`, `/chat` |
| GET | `/api/v1/documents/{id}` | **Tambahan** | `/documents/[id]` (metadata saja) |
| GET | `/api/v1/documents/{id}/status` | Ada di PRD 6.8 | polling status ingestion |
| GET | `/api/v1/documents/{id}/chunks` | Ada di PRD 6.8 | `/documents/[id]` (daftar chunk, terpaginasi) |
| DELETE | `/api/v1/documents/{id}` | Ada di PRD 6.8 | `/documents`, `/documents/[id]` |
| POST | `/api/v1/chat/query` | Ada di PRD 6.8 | `/chat` (SSE) |
| GET | `/api/v1/chat/sessions` | **Tambahan** | sidebar chat |
| DELETE | `/api/v1/chat/sessions` | **Tambahan** | `/settings` zona berbahaya |
| PATCH | `/api/v1/chat/sessions/{session_id}` | **Tambahan** | ubah nama satu percakapan |
| DELETE | `/api/v1/chat/sessions/{session_id}` | **Tambahan** | hapus satu percakapan |
| GET | `/api/v1/chat/{session_id}/history` | Ada di PRD 6.8 | `/chat/[sessionId]` |
| DELETE | `/api/v1/chat/{session_id}` | Ada di PRD 6.8 | tersedia, tidak dipakai UI |
| GET | `/api/v1/settings` | Ada di PRD 6.8 | `/settings` |
| PUT | `/api/v1/settings` | Ada di PRD 6.8 | `/settings` (debounce 800 ms) |
| GET | `/api/v1/analytics/summary` | Ada di PRD 6.8 | `/analytics` |
| GET | `/api/v1/analytics/logs` | Ada di PRD 6.8 | `/analytics` |
| GET | `/api/v1/health` | Ada di PRD 6.8 | belum dipakai UI |
| POST | `/api/logout` | **Hanya lokal** | header, route handler Next.js |

### Kenapa tiga endpoint `Tambahan` dibutuhkan

PRD 6.8 belum memuatnya, tapi UI yang sudah ada tidak bisa jalan tanpanya:

- **`GET /api/v1/documents`**. `/documents` dan sidebar `/chat` harus
  menampilkan daftar dokumen beserta statusnya. Tanpa endpoint ini, polling
  status (FR-1.4) tidak punya sumber.
- **`GET /api/v1/documents/{id}`**. `/documents/[id]` butuh metadata dokumen
  dan parameter ingestion sekaligus, supaya angka yang ditampilkan di
  halaman itu bukan konstanta tebakan. Daftar chunk diambil terpisah lewat
  `GET /documents/{id}/chunks` yang sudah ada di PRD, supaya dokumen besar
  tidak mengirim seluruh isinya sekaligus.
- **`GET /api/v1/chat/sessions`**. Sidebar menampilkan "Riwayat Sesi" dengan
  judul otomatis dari pertanyaan pertama. `GET /chat/{id}/history` hanya bisa
  dibaca kalau `id` sudah diketahui, sedangkan daftar id itu belum ada di PRD.
- **`DELETE /api/v1/chat/sessions`**. PRD 6.8 punya reset per sesi
  (`DELETE /chat/{session_id}`), tapi FR-6.3 meminta reset **seluruh** sesi.
  Tidak ada endpoint itu.
- **`PATCH /api/v1/chat/sessions/{session_id}`** dan
  **`DELETE /api/v1/chat/sessions/{session_id}`**. Mengubah nama dan menghapus
  satu percakapan dari sidebar. Perhatikan bahwa `DELETE /chat/{session_id}`
  di PRD 6.8 punya bentuk yang mirip, jadi perbedaan path-nya penting:
  `/chat/sessions/{id}` mengubah judul dan menghapus isi percakapan,
  sedangkan `/chat/{session_id}` hanya mereset memori percakapan itu. Kalau
  keduanya diimplementasikan, router harus tidak menganggap
  `/chat/sessions/...` sebagai `session_id`.

Kalau nanti PRD 6.8 diperbarui, tabel di atas harus ikut diperbarui.

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
| 413 | `file_too_large` | Berkas melewati 10 MB (FR-1.1) |
| 422 | `unprocessable` | Validasi field gagal |
| 429 | `rate_limited` | Rate limit kena. Wajib mengirim header `Retry-After` |
| 5xx | `internal` | Gangguan server, layak dicoba ulang |

Frontend hanya melakukan retry otomatis untuk 408, 5xx, dan kegagalan
jaringan. 404 atau 422 tidak akan membaik dengan dicoba ulang.

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
  (FR-0.3, TC-09: percobaan ke-6 ditolak).
- Cookie sesi: HTTP-only, `SameSite=Lax`, `Secure` di produksi, `Max-Age=86400`
  (FR-0.2).

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
Toleransi: PDF, TXT, MD. Maks 10 MB (FR-1.1).

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
store-nya (FR-1.5). Cache query yang mereferensikan dokumen ikut di-invalidate
(FR-4.2). Jika ada sesi aktif yang menunjuk dokumen itu, hapus juga sitasinya
dari riwayat.

---

## 5. Chat

### `POST /api/v1/chat/query`

`Content-Type: application/json`, `Accept: text/event-stream`.

```json
// request
{ "session_id": "ses_..." | null, "question": "apa isi klausul 14?" }
```

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
| `done` | ya | penanda stream selesai |
| `error` | kalau gagal | `{ "type":"error","message":"...","retry_after_seconds":30 }` |

Aturan yang tidak boleh dilanggar:

- `not_found` dikirim **setelah** retrieval dan **sebelum** panggilan LLM
  (FR-2.3). Kalau `token` sudah sempat terkirim lalu ternyata `not_found`,
  jawabannya terlambat dihentikan.
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
  "message_count": 6
}
```

Urut `last_active_at` menurun. Hanya sesi yang masih hidup di Redis
(FR-3.1, TTL default 1 jam). Sesi yang sudah kedaluwarsa tidak dikembalikan;
frontend menampilkannya sebagai daftar kosong, bukan error.

### `GET /api/v1/chat/{session_id}/history`

```json
{
  "session": { "...": "..." },
  "messages": [
    { "id": "msg_...", "role": "assistant", "content": "...",
      "created_at": "...", "citations": [], "not_found": false }
  ]
}
```

Sesi tidak ada atau sudah kedaluwarsa: `404`. Frontend menampilkan
`ErrorState`, bukan halaman kosong.

### `DELETE /api/v1/chat/sessions`

`204 No Content`. Menghapus seluruh sesi milik pengguna aktif (FR-6.3).
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

- Hapus juga cache query yang involves `session_id` di Redis (FR-4.2).
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

| Parameter | Min | Maks | Default | PRD |
| --- | --- | --- | --- | --- |
| `top_k` | 3 | 10 | 5 | FR-2.1 |
| `similarity_threshold` | 0.50 | 0.90 | 0.50 | FR-2.3 |

Perubahan harus berlaku pada query berikutnya tanpa restart (FR-6.2), jadi
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
menampilkan empty state, bukan angka nol dan bukan angka contoh (TC-12).
Satu-s-satunya sumber angka RAGAS adalah tabel `eval_runs`; jangan
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

**`trace_id`** adalah id trace Langfuse untuk panggilan LLM pada query itu
(PRD Section 12.1). Aturannya:

- `null` kalau tidak ada panggilan LLM: query dijawab dari cache (FR-4.1),
  atau retrieval tidak menemukan apa pun sehingga LLM tidak dipanggil.
- String kosong **tidak boleh** dipakai sebagai pengganti `null`.
- Frontend tidak pernah membuat nilai ini di sisi klien. Kalau kolomnya masih
  kosong setelah RAGAS dan Langfuse terhubung, berarti tracing belum
  dikonfigurasi di backend.

Kolom ini perlu ada di tabel `query_logs` (PRD Section 8.5) sebagai
`trace_id text null`, dengan indeks bila tabel besar. gunanya supaya tabel log
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
    "repository": "sqlite",
    "memory": "in-memory",
    "vector_store": "chroma",
    "vector_store_persistent": true,
    "tracing": false,
    "mode": "full"
  }
}
```

`status` jadi `degraded` kalau ada komponen yang tidak terjangkau. Endpoint
ini harus menjawab dalam waktu pendek dan tidak boleh menyentuh LLM, karena
dipakai monitor.

Field `fallback` memberi tahu mode apa yang sedang aktif -- bukan sekadar
"sehat atau tidak". `mode: "reduced"` berarti salah satu komponen berjalan
dalam mode fallback (misalnya vector store in-memory yang hilang saat
restart), dan operator tidak boleh mengira data sudah persisten padahal belum.
`tracing: false` menjelaskan kenapa kolom Trace di /analytics kosong: bukan
error, memang dimatikan.

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

## 10. Yang belum decided

1. **`trace_id` di backend.** Bentuknya sudah ditetapkan di Section 7, tapi
   backend belum tentu mengisinya. Kalau RAGAS dan Langfuse belum terhubung,
   kolomnya akan `null` seluruhnya.
2. **Cache hit di UI.** `from_cache` sudah ada di kontrak tapi belum
   ditampilkan. Kalau nanti ditampilkan, harus jelas bedanya dari query biasa,
   karena "dari cache" memengaruhi perhitungan latency yang dilihat pengguna.
3. **Identitas pengguna.** PRD 6.0 hanya satu passcode, jadi endpoint
   `chat/sessions` tidak punya parameter user. Kalau nanti ada multi-user,
   semua endpoint ini butuh scoping per user.

---

*Dokumen ini adalah living document, sama seperti PRD/SRS.*
