# Backend, Intelligent Document Assistant

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
   lolos ambang, jawabannya "tidak ditemukan", bukan karangan.
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
pip install sentence-transformers      # untuk embedding semantik (USE_LOCAL_EMBEDDING=1)

Copy-Item .env.example .env
python -m scripts.make_passcode          # menghasilkan ACCESS_PASSCODE_SHA256

python -m uvicorn app.main:app --reload --port 8000
```

Dokumentasi API interaktif: <http://localhost:8000/docs>

### Embedding lokal butuh unduhan model sekali

Saat start pertama, `intfloat/multilingual-e5-small` (~470 MB) diunduh dari
Hugging Face dan disimpan di cache. Setelah itu jalan offline.

Kalau tidak ingin mengunduhnya, set `USE_LOCAL_EMBEDDING=0`. Sistem tetap
jalan dengan embedding berbasis hashing, **dan `/api/v1/health` akan
melaporkan itu**, karena retrieval hanya cocok untuk kata yang identik.

### Ganti model embedding = indeks harus dibangun ulang

Vektor yang tersimpan dibuat oleh model tertentu. Kalau `USE_LOCAL_EMBEDDING`
atau `EMBEDDING_MODEL` berubah, vektor lama **tidak sebanding** dengan vektor
baru walau dimensinya sama. Gejalanya menipu: dokumen berstatus `ready`,
pertanyaan wajar, tapi jawabannya ngawur atau selalu "tidak ditemukan".

```powershell
python -m scripts.reindex --dry-run   # lihat berapa chunk yang akan diproses
python -m scripts.reindex             # bangun ulang vektor dari isi chunk
```

Dokumen tidak perlu diunggah ulang: isi chunk dibaca dari database metadata.

## Menjalankan dengan Docker

```powershell
Copy-Item .env.example .env
python -m scripts.make_passcode

