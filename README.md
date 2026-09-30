# Intelligent Document Assistant

Tanya-jawab berbasis dokumen (RAG) dengan sitasi yang bisa ditelusuri.
Upload PDF/TXT/Markdown, bertanya dalam Bahasa Indonesia, dapat jawaban
dengan sumber yang bisa diklik -- atau jawaban jujur "tidak ditemukan"
kalau dokumennya tidak memuat itu.

```
Upload ──► parse ──► chunk ──► embed ──► retrieval hybrid ──► gate ──► LLM + sitasi
                                                        │
                                              tidak lolos? ──► "tidak ditemukan"
```

Dua aturan yang menentukan apakah sistem ini bisa dipercaya:

1. **LLM tidak pernah dipanggil tanpa konteks.** Tidak ada chunk yang lolos
   ambang berarti tidak ada panggilan LLM -- dan itu sumber halusinasi paling
   umum yang dihilangkan.
2. **Frontend tidak pernah menebak.** Setiap angka yang ditampilkan (chunk
   count, threshold, latency, token) berasal dari API, bukan placeholder.

## Struktur

```
frontend/          Next.js 16 + React 19 + Tailwind v4 (9 halaman)
backend/           FastAPI + ChromaDB + SQLite + Groq/Ollama
Design/            Mockup referensi (11 layar)
PRD-SRS_*.md       Spesifikasi kebutuhan (sumber kebenaran fungsional)
API-CONTRACT.md    Kontrak endpoint frontend-backend
design.md          Spesifikasi desain UI
```

## Mulai cepat (5 menit, tanpa backend)

Frontend jalan sendiri dengan fixture lokal -- cukup untuk melihat semua halaman:

```powershell
cd frontend
npm install
npm run dev
```

Buka <http://localhost:3000>. Banner "Mode demo" berarti data dari fixture,
bukan backend.

## Menjalankan penuh (frontend + backend)

```powershell
# Terminal 1 -- backend
cd backend
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
python -m scripts.make_passcode
python -m uvicorn app.main:app --port 8000

# Terminal 2 -- frontend
cd frontend
npm install
Copy-Item .env.example .env.local
# .env.local: NEXT_PUBLIC_USE_BACKEND=1, BACKEND_ORIGIN=http://127.0.0.1:8000
npm run dev
```

Lalu isi database contoh:

```powershell
cd backend
python -m scripts.seed_demo
```

Tanyakan di /chat: *"berapa hari untuk penyelesaian permintaan?"*

## Deployment (AWS EC2, free tier)

Lihat **[backend/README.md](backend/README.md)** -- langkah EC2 + TLS otomatis
dengan Caddy, satu instance dengan volume persisten. Tidak perlu Supabase,
Redis, atau object storage untuk setup ini; ketiganya hanya relevan kalau
nanti diskalakan ke banyak instance.

## Verifikasi

```powershell
# Backend: 291+ test, coverage gate 70%, lint bersih
cd backend
pytest
ruff check app tests scripts

# E2E lewat proxy frontend sungguhan (butuh kedua server hidup)
python -m scripts.e2e_check

# Frontend
cd ../frontend
npx tsc --noEmit; npm run lint; npm run build
```

## Evaluasi kualitas retrieval

```powershell
cd backend
pip install -e ".[evaluation]"
python -m scripts.evaluate_ragas --dataset evaluation/dataset.json
```

Dataset berisi 11 pertanyaan: 8 harus terjawab benar, 3 **harus** dijawab
"tidak ditemukan". Tiga yang terakhir itu yang paling berguna -- di situlah
diukur apakah sistem mengarang saat tidak tahu.

## Keputusan arsitektur penting

| Keputusan | Alasan singkat |
|---|---|
| SQLite default, bukan Supabase | Satu instance tidak butuh database terkelola |
| Dict in-process, bukan Redis | Redis untuk banyak instance; tidak ada banyak instance |
| `multilingual-e5-small`, bukan MiniLM | Model Inggris-first jauh lebih buruk untuk Bahasa Indonesia |
| Ambang pada bukti mentah, bukan RRF | Skor RRF selalu punya pemenang 1.0, jadi ambang di sana mati |
| Proxy same-origin, bukan CORS | `Set-Cookie` login hilang kalau beda origin |

Detail lengkap ada di komentar kode -- setiap angka dan pilihan yang tidak
langsung jelas dijelaskan "mengapa"-nya di tempat ia dipakai.
