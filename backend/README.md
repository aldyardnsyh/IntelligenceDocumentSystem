# Backend — Intelligent Document Assistant

FastAPI untuk ingestion dokumen, retrieval hybrid, dan generasi jawaban
berantai sitasi. Dijalankan sendiri, atau di dalam Docker.

---

## Ringkas arsitektur

```
Upload ──► parse (PDF/TXT/MD) ──► chunk (paragraf-kalimat) ──► embed (lokal)
                                                                    │
                        ┌───────────────────────────────────────────┘
                        ▼
    Retrieval: vektor (Chroma) + BM25 (in-process) ──► RRF ──► ambang
                        │
                        ▼
   Gate "tidak ditemukan" ──► kalau lolos: prompt terikat kutipan ──► LLM
                        │                                              │
                        └──── dokumen tidak ada? jangan pernah LLM ◄─────┘
```

Dua hal yang menentukan apakah sistem ini bisa dipercaya:

1. **LLM tidak pernah dipanggil tanpa konteks.** Kalau tidak ada chunk yang
   lolos ambang, jawabannya "tidak ditemukan" — bukan karangan.
2. **Ambang dinilai pada bukti mentah**, bukan pada skor RRF. Skor RRF
   dinormalisasi terhadap kandidat terbaik sehingga selalu bernilai 1.0 di
   puncak; ambang yang dipasang di sana tidak akan pernah menolak apa pun.

## Yang dipakai, dan yang sengaja tidak

| Kebutuhan | Yang dipakai | Kenapa bukan yang lain |
|---|---|---|
| Metadata | **SQLite** | Supabase/Turso hanya relevan saat multi-instance. Satu instance cukup. |
| Vektor | **ChromaDB** di disk | Untuk ribuan chunk, brute-force di Python sudah cukup cepat. |
| Memori sesi | **Dict in-process** | Redis menyelesaikan masalah "banyak instance berbagi state". Tidak ada banyak instance. |
| Embedding | **multilingual-e5-small** lokal | Model Inggris-first seperti all-MiniLM jauh lebih buruk untuk Bahasa Indonesia. |
| LLM | **Groq / Ollama**, bisa fallback | Satu provider saja berarti satu titik gagal. |

Menambah layanan untuk kebutuhan yang belum ada berarti menambah biaya
operasional dan tempat gagal diam-diam. Semua opsi di atas bisa diganti lewat
satu variabel env tanpa menyentuh kode.

---

## Menjalankan lokal

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

Copy-Item .env.example .env
python -m scripts.make_passcode          # menghasilkan ACCESS_PASSCODE_SHA256

python -m uvicorn app.main:app --reload --port 8000
```

Dokumentasi API interaktif: <http://localhost:8000/docs>

### Embedding lokal butuh unduhan model sekali

Saat start pertama, `intfloat/multilingual-e5-small` (~470 MB) diunduh dari
Hugging Face dan disimpan di cache. Setelah itu jalan offline.

Kalau tidak ingin mengunduhnya, set `USE_LOCAL_EMBEDDING=0`. Sistem tetap
jalan dengan embedding berbasis hashing — **dan `/api/v1/health` akan
melaporkan itu**, karena retrieval hanya cocok untuk kata yang identik.

## Menjalankan dengan Docker

```powershell
Copy-Item .env.example .env
python -m scripts.make_passcode

docker compose up -d --build
docker compose logs -f api
```

## Deployment ke AWS EC2 (free tier)

Shape EC2 yang dipakai: **satu** instance dengan disk persisten.
Semua state ada di satu volume, jadi tidak ada database eksternal.

### 1. Buat instance

Di konsol AWS → EC2 → Launch instance:

| Pengaturan | Nilai |
|---|---|
| Name | `ida-rag` |
| AMI | Ubuntu 24.04 LTS (x86_64) |
| Instance type | **t3.small** (2 vCPU, 2 GB) — atau `t3.micro` (1 GB) kalau ketat |
| Key pair | Buat baru, atau pilih yang sudah ada |
| Storage | **gp3, 20 GB** |

>`t3.micro` (1 GB) cukup kalau `USE_LOCAL_EMBEDDING=0`. Dengan embedding
> sungguhan, pakai `t3.small`.

### 2. Security group

Inbound: **Hanya HTTP (80) dan HTTPS (443)**, source `0.0.0.0/0`.
Port 8000 **jangan** dibuka — API hanya dijangkau lewat Caddy.

### 3. Arahkan domain

Point DNS `A` record ke **Public IPv4** instance. Tanpa domain, Caddy tidak
bisa menerbitkan sertifikat TLS.

### 4. Siapkan server

```bash
ssh -i <key>.pem ubuntu@<ip-EC2>

sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker

git clone <repo> ida && cd ida/backend
cp .env.example .env

# Hash passcode. Dijalankan lewat container karena skripnya butuh pydantic,
# sedangkan server Ubuntu yang polos belum punya itu.
docker compose run --rm api python -m scripts.make_passcode --stdin
```

Edit `.env` minimal pada ini:

```ini
ACCESS_PASSCODE_SHA256=<hash-dari-skrip>
LLM_PROVIDER=groq
GROQ_API_KEY=<key-anda>
# atau, kalau mau lokal:
# LLM_PROVIDER=ollama
CORS_ORIGINS=https://domain-anda
DEBUG=false
```

### 5. Jalankan

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f api
```

Caddy mendapatkan dan memperbarui sertifikat Let's Encrypt otomatis dalam satu menit setelah container berjalan.

### 6. Verifikasi

```bash
curl https://domain-anda/api/v1/health
```

`"status": "ok"` berarti semua komponen hidup. Field `fallback` memberi tahu
storage mana yang aktif — kalau `vector_store_persistent` false, indeks akan
 hilang saat restart.

### 7. Deploy ulang

```bash
git pull
docker compose up -d --build
```

---

## Yang perlu dipelihara

Hampir tidak ada. Yang perlu Anda ingat cuma satu:

> **Jangan pernah menghapus volume `ida-data`.** Di situ metadata SQLite dan
> indeks ChromaDB berada. Menghapus volume = kehilangan seluruh dokumen.

Backup sekali sebulan cukup:

```bash
docker run --rm -v ida_ida-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/ida-$(date +%F).tar.gz -C /data .
```

## Command harian

| Tujuan | Command |
|---|---|
| Lihat log | `docker compose logs -f api` |
| Restart setelah ubah env | `docker compose up -d --force-recreate api` |
| Status komponen | `curl localhost:8000/api/v1/health` |
| Buka shell di container | `docker compose exec api bash` |
| Ganti passcode | `docker compose run --rm -T api python -m scripts.make_passcode --stdin` lalu `up -d --force-recreate api` |

## Test

```powershell
pip install -e ".[dev]"
pytest                    # 291 test, coverage gate 70%
ruff check app tests      # lint
```

Test memakai stub untuk embedding, LLM, dan storage yang berat, sehingga
tidak mengunduh model dan tidak butuh API key. Pipeline tetap dijalankan
utuh dari parsing sampai streaming SSE.

## Evaluasi kualitas retrieval

```powershell
pip install -e ".[evaluation]"
python -m scripts.evaluate_ragas --dataset evaluation/dataset.json
```

Dataset berisi 11 pertanyaan: 8 yang harus terjawab benar, dan 3 yang
**harus** dijawab "tidak ditemukan". Tiga yang terakhir itu yang paling berguna — di situ yang diukur apakah sistem mengarang saat tidak tahu.

Untuk melihat jawaban dan konteks tanpa menghitung skor:

```powershell
python -m scripts.evaluate_ragas --dry-run
```

## Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| `401` di semua request | Cookie `ida_session` tidak sampai | Pastikan frontend pakai rewrite proxy (`BACKEND_ORIGIN` di `.env.local`) |
| Semua pertanyaan "tidak ditemukan" | Indeks retrieval kosong | `docker compose restart api`; log akan menyebut jumlah chunk yang dipulihkan |
| Container restart berulang | RAM habis | Pakai `t3.small`, atau `USE_LOCAL_EMBEDDING=0` |
| Caddy tidak terbit sertifikat | DNS belum Resolve | Cek `dig +short domain-anda`; harus menunjuk ke IP instance |
| `Set-Cookie` tidak terkirim | Browser bicara langsung ke backend | Set `NEXT_PUBLIC_API_BASE_URL=` (kosong) di frontend, biar lewat proxy |
