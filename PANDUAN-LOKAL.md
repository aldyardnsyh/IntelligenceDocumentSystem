# Melihat Hasilnya di Komputer Sendiri

Panduan ini untuk Anda yang ingin **melihat aplikasinya berjalan** sebelum
memasangnya di server. Tidak perlu tahu Docker, tidak perlu akun apa pun.

Ada dua cara, pilih sesuai kebutuhan:

| Cara | Waktu | Yang didapat |
|---|---|---|
| [Cara B: lengkap](#cara-b-lengkap-dengan-backend-30-menit) | 30 menit | Benar-benar menjawab dari dokumen yang Anda unggah |

Cara A (mode demo tanpa backend) sudah dihapus seluruhnya: frontend selalu
berbicara dengan backend FastAPI, jadi satu-satunya jalur menjalankan adalah
Cara B. Sesuai keputusan produk, UI tiruan yang tampil ke pengunjung lebih
merusak daripada pesan error yang jujur.

---

## Jalan pintas: satu perintah

Kalau Anda memakai **Cara B** (dengan backend), ada satu perintah yang
menyiapkan hampir semuanya: membuat `backend/.env`, membuat
`frontend/.env.local`, menyiapkan folder data, dan memeriksa perangkat serta
dependency yang sudah terpasang.

```powershell
cd "<folder-project>"
python scripts/siapkan-lokal.py
```

Perintah itu menampilkan **passcode acak** yang harus Anda catat. Yang disimpan
hanya hash-nya, jadi passcode tidak bisa dilihat lagi setelah itu. Kalau
hilang, buat yang baru dengan `python -m scripts.make_passcode`.

Perintah itu **tidak menimpa** berkas yang sudah ada, jadi aman dijalankan
ulang. Kalau Anda hanya ingin melihat tampilannya tanpa backend, harapkan
`frontend/.env.local` seperti dijelaskan di bawah.

---

## Yang harus ada lebih dulu

| Perangkat | Versi | Cara memeriksa |
|---|---|---|
| Node.js | 20 atau lebih baru | `node --version` |
| Python | 3.11 atau lebih baru | `python --version` |

Node.js diunduh dari <https://nodejs.org> (pilih LTS). Python dari
<https://www.python.org/downloads>. **Saat memasang Python di Windows, centang
"Add Python to PATH"** di layar pertama pemasang. Kalau tidak dicentang,
perintah `python` tidak dikenali, dan itu penyebab kegagalan paling sering.

Cara memeriksa setelah memasang, buka PowerShell lalu jalankan:

```powershell
node --version
python --version
```

Yang benar keluar angka versi, misalnya `v22.19.0` dan `Python 3.11.0`. Kalau
keluar pesan "tidak dikenali" atau "not recognized", tutup PowerShell, buka
lagi, lalu coba sekali lagi. Kalau masih sama, ulangi pemasangan dan pastikan
opsi PATH dicentang.

---

## Cara A: sudah dihapus (mode demo tidak ada lagi)

Mode demo (fixture in-browser) telah dihapus dari kode: tidak ada
`lib/mock`, tidak ada banner "Mode demo", dan tidak ada tombol masuk tanpa
passcode. Frontend menolak menampilkan data tiruan ke pengunjung; tanpa
backend, aplikasi menampilkan pesan error yang jujur. Ikuti Cara B di bawah.

## Cara B: lengkap, dengan backend (30 menit)

Cara ini menyalakan dua bagian: backend yang benar-benar mengindeks dokumen,
dan frontend yang menampilkannya. Inilah bentuk yang sama dengan yang nanti
berjalan di server.

### Kalau login ditolak dengan pesan yang membingungkan

Gejala yang paling sering: halaman login tampil normal, passcode diketik
benar, tetapi selalu gagal tanpa penjelasan. Penyebabnya hampir selalu
konfigurasi, bukan aplikasi. Periksa dengan satu perintah:

```powershell
cd "<folder-project>"
python scripts/cek-kesiapan.py
```

Perintah itu memeriksa dua hal yang paling sering salah:

1. **`backend/.env` ada dan `ACCESS_PASSCODE_SHA256` terisi.** Tanpa nilai itu,
   backend menolak semua passcode dengan 401. Pesannya di log backend berbunyi
   "ACCESS_PASSCODE_SHA256 belum diisi", tetapi mudah tertimpa log request.
2. **Konsistensi `frontend/.env.local`.** Frontend selalu memakai backend
   sungguhan, sehingga backend wajib berjalan.

Kalau ada masalah, perintah itu juga menyebutkan tindakannya.

Anda butuh **dua terminal** yang terbuka bersamaan: satu untuk backend, satu
untuk frontend. Keduanya harus tetap berjalan selama Anda memakai aplikasi.

### Bagian 1: backend (terminal pertama)

#### Langkah 1: masuk ke folder backend

```powershell
cd "<folder-project>\backend"
```

#### Langkah 2: buat lingkungan Python

```powershell
python -m venv .venv
```

Ini membuat folder `.venv` berisi Python terpisah, supaya paket proyek ini
tidak mengganggu Python lain di komputer Anda.

#### Langkah 3: aktifkan lingkungan

```powershell
.\.venv\Scripts\Activate.ps1
```

Setelah berhasil, prompt terminal diawali `(.venv)`.

Kalau muncul pesan tentang *execution policy*, jalankan sekali:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Lalu ulangi Langkah 3.

#### Langkah 4: pasang paket

```powershell
pip install -e ".[dev]"
pip install sentence-transformers
```

Ini mengunduh sekitar 1,5 GB dan butuh 5 sampai 15 menit. Bagian terbesar
adalah `torch`. Kalau koneksi Anda lambat, sediakan waktu lebih.

#### Langkah 5: buat passcode

```powershell
python -m scripts.make_passcode
```

Anda akan diminta mengetik passcode (minimal 12 karakter). Ketikan tidak
terlihat di layar, itu normal. Hasilnya berupa satu baris panjang:

```
ACCESS_PASSCODE_SHA256=a1b2c3d4...
```

**Salin baris itu**, Anda butuh di langkah berikutnya.

#### Langkah 6: buat berkas konfigurasi

```powershell
Copy-Item .env.example .env
```

Buka `backend/.env` dengan Notepad, lalu ganti baris berikut:

```ini
ACCESS_PASSCODE_SHA256=isi-dengan-hash-dari-langkah-5
LLM_PROVIDER=mock
```

Penjelasan dua baris itu:

- **`ACCESS_PASSCODE_SHA256`**: hash dari passcode Anda, supaya passcode asli
  tidak pernah disimpan.
- **`LLM_PROVIDER=mock`**: jawaban disusun dengan menyalin kutipan dokumen,
  bukan dengan model bahasa. Ini pilihan yang tepat untuk mencoba: tanpa
  API key, tanpa biaya, dan jawabannya tetap bersumber dokumen. Kalau nanti
  ingin jawaban yang disintesis model, ganti menjadi `groq` dan isi
  `GROQ_API_KEY` dari <https://console.groq.com/keys>.

Satu hal lagi yang patut disetel sejak awal: **OCR lokal untuk PDF hasil
pindai**. Pasang ekstra OCR sekali saja:

```powershell
pip install -e ".[ocr]"
```

Dengan `OCR_ENGINE=auto` (bawaan), halaman yang text-layer-nya tipis atau
rusak dirender ke gambar lalu ditranskripsi PP-OCR secara lokal — tanpa API
key dan tanpa biaya. PDF dengan text-layer bagus tetap diproses cepat tanpa
OCR. Kalau ingin memaksa seluruh jalur tetap lokal, set `OCR_ENGINE=paddle`.

Model vision dari Groq hanya dipakai sebagai penyelamat ketika keyakinan OCR
lokal rendah. Opsional:

```ini
VISION_PROVIDER=groq
# GROQ_API_KEY sama dengan yang dipakai LLM_PROVIDER=groq di atas.
```

Bila ekstra OCR belum dipasang dan vision juga tidak dikonfigurasi, halaman
hasil pindai akan terindeks dengan teks minim. Semua opsi lengkapnya ada di
`backend/.env.example`.

Simpan berkasnya.

#### Langkah 7: jalankan backend

```powershell
python -m uvicorn app.main:app --port 8000
```

Tunggu sampai muncul:

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

Pemuatan pertama bisa 1 sampai 2 menit karena model embedding diunduh. Itu
sekali saja; berikutnya cepat.

**Biarkan terminal ini terbuka.** Jangan tutup dan jangan tekan `Ctrl + C`
selama Anda memakai aplikasi.

Untuk memastikan backend sehat, buka di browser:
<http://127.0.0.1:8000/api/v1/health>

Yang benar menampilkan tulisan seperti:

```json
{"status": "ok", "llm": "ok", "vector_store": "ok", "memory": "ok"}
```

### Bagian 2: frontend (terminal kedua)

Buka PowerShell **baru**, jangan menutup yang pertama.

#### Langkah 8: masuk ke folder frontend

```powershell
cd "<folder-project>\frontend"
```

#### Langkah 9: pastikan mengarah ke backend

Buat berkas `frontend/.env.local` berisi:

```ini
BACKEND_ORIGIN=http://127.0.0.1:8000
NEXT_PUBLIC_API_BASE_URL=
```

Frontend selalu memakai backend; tidak ada lagi mode demo tanpa model.

#### Langkah 10: pasang dependency

```powershell
npm install
```

#### Langkah 11: jalankan frontend

```powershell
npm run dev
```

Buka <http://localhost:3000> dan masuk dengan passcode yang Anda buat di
Langkah 5.

Data kini berasal dari
backend sungguhan.

### Bagian 3: mencoba dengan dokumen sungguhan

1. Buka halaman **Dokumen**.
2. Klik **Unggah dokumen**, pilih berkas dari folder `backend/samples`:
   - `panduan-tiket-layanan.md`
   - `kebijakan-cuti.txt`
   - `laporan-infrastruktur.pdf`
3. Tunggu sampai kartunya berubah menjadi **"Siap ditanyai"**. Biasanya 5
   sampai 30 detik per berkas.
4. Buka **Chat**, tanyakan sesuatu yang ada di dokumen, misalnya:
   - "berapa hari SLA respons tiket prioritas sedang?"
   - "berapa hak cuti tahunan karyawan?"
5. Jawaban muncul mengalir, diikuti tombol **"N sumber ditemukan"**. Klik
   tombol itu untuk melihat kutipan dan skornya.

### Latihan: memastikan sistem tidak mengarang

Ini bagian yang paling penting untuk dicoba, karena inilah janji utama
aplikasi ini.

1. Di halaman Chat, **matikan** sakelar **"Jawab tanpa dokumen"** di bawah
   kotak tanya.
2. Tanyakan hal yang tidak ada di dokumen: "berapa harga tiket bioskop di
   jakarta?"
3. Yang benar: muncul pesan **"Informasi ini tidak ditemukan dalam dokumen
   yang diunggah"**, tanpa sitasi.

Kalau sakelar itu dinyalakan kembali dan pertanyaan yang sama diajukan,
jawabannya muncul dengan label **"Bukan dari dokumen Anda"**. Dua perilaku itu
sengaja berbeda, dan labelnya harus terlihat.

---

## Kalau ada yang tidak berjalan

| Gejala | Sebab | Tindakan |
|---|---|---|
| `python` tidak dikenali | PATH tidak dicentang saat memasang | Pasang ulang Python, centang "Add Python to PATH", tutup dan buka ulang PowerShell |
| `node` tidak dikenali | Node.js belum terpasang | Pasang dari <https://nodejs.org>, pilih LTS |
| Login selalu gagal, tidak ada pesan | Backend belum hidup, atau hash passcode salah | Buka <http://127.0.0.1:8000/api/v1/health>. Kalau gagal, lihat terminal backend |
| "Gagal terhubung ke layanan" di dalam aplikasi | Terminal backend sudah ditutup | Jalankan lagi Langkah 7 |
| Semua pertanyaan dijawab "tidak ditemukan" | Dokumen belum berstatus "Siap ditanyai" | Tunggu sampai kartunya berubah, lalu coba lagi |
| Upload gagal dengan "format tidak didukung" | Berkas bukan PDF, TXT, atau Markdown | Pakai berkas dari `backend/samples` |
| Port 3000 sudah dipakai | Ada aplikasi lain di port itu | Hentikan aplikasi itu, atau jalankan `npm run dev -- -p 3001` |
| Port 8000 sudah dipakai | Backend lain masih berjalan | Tutup terminal backend yang lama |
| Aplikasi lain muncul di <http://localhost:3000> | Port 3000 dipakai proyek lain | Pastikan terminal frontend menampilkan "Ready", lalu pakai port lain |
| Halaman tampil tetapi tombol tidak bereaksi | Dibuka lewat `127.0.0.1` | Pakai `localhost:3000` |
| Petunjuk passcode berbeda dari yang diterima | `.env.local` mengisi `NEXT_PUBLIC_DEV_PASSCODE_HINT` | Singkirkan `.env.local`, lalu muat ulang halaman |
| Login selalu 401 padahal passcode benar | `backend/.env` hilang atau `ACCESS_PASSCODE_SHA256` kosong | Jalankan `python scripts/cek-kesiapan.py` dari akar proyek |

### Cara memastikan yang salah backend atau frontend

Buka <http://127.0.0.1:8000/api/v1/health>:

- **Menampilkan JSON** berarti backend sehat, masalahnya di frontend.
- **Tidak bisa dibuka** berarti backend belum jalan, masalahnya di backend.

Pembagian ini memotong separuh kemungkinan sekaligus, dan menghindari
memeriksa hal yang sebenarnya tidak bermasalah.

---

## Ringkasan perintah

Untuk Anda yang sudah pernah melakukannya, ini ringkasannya.



```powershell
cd frontend
npm install
npm run dev                       # buka http://localhost:3000
```

**Lengkap, sekali saja dari akar proyek:**

```powershell
python scripts/siapkan-lokal.py    # membuat .env, .env.local, dan passcode acak
```

**Lengkap, terminal 1:**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install sentence-transformers
python -m uvicorn app.main:app --port 8000
```

**Lengkap, terminal 2:**

```powershell
cd frontend
npm install
npm run dev                       # buka http://localhost:3000
```

---

## Setelah mencoba di lokal

Kalau hasilnya sudah sesuai harapan dan Anda ingin memasangnya di server
supaya bisa diakses dari mana saja, lanjutkan ke
[PANDUAN-DEPLOY-VPS.md](PANDUAN-DEPLOY-VPS.md). Di sana ada panduan yang sama
detailnya, ditulis untuk dijalankan langsung dari terminal server.
