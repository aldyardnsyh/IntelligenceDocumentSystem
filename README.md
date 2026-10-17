# Intelligent Document Assistant

<!-- Stack teknologi. Versinya disamakan dengan pyproject.toml dan
     package.json, jadi badge ini ikut berubah saat dependency diperbarui. -->
[![Next.js](https://img.shields.io/badge/Next.js-16.4.0-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org)
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
     bukan klaim. Badge CI diambil langsung dari hasil GitHub Actions, jadi
     kalau ada yang rusak, badge-nya merah. -->
[![CI](https://github.com/aldyardnsyh/IntelligenceDocumentSystem/actions/workflows/ci.yml/badge.svg)](https://github.com/aldyardnsyh/IntelligenceDocumentSystem/actions/workflows/ci.yml)
[![pytest](https://img.shields.io/badge/pytest-434_passed-0A9EDC?logo=pytest&logoColor=white)](#verifikasi-dan-pengujian)
[![Playwright](https://img.shields.io/badge/Playwright-46_specs-2EAD33?logo=playwright&logoColor=white)](#verifikasi-dan-pengujian)
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
- [Keamanan](#keamanan)
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
python -m pytest                 # 434 test, coverage gate 70%
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

46 skenario Playwright yang mencakup login, unggah tiga format berkas, tanya
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
server dengan Caddy untuk TLS otomatis dan volume persisten. Tidak perlu
Supabase, Redis, atau object storage. Kodenya tidak terikat penyedia
tertentu, jadi VPS apa pun dengan Docker bisa dipakai.

### Kebutuhan minimum

| Komponen | RAM |
|---|---|
| Ubuntu dan Docker | ~300 MB |
| FastAPI dan ChromaDB | ~250 MB |
| torch saat dimuat | ~600 MB |
| Model embedding | ~470 MB |
| **Total** | **~1,6 GB** |

Jadi **2 GB RAM sudah cukup**. Dengan 1 GB, aplikasi tetap jalan tapi wajib
swap. Disk: sekitar 9 GB untuk sistem dan build cache, jadi 20 GB cukup dan
40 GB lebih lega.

### Cara cepat: satu skrip

Ada skrip yang mengerjakan seluruh langkah di bawah secara berurutan. Cocok
dipakai dari terminal web penyedia (OrcaTerm di Tencent), tanpa perlu SSH
dari komputer sendiri.

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/aldyardnsyh/IntelligenceDocumentSystem.git /opt/ida
cd /opt/ida/backend
bash scripts/setup-vps.sh
```

Skripnya menanyakan domain, email, passcode, dan Groq API key, lalu
mengerjakan sisanya: swap, Docker, konfigurasi, build, dan verifikasi.
Aman dijalankan ulang, dan konfigurasi yang sudah ada tidak ditimpa tanpa
bertanya.

Domain boleh nama apa saja, asalkan sudah mengarah ke IP server. Kalau belum
punya, <https://www.duckdns.org> memberi subdomain gratis, misalnya
`intelligencedocumentassistant.duckdns.org`. Cukup isi kolom `current ip`
dengan IP server lalu klik **update ip**.

Satu hal yang **harus** Anda lakukan sendiri di panel penyedia: **buka port
80 dan 443 di firewall**. Skrip tidak bisa menutupnya karena firewall-nya
ada di luar server, dan ini penyebab kegagalan yang paling sering.

### Ringkasan langkah manual

| Langkah | Yang dilakukan |
|---|---|
| 1 | Siapkan server, Ubuntu 24.04 |
| 2 | Buka firewall: hanya port 80 dan 443 |
| 3 | Siapkan domain. Bisa domain sendiri, atau DuckDNS gratis. Nama bebas |
| 4 | Swap (wajib kalau RAM 1 GB), pasang Docker, buat passcode, isi `.env` |
| 5 | Ganti domain di `backend/Caddyfile` |
| 6 | `docker compose up -d --build`, tunggu 5 sampai 15 menit |
| 7 | Verifikasi: health check, TLS, lalu unggah dokumen contoh dan tanya |

Tiga hal yang paling sering terlewat:

1. **Port 80 dan 443 di firewall penyedia.** Gejalanya menyesatkan: semua
   container sehat, API menjawab dari dalam server, tapi situs tidak bisa
   dibuka dan log Caddy penuh percobaan ACME yang gagal.
2. **Swap kalau RAM 1 GB.** Aplikasi ini butuh sekitar 1,6 GB. Tanpa swap,
   kernel akan membunuh container saat ingestion. Dengan RAM 2 GB, swap
   tidak wajib tapi tetap disarankan sebagai jaring pengaman.
3. **Domain di `Caddyfile`.** Nilai bawaannya `example.com` milik IANA, dan
   sertifikat TLS tidak akan pernah terbit untuk domain itu.

**Vercel tidak bisa dipakai untuk backend.** Batas bundle Hobby 250 MB,
sedangkan `torch` sendiri 1.260 MB, dan Vercel tidak punya disk persisten
untuk SQLite dan ChromaDB. Domain `*.vercel.app` juga tidak bisa diarahkan
ke server lain. Penjelasan lengkapnya ada di `backend/README.md`.

## Struktur proyek

```
frontend/             Next.js 16 + React 19 + Tailwind v4 (9 halaman)
frontend/e2e/         46 skenario Playwright
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
| Test backend | `python -m pytest` | 434 test, coverage 83% |
| Lint backend | `python -m ruff check app tests scripts` | Bersih |
| Tipe dan lint frontend | `npx next typegen; npx tsc --noEmit; npm run lint` | Bersih |
| Build frontend | `npm run build` | Sukses |
| Uji browser | `npx playwright test` | 46 skenario |
| Uji ujung ke ujung | `python -m scripts.e2e_check` | 21 pemeriksaan |

Empat baris pertama juga dijalankan otomatis oleh GitHub Actions pada
setiap push, jadi angkanya tidak bisa basi tanpa badge CI ikut merah.

Cara menjalankan semuanya ada di bagian
[Verifikasi dan pengujian](#verifikasi-dan-pengujian).

## Keamanan

Yang sudah ditangani, dan alasannya:

| Area | Penanganan |
|---|---|
| Passcode | Dibandingkan sebagai SHA-256 dengan `hmac.compare_digest`, jadi selisih waktu tidak membocorkan berapa karakter yang cocok |
| Panjang passcode | Minimal 12 karakter, ditolak oleh `scripts.make_passcode`, bukan hanya disarankan |
| Sesi | Token acak 32 byte, disimpan di server, dicabut saat logout. Cookie `HttpOnly`, `SameSite=Lax`, `Secure` mengikuti skema permintaan |
| Rate limit login | 5 percobaan per 5 menit per IP, dengan header `Retry-After` |
| CORS | Origin harus disebut satu per satu. `*` ditolak saat start, karena aplikasi ini memakai cookie sesi |
| Kepemilikan sesi | Percakapan diikat ke token yang membuatnya. ID saja tidak cukup untuk membuka riwayat orang lain |
| Path traversal | Nama berkas disanitasi di server. Berkas asli disimpan dengan nama dari ID dokumen, bukan nama dari klien |
| SQL injection | Semua nilai lewat parameter binding. Nama kolom di `UPDATE` diambil dari daftar putih |
| XSS | Nama berkas dibersihkan dari markup di server. Frontend tidak memakai `dangerouslySetInnerHTML` |
| Prompt injection | Isi dokumen diberi penanda batas, dan prompt sistem menyatakan bahwa konteks adalah data, bukan instruksi |
| PDF berbahaya | Batas 10 MB, batas 3000 halaman, dan batas waktu 120 detik per dokumen |
| Ukuran unggahan | Dibatasi tiga lapis: 16 MB di Caddy, `Content-Length` di route, lalu pembacaan bertahap |
| Kuota penyimpanan | Maksimal 200 dokumen dan 1 GB total. Ditolak dengan 507 dan pesan yang menyebut tindakannya |
| Kuota permintaan | Dikunci ke identitas stabil (hash passcode), bukan token sesi, supaya login ulang tidak mereset kuota |
| Indeks tidak cocok | Model embedding dicatat saat indexing. Kalau berbeda saat start, status `degraded` dan pesannya menyebut perintah perbaikan |
| Open redirect | `?next=` divalidasi dengan daftar karakter yang diizinkan, lalu dicek lagi hasil resolusi URL-nya |
| Clickjacking | `X-Frame-Options: SAMEORIGIN` dan `frame-ancestors 'self'`. SAMEORIGIN, bukan DENY, karena pratinjau PDF memakai iframe same-origin |
| Dokumentasi API | `/docs`, `/redoc`, dan `/openapi.json` mati secara default, dinyalakan bersama lewat `API_DOCS_ENABLED=1` |
| Endpoint publik | `/health` hanya mengirim `mode`, `vector_store`, `boot_id`. Nama repository, memory store, provider LLM, dan model embedding hanya ada di log server |
| Error | Pesan 500 selalu generik. Detail aslinya hanya masuk log server |

Konfigurasi yang berbahaya dicatat di log saat startup, bukan dibiarkan lewat
tanpa jejak: `DEBUG=true`, provider `mock`, passcode yang belum diisi,
dokumentasi API yang dinyalakan, dan origin `http://` untuk host non-lokal.

Audit dependensi:

```bash
# Frontend. Yang penting: nol kerentanan di dependency runtime.
npm audit --omit=dev

# Backend.
python -m pip install pip-audit
python -m pip_audit
```

`npm audit --omit=dev` bersih. Yang tersisa di `npm audit` penuh semuanya
berada di alat pengembangan (`shadcn` beserta rantai `fast-glob`), dan
paket-paket itu tidak ikut ke image produksi. `shadcn` juga sudah dipindahkan
ke `devDependencies` supaya batas itu terlihat jelas.

Sebelum menaruh aplikasi ini di internet, periksa daftar berikut:

| Setelan | Nilai yang benar |
|---|---|
| `DEBUG` | `false` |
| `CORS_ORIGINS` | Domain Anda, tanpa `*` |
| `ACCESS_PASSCODE_SHA256` | Diisi, dibuat dengan `python -m scripts.make_passcode` |
| `API_DOCS_ENABLED` | `0`, kecuali ini demo publik |
| `LLM_PROVIDER` | `groq` atau `ollama`, bukan `mock` |
| `TRUST_PROXY_HEADERS` | `1` kalau di balik Caddy, `0` kalau tidak |
| `NEXT_PUBLIC_DEV_PASSCODE_HINT` | Kosong |

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
| Reranking mati secara default | Mengukur dulu sebelum menyalakan: ketepatan posisi pertama naik 4/11 ke 7/11, tapi menambah 80 MB model dan latensi. Dipakai kalau kualitas lebih penting daripada kecepatan |
| Heading digabung dengan paragraf berikutnya | Chunk yang isinya hanya judul tidak bisa menjawab apa pun, dan paragraf di bawahnya kehilangan konteks |
| Kunci kuota dari hash passcode, bukan token | Token berganti setiap login, jadi bucket ikut baru dan kuota bisa direset dengan login ulang |

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
