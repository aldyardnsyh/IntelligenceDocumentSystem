# Melihat Hasilnya di Komputer Sendiri

Panduan ini untuk Anda yang ingin **melihat aplikasinya berjalan** sebelum
memasangnya di server. Tidak perlu tahu Docker, tidak perlu akun apa pun.

Ada dua cara, pilih sesuai kebutuhan:

| Cara | Waktu | Yang didapat |
|---|---|---|
| [Cara A: mode demo](#cara-a-mode-demo-tanpa-backend-5-menit) | 5 menit | Semua halaman bisa diklik, data contoh dari browser |
| [Cara B: lengkap](#cara-b-lengkap-dengan-backend-30-menit) | 30 menit | Benar-benar menjawab dari dokumen yang Anda unggah |

Kalau tujuan Anda hanya "ingin tahu hasilnya seperti apa", **Cara A sudah
cukup**. Cara B dipakai kalau Anda ingin menguji kualitas jawaban sungguhan.

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

## Cara A: mode demo, tanpa backend (5 menit)

Cara ini menjalankan tampilan saja. Data contoh disimpan di browser, jadi
perubahan hilang saat halaman dimuat ulang. Cocok untuk melihat seluruh
halaman dan mencoba setiap tombol.

### Langkah 1: buka folder frontend

```powershell
cd "D:\Riset Pribadi\RAG - Intelegence Document System\frontend"
```

Sesuaikan alamatnya dengan tempat Anda menyimpan proyek ini.

### Langkah 2: pasang dependency

```powershell
npm install
```

Sekali saja untuk pemasangan pertama. Prosesnya 1 sampai 3 menit dan
mengunduh sekitar 400 MB. Kalau muncul peringatan `npm warn`, itu normal,
bukan kegagalan.

Kalau perintah ini gagal dengan pesan tentang peer dependency, jalankan
sebagai gantinya:

```powershell
npm install --legacy-peer-deps
```

### Langkah 3: jalankan

```powershell
npm run dev
```

Tunggu sampai muncul tulisan seperti ini:

```
▲ Next.js 16.4.0 (Turbopack)
- Local:  http://localhost:3000
✓ Ready in 2.3s
```

### Langkah 4: buka di browser

Buka <http://localhost:3000>.

Masuk dengan passcode demo: **`demo-rag-2025`**

Di bagian atas akan muncul banner **"Mode demo"**. Itu artinya data berasal
dari browser, bukan dari server. Banner ini sengaja ada supaya tidak ada yang
mengira sedang melihat data sungguhan.

### Yang bisa Anda coba

| Halaman | Yang bisa dilakukan |
|---|---|
| Chat | Tanya apa saja, lihat jawaban dan kartunya sitasi |
| Dokumen | Unggah PDF, TXT, atau Markdown, lihat statusnya berubah |
| Analitik | Latensi, log pertanyaan, tombol evaluasi |
| Pengaturan | Ubah jumlah sumber dan ambang kemiripan |
| Tentang | Penjelasan alur kerja dan pilihan teknologi |

### Menghentikan

Tekan `Ctrl + C` di terminal tempat `npm run dev` berjalan.

---

## Cara B: lengkap, dengan backend (30 menit)

Cara ini menyalakan dua bagian: backend yang benar-benar mengindeks dokumen,
dan frontend yang menampilkannya. Inilah bentuk yang sama dengan yang nanti
berjalan di server.

Anda butuh **dua terminal** yang terbuka bersamaan: satu untuk backend, satu
untuk frontend. Keduanya harus tetap berjalan selama Anda memakai aplikasi.

### Bagian 1: backend (terminal pertama)

#### Langkah 1: masuk ke folder backend

```powershell
cd "D:\Riset Pribadi\RAG - Intelegence Document System\backend"
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
cd "D:\Riset Pribadi\RAG - Intelegence Document System\frontend"
```

#### Langkah 9: pastikan mengarah ke backend

Buat berkas `frontend/.env.local` berisi:

```ini
NEXT_PUBLIC_USE_BACKEND=1
BACKEND_ORIGIN=http://127.0.0.1:8000
NEXT_PUBLIC_API_BASE_URL=
```

`NEXT_PUBLIC_USE_BACKEND=1` adalah sakelar utama: dengan nilai itu, aplikasi
memakai backend sungguhan dan bukan data demo.

#### Langkah 10: pasang dependency

Lewati kalau Anda sudah menjalankan Cara A.

```powershell
npm install
```

#### Langkah 11: jalankan frontend

```powershell
npm run dev
```

Buka <http://localhost:3000> dan masuk dengan passcode yang Anda buat di
Langkah 5.

Kali ini **tidak ada banner "Mode demo"**. Itu artinya data berasal dari
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
| Banner "Mode demo" tetap muncul | `NEXT_PUBLIC_USE_BACKEND` belum `1` | Periksa `frontend/.env.local`, lalu hentikan frontend dengan `Ctrl + C` dan jalankan lagi |
| Login selalu gagal, tidak ada pesan | Backend belum hidup, atau hash passcode salah | Buka <http://127.0.0.1:8000/api/v1/health>. Kalau gagal, lihat terminal backend |
| "Gagal terhubung ke layanan" di dalam aplikasi | Terminal backend sudah ditutup | Jalankan lagi Langkah 7 |
| Semua pertanyaan dijawab "tidak ditemukan" | Dokumen belum berstatus "Siap ditanyai" | Tunggu sampai kartunya berubah, lalu coba lagi |
| Upload gagal dengan "format tidak didukung" | Berkas bukan PDF, TXT, atau Markdown | Pakai berkas dari `backend/samples` |
| Port 3000 sudah dipakai | Ada aplikasi lain di port itu | Hentikan aplikasi itu, atau jalankan `npm run dev -- -p 3001` |
| Port 8000 sudah dipakai | Backend lain masih berjalan | Tutup terminal backend yang lama |
| Aplikasi lain muncul di <http://localhost:3000> | Port 3000 dipakai proyek lain | Pastikan terminal frontend menampilkan "Ready", lalu pakai port lain |

### Cara memastikan yang salah backend atau frontend

Buka <http://127.0.0.1:8000/api/v1/health>:

- **Menampilkan JSON** berarti backend sehat, masalahnya di frontend.
- **Tidak bisa dibuka** berarti backend belum jalan, masalahnya di backend.

Pembagian ini memotong separuh kemungkinan sekaligus, dan menghindari
memeriksa hal yang sebenarnya tidak bermasalah.

---

## Ringkasan perintah

Untuk Anda yang sudah pernah melakukannya, ini ringkasannya.

**Mode demo:**

```powershell
cd frontend
npm install
npm run dev                       # buka http://localhost:3000
```

**Lengkap, terminal 1:**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install sentence-transformers
python -m scripts.make_passcode    # salin hash ke .env
Copy-Item .env.example .env        # lalu isi ACCESS_PASSCODE_SHA256 dan LLM_PROVIDER=mock
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