docker compose up -d --build
docker compose logs -f api
```

## Deployment ke satu VPS

Shape yang dipakai: **satu** server dengan disk persisten. Semua state ada di
satu volume, jadi tidak ada database eksternal. Kode ini tidak terikat pada
penyedia tertentu: tidak ada satu pun baris yang menyebut AWS, jadi VPS mana
pun dengan Docker bisa dipakai.

### Kebutuhan minimum

| Komponen | RAM |
|---|---|
| Ubuntu dan Docker | ~300 MB |
| FastAPI dan ChromaDB | ~250 MB |
| torch saat dimuat | ~600 MB |
| Model embedding | ~470 MB |
| **Total** | **~1,6 GB** |

Jadi **2 GB RAM sudah cukup**, dengan sisa sekitar 400 MB. Dengan 1 GB,
aplikasi tetap bisa jalan tapi wajib swap (lihat catatan di langkah 4).

Disk: sekitar 9 GB untuk sistem, image, dan build cache, sisanya untuk
dokumen. **20 GB cukup**, 40 GB lebih lega.

### Pilihan penyedia

| | Tencent Lighthouse (Singapore) | AWS EC2 t3.micro |
|---|---|---|
| RAM | 2 GB | 1 GB |
| Disk | 40 GB | 20 GB |
| Biaya | sudah dibayar | gratis 12 bulan, lalu ditagih |
| Swap | tidak wajib, tapi disarankan | **wajib** |
| Catatan | region Singapore bisa akses semua layanan | setelah 12 bulan biaya muncul tanpa pemberitahuan jelas |

VPS dengan 2 GB lebih dipilih karena tidak perlu bergantung pada swap. Swap
bekerja, tapi lambat, dan build pertama akan terasa jauh lebih lama.

### Cara cepat: satu skrip

Ada skrip yang mengerjakan seluruh langkah di bawah secara berurutan, dari
server kosong sampai aplikasi jalan. Cocok dipakai dari OrcaTerm atau
terminal web lain, tanpa perlu SSH dari komputer sendiri.

```bash
# Dari server yang baru dibuat.
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/aldyardnsyh/IntelligenceDocumentSystem.git /opt/ida
cd /opt/ida/backend
bash scripts/setup-vps.sh
```

Skrip akan menanyakan empat hal, lalu mengerjakan sisanya:

| Pertanyaan | Keterangan |
|---|---|
| Domain | Harus sudah menunjuk ke IP server ini |
| Email | Untuk pemberitahuan kedaluwarsa sertifikat. Isinya bebas |
| Passcode | Minimal 12 karakter, untuk masuk ke aplikasi |
| Groq API key | Dari <https://console.groq.com/keys>, gratis |

Skripnya **idempoten**: aman dijalankan ulang. Kalau konfigurasi sudah ada,
ia bertanya dulu sebelum mengubah, dan langkah yang sudah selesai dilewati.

Yang **tidak** dikerjakan skrip ini, dan harus Anda lakukan di panel
penyedia: **buka port 80 dan 443 di firewall**. Tanpa itu, Caddy tidak bisa
menerbitkan sertifikat dan situs tidak bisa diakses dari internet. Ini
penyebab kegagalan yang paling sering, dan skrip tidak bisa menutupnya
karena firewall-nya ada di luar server.

Kalau lebih suka mengerjakan manual, atau ingin tahu apa yang sebenarnya
dilakukan, lanjutkan membaca bagian di bawah. Isinya sama, hanya dipecah
per langkah.

### Kenapa satu server, bukan Vercel + backend terpisah

Pertanyaan ini sering muncul, jadi jawabannya ditulis di sini.

**Backend tidak bisa di Vercel.** Batas ukuran bundle Hobby adalah 250 MB
uncompressed, sedangkan `torch` sendiri 1.260 MB. Ditambah Vercel tidak
punya disk persisten, sehingga SQLite dan ChromaDB akan hilang setiap kali
function dingin. Backend butuh disk dan RAM yang tidak disediakan platform
serverless.

**Frontend bisa, tapi tidak memberi keuntungan di sini.** Semua halaman
butuh backend, jadi memisahkannya hanya menambah satu tempat yang bisa
gagal. Yang lebih penting: aplikasi ini didesain **satu origin** supaya
cookie sesi bekerja tanpa `SameSite=None`, dan jawaban LLM di-stream lewat
SSE yang berisiko terputus kalau lewat proxy perantara. Satu server
menghindari ketiga masalah itu sekaligus.

### 1. Siapkan server

Bagian ini berlaku untuk penyedia mana pun. Yang berbeda hanya cara masuk
dan nama firewall-nya.

**Tencent Lighthouse.** Beli paket Singapore, pilih image **Ubuntu 24.04**.
Firewall ada di panel Lighthouse, bukan di dalam server.

**AWS EC2.** Launch instance dengan AMI Ubuntu 24.04 LTS (x86_64), tipe
`t3.micro`, storage gp3 20 GB, lalu buat atau pilih key pair.

Masuk ke server. Tencent punya terminal web (**OrcaTerm**) di panel, jadi
langkah ini bisa dilewati sepenuhnya: buka OrcaTerm dan Anda langsung
berada di dalam server.

```bash
ssh -i <key>.pem ubuntu@<ip-server>          # AWS
ssh root@<ip-server>                          # Tencent, atau user yang Anda buat
```

### 2. Buka firewall

Inbound: **hanya HTTP (80) dan HTTPS (443)**, source `0.0.0.0/0`.

- **Tencent Lighthouse:** menu **Firewall** di panel, tambahkan rule untuk
  port 80 dan 443. Lighthouse secara default hanya membuka 22, jadi langkah
  ini wajib. Tanpa ini, Caddy tidak akan pernah bisa menerbitkan sertifikat
  dan situs tidak bisa diakses dari internet.
- **AWS:** Security group instance, tambahkan inbound rule yang sama.

Port 8000 **jangan** dibuka. API hanya dijangkau lewat Caddy.

> Ini penyebab kegagalan yang paling sering, dan gejalanya menyesatkan:
> semua container terlihat sehat, `curl localhost:8000/api/v1/health`
> berhasil dari dalam server, tapi situs tidak bisa dibuka dari luar dan
> log Caddy penuh percobaan ACME yang gagal. Kalau itu terjadi, periksa
> firewall dulu, bukan konfigurasi Caddy.

> Kalau memakai Tencent di China mainland, port 80 dan 443 untuk domain
> yang belum terdaftar (ICP filing) akan diblokir. Region Singapore tidak
> punya batasan ini.

### 3. Siapkan domain

Caddy butuh domain untuk menerbitkan sertifikat TLS otomatis, dan domain
`*.vercel.app` **tidak bisa dipakai** karena dimiliki Vercel, A record-nya
menunjuk server mereka, dan kita tidak bisa mengubahnya.

Dua pilihan:

**Domain sendiri (paling rapi).** Beli domain, lalu buat `A` record yang
menunjuk ke **IP publik server**. Domain `.my.id` sekitar Rp15 ribu per
tahun dan sudah cukup.

**DuckDNS (gratis).** `duckdns.org` terdaftar di Public Suffix List,
artinya `nama-anda.duckdns.org` dianggap domain sendiri oleh Let's Encrypt,
jadi Caddy bisa menerbitkan sertifikat untuk itu tanpa biaya.

Langkahnya:

1. Buka <https://www.duckdns.org>, masuk dengan akun Google, GitHub, atau
   Twitter. Tidak perlu membuat akun baru.
2. Di kotak **sub domain**, ketik nama pilihan Anda, misalnya
   `intelligencedocumentassistant`. Alamat akhirnya menjadi
   `intelligencedocumentassistant.duckdns.org`. Hanya huruf kecil, angka,
   dan tanda hubung.
3. Klik **add domain**.
4. Di baris domain yang baru muncul, isi kolom **current ip** dengan IP
   publik server Anda, lalu klik **update ip**.
5. Salin **token** di bagian atas halaman. Simpan, karena dipakai kalau
   nanti perlu memperbarui IP tanpa membuka situsnya.
6. Cek dari komputer sendiri:

   ```bash
   nslookup intelligencedocumentassistant.duckdns.org
   ```

   Harus menampilkan IP server Anda. Kalau belum, tunggu satu atau dua
   menit, DNS butuh waktu menyebar.

> Nama subdomain DuckDNS dibatasi satu label, jadi tidak bisa memakai titik
> di dalamnya. `intelligencedocumentassistant` (29 karakter) termasuk
> panjang tapi masih dalam batas satu label DNS, yaitu 63 karakter. Kalau
> DuckDNS menolak nama itu, pakai bentuk yang lebih pendek seperti `ida-rag`
> atau `ida-docs`.

**Kalau IP server berubah**, DuckDNS harus diperbarui atau situs menjadi
tidak bisa dibuka. Ini bisa dilakukan tanpa membuka situsnya:

```bash
# Ganti <token> dengan token dari halaman duckdns.org.
curl -s "https://www.duckdns.org/update?domains=intelligencedocumentassistant&token=<token>&ip="
```

Jawaban `OK` berarti berhasil. Perintah yang sama bisa dimasukkan ke cron
kalau Anda ingin memperbaruinya otomatis.

### 4. Siapkan server

**Kalau server Anda punya 1 GB RAM (t3.micro), tambahkan swap lebih dulu.**
Kalau 2 GB atau lebih, swap tidak wajib tapi tetap disarankan sebagai jaring
pengaman; ukurannya cukup 2 GB.

```bash
# 4G untuk server 1 GB, 2G untuk server 2 GB.
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Bertahan setelah reboot.
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Pakai swap hanya kalau RAM benar-benar habis, bukan sebagai tambahan
# rutin. Nilai rendah membuat sistem lebih memilih membuang cache.
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

