# Intelligent Document Assistant

<!-- Stack teknologi. Versinya disamakan dengan pyproject.toml dan
     package.json, jadi badge ini ikut berubah saat dependency diperbarui. -->
[![Next.js](https://img.shields.io/badge/Next.js-16.3.7-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![React](https://img.shields.io/badge/React-19.2-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-0.6+-FF6B35)](https://www.trychroma.com)
[![SQLite](https://img.shields.io/badge/SQLite-metadata-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org)
[![Groq](https://img.shields.io/badge/Groq-LLM-F55036)](https://groq.com)
[![Ollama](https://img.shields.io/badge/Ollama-fallback-000000?logo=ollama&logoColor=white)](https://ollama.com)

<!-- Status kualitas. Angkanya berasal dari perintah di bagian verifikasi,
     bukan klaim. -->
[![pytest](https://img.shields.io/badge/pytest-403_passed-0A9EDC?logo=pytest&logoColor=white)](#verifikasi-dan-pengujian)
[![Playwright](https://img.shields.io/badge/Playwright-39_specs-2EAD33?logo=playwright&logoColor=white)](#verifikasi-dan-pengujian)
[![coverage](https://img.shields.io/badge/coverage-83%25-4C1)](#verifikasi-dan-pengujian)
[![Lisensi](https://img.shields.io/badge/lisensi-PSHT-blue)](LICENSE.md)

Asisten tanya jawab untuk dokumen pribadi Anda. Unggah berkas PDF, TXT, atau
Markdown, lalu ajukan pertanyaan dalam Bahasa Indonesia dan dapatkan jawaban
yang disertai sumber yang bisa diklik.

Yang membedakan aplikasi ini dari sekadar chatbot: sistem **tidak mengarang**.
Kalau jawabannya tidak ada di dokumen Anda, sistem mengatakannya terus terang.
Kalau Anda mengizinkan mode pengetahuan umum, jawabannya diberi label tegas
supaya tidak tertukar dengan jawaban yang bersumber dokumen.

## Cara kerjanya

```
Unggah -> parse -> potong jadi chunk -> embedding -> pencarian hybrid
                                                            |
                                                    ada yang lolos?
                                                      |          |
                                                     ya         tidak
                                                      |          |
                                          jawaban + sitasi   pilihan Anda:
                                                             tolak menjawab,
                                                             atau jawab dari
                                                             pengetahuan umum
                                                             dengan label
```

Tiga aturan yang menjaga sistem ini bisa dipercaya:

1. **Jawaban tanpa konteks tidak pernah diberi sitasi.** Kalau tidak ada
   potongan dokumen yang cukup mirip, sistem tidak berpura-pura menemukannya.
2. **Setiap dokumen bisa punya percakapan privatnya sendiri.** Sesi ber-scope
   hanya mencari di dokumen itu. Sesi lintas dokumen tetap tersedia.
3. **Semua angka berasal dari server.** Jumlah chunk, ambang kemiripan,
   latensi, dan token semuanya hasil pengukuran, bukan nilai contoh.

## Daftar isi

- [Coba tanpa backend (2 menit)](#coba-tanpa-backend-2-menit)
- [Jalankan lengkap (backend + frontend)](#jalankan-lengkap-backend--frontend)
- [Dokumen contoh untuk pengujian](#dokumen-contoh-untuk-pengujian)
- [Cara memakai fitur utamanya](#cara-memakai-fitur-utamanya)
- [Verifikasi dan pengujian](#verifikasi-dan-pengujian)
- [Deployment ke server](#deployment-ke-server)
- [Struktur proyek](#struktur-proyek)
- [Kualitas dan pengujian](#kualitas-dan-pengujian)
- [Keputusan teknis penting](#keputusan-teknis-penting)
- [Lisensi](#lisensi)

## Coba tanpa backend (2 menit)

Cara tercepat melihat seluruh halaman. Data berasal dari fixture di browser,
jadi tidak perlu Python maupun API key.

```powershell
cd frontend
npm install
npm run dev
```

Buka <http://localhost:3000>. Banner "Mode demo" akan muncul, artinya data
bukan dari backend. Passcode demo ditampilkan di layar login.

## Jalankan lengkap (backend + frontend)

Butuh Python 3.11 atau lebih baru dan Node.js 20 atau lebih baru.

### Langkah 1: siapkan backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install sentence-transformers
Copy-Item .env.example .env
python -m scripts.make_passcode
```

Perintah terakhir menanyakan passcode pilihan Anda dan menyimpan hash-nya ke
`.env`. Passcode aslinya tidak pernah tersimpan di berkas mana pun.

### Langkah 2: jalankan backend

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

Tunggu sampai muncul `Application startup complete`. Pada start pertama, model
embedding (sekitar 470 MB) diunduh dan disimpan di cache. Ini hanya terjadi
sekali.

Cek dari terminal lain:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Yang diharapkan: `status: ok`, `fallback.mode: full`, dan
`fallback.embedding: sentence-transformers`.

### Langkah 3: siapkan frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
```

Pastikan `.env.local` berisi dua baris ini:

```ini
NEXT_PUBLIC_USE_BACKEND=1
BACKEND_ORIGIN=http://127.0.0.1:8000
```

Kalau ingin passcode dev terlihat di layar login, tambahkan juga:

```ini
NEXT_PUBLIC_DEV_PASSCODE_HINT=passcode-anda
```

### Langkah 4: jalankan frontend

```powershell
npm run dev
```

Buka <http://localhost:3000>, masuk dengan passcode yang Anda buat di Langkah 1,
lalu unggah dokumen pertama Anda.

### Langkah 5: isi database contoh (opsional)

Untuk mencoba cepat tanpa menyiapkan dokumen sendiri:

```powershell
cd backend
python -m scripts.seed_demo
```

Perintah itu membuat satu dokumen SOP contoh, lalu Anda bisa bertanya:
*"berapa hari untuk penyelesaian permintaan?"*

## Dokumen contoh untuk pengujian

Folder `backend/samples/` berisi tiga berkas dengan format berbeda:

| Berkas | Format | Yang diuji |
|---|---|---|
| `kebijakan-cuti.txt` | teks | pemotongan dan pencarian pada teks polos |
| `panduan-tiket-layanan.md` | Markdown | heading menjadi chunk tersendiri |
| `laporan-infrastruktur.pdf` | PDF | ekstraksi teks per halaman |

## Cara memakai fitur utamanya

### Bertanya dan membaca sitasi

1. Buka `/chat`, tulis pertanyaan, tekan Enter.
2. Jawaban muncul mengalir, diikuti kartu sitasi.
3. Klik salah satu kartu untuk membuka dokumen sumbernya di chunk yang tepat.

### Mengatur seberapa ketat pencarian

Buka `/settings`:

- **Top K**: berapa banyak potongan dokumen yang diambil. Semakin besar,
  semakin banyak konteks, tapi jawaban bisa kurang fokus.
- **Ambang kemiripan**: batas minimal skor agar sebuah potongan dipakai.
  Rentang 0.75 sampai 0.92 diukur untuk model embedding yang dipakai. Nilai
  lebih tinggi membuat sistem lebih sering menjawab "tidak ditemukan".

### Percakapan privat per dokumen

Ada dua cara memulai:

- Buka `/documents`, klik **Tanya dokumen ini** pada kartu dokumen.
- Buka `/chat`, pilih dokumen dari daftar di sidebar.

Header akan menampilkan badge nama dokumen. Selama badge itu ada, pencarian
hanya berjalan di dokumen tersebut. Klik **Percakapan baru** untuk kembali ke
mode lintas dokumen.

### Mode jawab tanpa dokumen

Saat jawabannya tidak ada di dokumen Anda, ada dua perilaku yang bisa dipilih
lewat sakelar di bawah kolom pertanyaan:

- **Sakelar menyala** (bawaan): sistem menjawab dari pengetahuan umum model,
  dengan label tegas "Bukan dari dokumen Anda" dan tanpa sitasi.
- **Sakelar mati**: sistem menjawab "tidak ditemukan".

Yang tidak pernah terjadi di kedua mode: jawaban mengarang yang diberi sitasi
seolah-olah bersumber dari dokumen Anda.

### Melihat isi dokumen untuk memeriksa jawaban

Buka `/documents`, pilih salah satu dokumen. Ada dua tab:

- **Pratinjau isi**: berkas aslinya. Untuk PDF, ditampilkan langsung di
  halaman. Untuk teks, isinya ditampilkan berurutan.
- **Chunk hasil ingestion**: bagaimana dokumen dipotong, beserta posisi tiap
  potongan.

Cara memeriksa: buka PDF-nya, cari bagian yang disebut jawaban chat, lalu
bandingkan dengan chunk di tab sebelah. Kalau ada bagian yang terlihat di PDF
tapi tidak muncul di chunk, ekstraksi teksnya yang gagal membaca bagian itu.

### Menjalankan evaluasi kualitas

Buka `/analytics`, pilih dokumen yang ingin diuji, lalu klik **Jalankan
evaluasi**. Sistem menjalankan daftar pertanyaan contoh terhadap dokumen yang
Anda pilih dan melaporkan:

- **Precision**: seberapa tepat sumber yang diambil.
- **Hit rate**: berapa banyak pertanyaan yang menemukan sumbernya.
- **Penolakan benar**: berapa pertanyaan "tidak ada jawaban" yang benar
  ditolak.

Evaluasi ini tidak memerlukan API key tambahan. Untuk skor RAGAS lengkap
(termasuk faithfulness yang dinilai oleh model kedua), lihat bagian
[Evaluasi dengan RAGAS](#evaluasi-dengan-ragas).

## Verifikasi dan pengujian

### Backend

```powershell
cd backend
python -m pytest                 # 403 test, coverage gate 70%
python -m ruff check app tests scripts
```

### Frontend

```powershell
cd frontend
npx tsc --noEmit
npm run lint
npm run build
```

### Uji ujung ke ujung lewat proxy

Butuh kedua server hidup. Skrip ini menguji alur lengkap: login, unggah,
tanya jawab, sitasi, dan mode jawab tanpa dokumen.

```powershell
cd backend
$env:E2E_PASSCODE = "passcode-anda"
python -m scripts.e2e_check
```

### Uji browser otomatis

39 skenario Playwright yang mencakup login, unggah tiga format berkas, tanya
jawab dengan sitasi, penolakan halusinasi, pratinjau PDF, pemilih dokumen di
halaman evaluasi, dan notifikasi.

```powershell
cd frontend
npx playwright test
```

Playwright sengaja tidak menyalakan server sendiri. Jalankan backend dan
frontend lebih dulu di dua terminal terpisah.

## Evaluasi dengan RAGAS

Skor RAGAS butuh model penilai tambahan dan API key dari penyedia model
(misalnya `OPENAI_API_KEY`).

```powershell
cd backend
pip install -e ".[evaluation]"
python -m scripts.seed_demo
python -m scripts.evaluate_ragas --dataset evaluation/dataset.json
```

Dataset berisi 11 pertanyaan: 8 harus terjawab benar, 3 **harus** dijawab
"tidak ditemukan". Kelompok kedua itu yang paling penting, karena di situlah
diukur apakah sistem mengarang saat tidak tahu. Kalau ada pertanyaan yang
seharusnya ditolak tapi justru dijawab, skrip keluar dengan kode error.

## Deployment ke server

Panduan lengkap ada di **[backend/README.md](backend/README.md)**: satu
instance AWS EC2 dengan Caddy untuk TLS otomatis dan volume persisten. Tidak
perlu Supabase, Redis, atau object storage untuk setup satu instance.

Dua hal yang wajib dilakukan sebelum `docker compose up`:

1. Ganti domain di `backend/Caddyfile`. Nilai bawaannya `example.com` milik
   IANA, dan sertifikat TLS tidak akan pernah terbit untuk domain itu.
2. Isi `backend/.env` dengan passcode dan API key Anda.

## Struktur proyek

```
frontend/             Next.js 16 + React 19 + Tailwind v4 (9 halaman)
frontend/e2e/         39 skenario Playwright
frontend/scripts/     Pembuat favicon dari logo aplikasi
backend/              FastAPI + ChromaDB + SQLite + Groq atau Ollama
backend/samples/      Tiga dokumen contoh untuk uji manual
backend/evaluation/   Golden dataset untuk mengukur kualitas retrieval
backend/scripts/      Seed, reindex, uji ujung ke ujung, evaluasi RAGAS
API-CONTRACT.md       Kontrak endpoint frontend dan backend
LICENSE.md            Ketentuan lisensi
```

## Kualitas dan pengujian

Angka di badge atas bukan klaim, tapi hasil perintah berikut:

| Pemeriksaan | Perintah | Hasil |
|---|---|---|
| Test backend | `python -m pytest` | 403 test, coverage 83% |
| Lint backend | `python -m ruff check app tests scripts` | Bersih |
| Tipe dan lint frontend | `npx tsc --noEmit; npm run lint` | Bersih |
| Build frontend | `npm run build` | Sukses |
| Uji browser | `npx playwright test` | 39 skenario |
| Uji ujung ke ujung | `python -m scripts.e2e_check` | 20 pemeriksaan |

Cara menjalankan semuanya ada di bagian
[Verifikasi dan pengujian](#verifikasi-dan-pengujian).

## Keputusan teknis penting

| Keputusan | Alasan |
|---|---|
| SQLite, bukan database terkelola | Satu instance tidak butuh database terpisah |
| Penyimpanan sesi in-process, bukan Redis | Redis dibutuhkan saat banyak instance; di sini hanya satu |
| `multilingual-e5-small`, bukan model Inggris | Model Inggris jauh lebih buruk untuk Bahasa Indonesia |
| Ambang 0.82, bukan 0.5 | Diukur untuk model ini: teks tidak relevan pun berskor 0.72 sampai 0.81, jadi ambang rendah membuatnya lolos |
| Jawaban tanpa konteks diberi label | Pengguna tetap mendapat jawaban, tapi tidak tertukar dengan yang bersumber dokumen |
| Scope dokumen disimpan di sesi | Sesi yang dibuka ulang mencari di tempat yang sama tanpa perlu diingat frontend |
| Ambang dinilai pada bukti mentah, bukan skor gabungan | Skor gabungan selalu punya nilai tertinggi 1.0, sehingga ambang tidak akan pernah menolak apa pun |
| Proxy same-origin, bukan CORS | Cookie login hilang kalau browser dan backend berada di origin berbeda |

Alasan lengkap setiap keputusan ditulis di komentar kode, tepat di tempat
keputusan itu dipakai.

## Line ending

`.gitattributes` menetapkan LF untuk berkas teks, dan CRLF khusus skrip
Windows (`.ps1`, `.bat`, `.cmd`). Sebelumnya repo ini bercampur antara CRLF
dan LF, sehingga perubahan satu baris bisa muncul sebagai diff seluruh berkas.

Kalau Anda menarik perubahan ini di checkout yang sudah ada, jalankan sekali:

```powershell
git add --renormalize .
git commit -m "chore: normalisasi line ending"
```

## Ikon aplikasi

Favicon dibuat dari logo yang sama dengan yang tampil di antarmuka. Berkasnya
`frontend/src/app/favicon.ico`, dibaca otomatis oleh Next.js. Untuk membuat
ulang setelah logo berubah:

```powershell
cd frontend
npm run favicon
```

## Lisensi

Hak cipta (c) 2026 PogungSoftwareHouseTeam (PSHT). Seluruh hak dilindungi.

Kode dalam repositori ini dikembangkan dan dimiliki oleh
PogungSoftwareHouseTeam (PSHT). Detail ketentuan penggunaan ada di
[LICENSE.md](LICENSE.md).

Dependensi pihak ketiga tunduk pada lisensi masing-masing, bukan pada lisensi
ini.