free -h   # baris Swap harus menunjukkan ukuran yang Anda pasang
```

> `chmod 600` bukan formalitas. Swap berisi salinan memori proses, termasuk
> passcode yang sedang dibandingkan dan potongan dokumen yang sedang
> diproses. Berkas yang bisa dibaca pengguna lain adalah kebocoran.

> Kalau `fallocate` gagal dengan "Operation not supported" (terjadi di
> filesystem tertentu), ganti baris pertama dengan:
> `sudo dd if=/dev/zero of=/swapfile bs=1M count=4096 status=progress`.
> Hasilnya sama, hanya lebih lambat karena benar-benar menulis 4 GB.

Lanjutkan dengan Docker:

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker

git clone <repo> ida && cd ida/backend
cp .env.example .env
```

Buat hash passcode. Dijalankan lewat container karena skripnya butuh
pydantic, sedangkan server Ubuntu yang polos belum punya itu:

```bash
docker compose run --rm -T api python -m scripts.make_passcode --stdin
```

Skrip itu menolak passcode di bawah 12 karakter. Passcode ini satu-satunya
yang berdiri di antara internet dan seluruh dokumen pengguna.

> Perintah ini **tidak** mengunduh model embedding. Skripnya hanya membaca
> `app.core.config` dan `app.core.security`, tidak menyentuh provider
> embedding. Jadi aman dijalankan di server 1 GB sebelum swap ditambahkan,
> dan selesai dalam hitungan detik.

Edit `.env` minimal pada ini:

```ini
ACCESS_PASSCODE_SHA256=<hash-dari-skrip>
LLM_PROVIDER=groq
GROQ_API_KEY=<key-anda>
CORS_ORIGINS=https://nama-anda.duckdns.org
DEBUG=false
API_DOCS_ENABLED=0
TRUST_PROXY_HEADERS=1
```

Catatan tiap baris:

- `GROQ_API_KEY` dari <https://console.groq.com/keys>. Free tier 1.000
  request per hari, dan tidak butuh kartu kredit.
- `CORS_ORIGINS` harus domain Anda, **tanpa `*`**. Nilai `*` ditolak saat
  start karena aplikasi ini memakai cookie sesi.
- `DEBUG=false` supaya pesan error internal tidak terkirim ke klien.
- `API_DOCS_ENABLED=0` menutup `/docs`, `/redoc`, dan `/openapi.json`.
  Kalau ingin halaman itu bisa dibuka, isi `1` **dan** isi
  `NEXT_PUBLIC_API_DOCS_URL` di langkah berikutnya.
- `TRUST_PROXY_HEADERS=1` wajib di compose. Tanpa ini semua klien terlihat
  sebagai IP Caddy, sehingga rate limit login jadi satu bucket global dan
  lima percobaan gagal mengunci semua pengguna.

### 5. Ganti domain di Caddyfile

Dari direktori `backend/`:

```bash
sed -i 's/^example\.com {/nama-anda.duckdns.org {/' Caddyfile
sed -i 's/^\(\s*email\s*\)admin@example\.com/\1email-anda@example.com/' Caddyfile
```

**Kenapa polanya dipatok ke awal baris, bukan `s/example\.com/.../g`.**
Kata `example.com` muncul tiga kali di berkas itu: sebagai alamat situs,
sebagai alamat email, dan di dalam komentar yang menjelaskan kenapa
placeholder tidak boleh dipakai. Mengganti semuanya membuat komentarnya
berbunyi salah, misalnya menjadi "nama-anda.duckdns.org milik IANA", dan
membuat pembaca berikutnya bingung.

Verifikasi hasilnya sebelum container dijalankan:

```bash
grep -n "example" Caddyfile          # sisa kemunculan harus di komentar saja
docker compose run --rm caddy caddy validate --config /etc/caddy/Caddyfile
```

Lewati langkah ini dan Caddy tidak akan pernah menerbitkan sertifikat:
`example.com` milik IANA, dan ACME pasti gagal untuk domain itu.

### 6. Jalankan

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f api
```

Build pertama memakan **10 sampai 15 menit** di server 1 GB, lebih cepat di 2 GB: mengunduh torch
CPU, lalu mengunduh model embedding 470 MB saat container pertama start.
Ini normal, bukan hang. Log akan berhenti di "Layanan siap" setelah modelnya
selesai diunduh.

Caddy menerbitkan sertifikat Let's Encrypt otomatis dalam satu menit setelah
container berjalan.

### 7. Verifikasi

Jalankan berurutan dari server:

```bash
# 1. Container hidup semua?
docker compose ps

# 2. API menjawab?
curl -s localhost:8000/api/v1/health | head -c 200

# 3. Lewat Caddy, tanpa TLS dulu (harus redirect ke HTTPS)
curl -sI http://nama-anda.duckdns.org | head -3

# 4. Lewat HTTPS, dari server
curl -s https://nama-anda.duckdns.org/api/v1/health

# 5. Sertifikat sudah terbit?
docker compose logs caddy | grep -i "certificate obtained"
```

`"status": "ok"` berarti semua komponen hidup. Kalau tertulis `"degraded"`,
lihat field `fallback`: `vector_store_persistent: false` berarti indeks akan
hilang saat restart.

Terakhir, buka `https://nama-anda.duckdns.org` di browser:

1. Halaman login muncul, dan ada ikon gembok (HTTPS valid).
2. Masuk dengan passcode yang Anda buat di langkah 4.
3. Unggah `backend/samples/panduan-tiket-layanan.md` di halaman Dokumen.
4. Tunggu statusnya `ready`, lalu tanyakan sesuatu di halaman Chat.
5. Jawabannya harus muncul bertahap (streaming), disertai sitasi.

Kalau langkah 5 gagal tapi 1 sampai 4 berhasil, masalahnya di provider LLM.
Cek `docker compose logs api | grep -i groq`.

### 8. Deploy ulang

```bash
cd ida && git pull && cd backend
docker compose up -d --build
```

Perubahan yang tidak menyentuh Dockerfile (misalnya isi `.env`) lebih cepat:

```bash
docker compose up -d --force-recreate api
```

---

## CI dan CD

Dua workflow, dengan pembagian tugas yang sengaja dipisah supaya kegagalan
satu tidak mengaburkan yang lain.

### `ci.yml`: memeriksa kode

Berjalan pada setiap push ke `master` dan setiap pull request. Isinya:

| Job | Langkah | Yang dicek |
|---|---|---|
| Backend | `ruff check` | Gaya kode dan kesalahan statis |
| Backend | `pytest` | 434 test, dengan gerbang coverage 70% |
| Frontend | `next typegen` | Tipe route `PageProps` dan `LayoutProps` |
| Frontend | `tsc --noEmit` | Tipe TypeScript |
| Frontend | `eslint` | Aturan lint Next.js |
| Frontend | `next build` | Build produksi benar-benar berhasil |

Yang **tidak** dijalankan, dan itu disengaja: tidak ada torch, tidak ada
unduhan model 470 MB, tidak ada panggilan ke Groq, dan tidak ada koneksi
keluar. Test memakai stub embedding, provider mock, dan `httpx.MockTransport`,
jadi hasilnya cepat dan tidak bergantung pada layanan luar.

Kalau job ini merah, jangan merge. Ada yang rusak.

### `publish.yml`: membangun image

Berjalan **hanya kalau CI lulus**, atau kalau dijalankan manual dari tab
Actions. Tugasnya satu: membangun image backend dan frontend, lalu
mengirimnya ke GitHub Container Registry.

Manfaatnya: build torch dan Next.js terjadi di mesin GitHub, bukan di VPS
2 GB. Deploy jadi satu sampai dua menit, bukan lima belas.

Image yang dihasilkan diberi dua tag:

- `:latest` untuk pemakaian biasa
- `:<commit-sha>` untuk rollback ke versi tertentu

### Deploy memakai image dari CI

Tambahkan dua baris ini ke `backend/.env`:

```ini
IDA_API_IMAGE=ghcr.io/aldyardnsyh/intelligencedocumentsystem-api:latest
IDA_WEB_IMAGE=ghcr.io/aldyardnsyh/intelligencedocumentsystem-web:latest
```

Lalu di server:

```bash
cd /opt/ida/backend
docker compose pull
docker compose up -d
```

Tanpa dua baris itu, `docker compose` kembali memakai image lokal dan
`--build` bekerja seperti biasa. Jadi memakai registry bersifat pilihan,
bukan keharusan.

> Kalau registry-nya privat, jalankan `docker login ghcr.io` sekali di
> server memakai Personal Access Token dengan scope `read:packages`. Untuk
> repo publik, image-nya juga publik dan langkah ini tidak perlu.

### Rollback

Karena setiap build diberi tag commit, kembali ke versi sebelumnya tidak
perlu membangun ulang:

```bash
cd /opt/ida/backend
sed -i 's|:latest|:<commit-sha-lama>|' .env
docker compose pull && docker compose up -d
```

### Kalau workflow gagal

Penyebab yang paling sering, dan cara memeriksanya:

| Gejala di log | Penyebab | Solusi |
|---|---|---|
| `Cannot find name 'PageProps'` | `next typegen` dilewati | Workflow sudah menjalankannya. Kalau diubah, jangan hapus langkah itu |
| `npm ci` gagal dengan `ERESOLVE` | Flag `--legacy-peer-deps` hilang | Flag itu wajib, sama seperti di Dockerfile |
| `ModuleNotFoundError: reportlab` | Dependency test tidak terpasang | Pastikan `reportlab` ada di daftar pip di workflow |
| `denied: permission_denied` saat push | `permissions: packages: write` hilang | Kembalikan blok permission di `publish.yml` |
| `coverage ... not reached` | Coverage turun di bawah 70% | Tambah test, atau turunkan gerbangnya dengan sadar |

Semua perintah di kedua workflow sudah dijalankan di environment bersih
sebelum di-commit, jadi kesalahan sintaks dan dependency sudah tersaring.
Yang tersisa biasanya soal izin atau konfigurasi repo.

> Build image pertama kali di GitHub Actions memakan sekitar 10 sampai 15
> menit karena mengunduh torch. Build berikutnya jauh lebih cepat karena
> memakai cache registry.

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

### Disk

Perkiraan pemakaian dengan disk 20 GB:

| Bagian | Ukuran |
|---|---|
| Ubuntu dan Docker engine | ~3,5 GB |
| Image backend (torch dan venv) | ~2,0 GB |
| Image frontend dan Caddy | ~0,6 GB |
| Build cache Docker | ~2,0 GB |
| Model embedding di volume | ~0,5 GB |
| **Total** | **~9 GB** |

Sisanya sekitar 10 GB untuk dokumen Anda. Dokumen dibatasi 10 MB per berkas,
jadi ruang itu cukup untuk ratusan dokumen.

Build cache adalah yang paling cepat menumpuk, karena setiap deploy
menyimpan layer lama. Kalau disk mulai penuh:

```bash
df -h /                        # berapa yang terpakai
docker system df               # rincian per kategori
docker builder prune -f        # hapus build cache
docker image prune -f          # hapus image yang tidak dipakai tag apa pun
```

Jangan pakai `docker system prune -a --volumes`: flag `--volumes` akan
menghapus `ida_ida-data` beserta seluruh dokumen Anda.

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
pytest                    # 434 test, coverage gate 70%
ruff check app tests scripts   # lint
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
**harus** dijawab "tidak ditemukan". Tiga yang terakhir itu yang paling berguna, di situ yang diukur apakah sistem mengarang saat tidak tahu.

Untuk melihat jawaban dan konteks tanpa menghitung skor:

```powershell
python -m scripts.evaluate_ragas --dry-run
```

## Troubleshooting

### Deployment

| Gejala | Penyebab | Solusi |
|---|---|---|
| Container `api` restart berulang | RAM habis, kernel membunuh proses | Cek `dmesg \| grep -i "killed process"` dan `free -h`. Pastikan swap aktif: baris `Swap` harus sesuai ukuran yang dipasang. Kalau masih mati, tambah RAM |
| Build berhenti lama tanpa log | Mengunduh torch lalu model 470 MB | Normal, 10 sampai 15 menit di server 1 GB, sekitar 5 menit di 2 GB. Lihat progres dengan `docker compose logs -f api` |
| Caddy tidak terbit sertifikat | DNS belum resolve ke instance | `nslookup nama-anda.duckdns.org` harus menunjuk IP instance. Untuk DuckDNS, pastikan kolom `current ip` sudah di-update |
| Caddy keluar dengan error ACME | Domain di Caddyfile masih `example.com` | Jalankan `sed -i 's/example\.com/domain-anda/g' Caddyfile` lalu `docker compose up -d --force-recreate caddy` |
| Halaman terbuka tapi API 502 | Container `api` belum sehat | `docker compose ps` harus menunjukkan `healthy`. Caddy sengaja menunggu sampai sehat |
| Healthcheck gagal terus padahal API jalan | Model embedding masih diunduh | `start_period` 600 detik. Tunggu, jangan restart, karena restart memulai unduhan dari awal |

### Aplikasi

| Gejala | Penyebab | Solusi |
|---|---|---|
| `401` di semua request | Cookie `ida_session` tidak sampai | Pastikan frontend pakai rewrite proxy (`BACKEND_ORIGIN` di `.env.local`), dan `NEXT_PUBLIC_API_BASE_URL` kosong |
| Semua pertanyaan "tidak ditemukan" | Indeks retrieval kosong | `docker compose restart api`; log akan menyebut jumlah chunk yang dipulihkan |
| Login selalu ditolak | `ACCESS_PASSCODE_SHA256` salah isi | Harus 64 karakter heksadesimal, bukan passcode mentah. Buat ulang dengan `docker compose run --rm -T api python -m scripts.make_passcode --stdin` |
| Login ditolak dari mana-mana setelah 5 kali gagal | `TRUST_PROXY_HEADERS` belum `1` | Semua klien terlihat sebagai IP Caddy, jadi satu bucket global. Set `TRUST_PROXY_HEADERS=1` lalu `docker compose up -d --force-recreate api` |
| `Set-Cookie` tidak terkirim | Browser bicara langsung ke backend | Set `NEXT_PUBLIC_API_BASE_URL=` (kosong) di frontend, biar lewat proxy |
| Jawaban tidak streaming, muncul sekaligus | Buffering proxy | Pastikan lewat Caddy (`flush_interval -1` sudah ada). Jangan taruh Cloudflare proxy di depan kalau tidak perlu |
| `/docs` mengembalikan 404 | Dokumentasi API memang dimatikan | Set `API_DOCS_ENABLED=1` **dan** isi `NEXT_PUBLIC_API_DOCS_URL`, lalu deploy ulang keduanya |
| Jawaban menyalin cuplikan dokumen | `LLM_PROVIDER=mock` masih aktif | Set `LLM_PROVIDER=groq` dan isi `GROQ_API_KEY`, lalu `docker compose up -d --force-recreate api`. Log startup akan memperingatkan ini |
