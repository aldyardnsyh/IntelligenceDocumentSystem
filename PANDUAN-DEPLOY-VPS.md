# Panduan Deploy ke VPS, dari Nol sampai Bisa Dibuka

Panduan ini ditulis untuk dijalankan **langsung dari terminal server**
(OrcaTerm Tencent, atau terminal web penyedia lain). Tidak perlu SSH dari
komputer sendiri, tidak perlu tahu Docker.

Setiap langkah berisi: **apa yang diketik**, **apa yang seharusnya muncul**,
dan **apa yang harus dilakukan kalau berbeda**. Kalau satu langkah tidak
sesuai, berhenti di situ dan periksa, jangan lanjut.

**Total waktu:** 30 sampai 60 menit, tergantung kecepatan unduh server.

---

## Gambaran besar

Ada enam tahap. Tiga pertama sekali saja, tiga berikutnya setiap kali ingin
memperbarui aplikasi.

| Tahap | Sekali atau berulang |
|---|---|
| 1. Siapkan server di panel penyedia | Sekali |
| 2. Arahkan domain ke server | Sekali |
| 3. Buka port 80 dan 443 | Sekali |
| 4. Jalankan skrip setup | Sekali |
| 5. Verifikasi | Setiap kali |
| 6. Memperbarui aplikasi | Setiap ada versi baru |

---

## Sebelum mulai: yang perlu Anda siapkan

| Yang dibutuhkan | Keterangan |
|---|---|
| VPS Ubuntu | 2 GB RAM, 40 GB disk. Yang Anda punya sudah cukup |
| Domain | Boleh gratis dari DuckDNS, lihat Langkah 2 |
| Groq API key | Gratis di <https://console.groq.com/keys>, 1000 permintaan per hari |
| Passcode | Buat sendiri, minimal 12 karakter |

Soal RAM: aplikasi ini butuh sekitar 1,6 GB saat berjalan. Dengan 2 GB, skrip
akan memasang swap otomatis sebagai jaring pengaman. Dengan 1 GB pun masih
bisa, tetapi lambat dan tidak disarankan.

---

## Langkah 1: siapkan server di panel penyedia

Ini dilakukan di **panel web Tencent Cloud**, bukan di terminal.

1. Buat instance baru, pilih **Ubuntu 22.04** atau lebih baru.
2. Pilih ukuran minimal **2 vCPU, 2 GB RAM**.
3. Setelah instance jadi, catat **IP publik**-nya. Bentuknya seperti
   `43.134.12.34`.

Setelah itu buka **OrcaTerm** atau terminal web yang disediakan panel, dan
Anda akan masuk sebagai user `ubuntu` atau `root`. Semua perintah berikutnya
diketik di sana.

### Periksa dulu bahwa server sehat

Ketik:

```bash
uname -a
free -h
df -h /
```

Yang perlu Anda lihat:

- `Ubuntu` dengan versi 22 atau lebih baru
- Baris `Mem:` menunjukkan sekitar `2.0Gi` atau lebih
- Kolom `Avail` pada baris `/` menunjukkan minimal `20G`

Kalau RAM di bawah 2 GB, skrip tetap jalan dengan swap, tetapi build awal
akan lambat. Kalau disk di bawah 20 GB, hentikan dan perbesar disk dulu,
karena image Docker dan model embedding butuh sekitar 9 GB.

---

## Langkah 2: arahkan domain ke server

Aplikasi ini wajib memakai HTTPS, dan HTTPS butuh domain. Tanpa domain,
sertifikat tidak bisa diterbitkan dan situs tidak bisa dibuka dengan aman.

### Kalau punya domain sendiri

Di panel DNS domain Anda, buat satu record:

| Jenis | Nama | Isi |
|---|---|---|
| A | `ida` (atau nama lain) | IP publik server Anda |

Kalau nanti bisa diakses di `https://ida.domainanda.com`, maka "Nama" adalah
`ida`.

### Kalau belum punya domain, pakai DuckDNS (gratis)

1. Buka <https://www.duckdns.org> dan masuk dengan akun Google atau GitHub.
2. Buat satu subdomain, misalnya `ida-anda`. Domainnya menjadi
   `ida-anda.duckdns.org`.
3. Di kolom **current ip**, isi IP publik server Anda, lalu klik
   **update ip**.

### Pastikan domain sudah menunjuk ke server

Dari terminal server, ketik (ganti dengan domain Anda):

```bash
getent hosts ida-anda.duckdns.org
```

Yang benar menampilkan IP publik server Anda:

```
43.134.12.34    ida-anda.duckdns.org
```

Kalau yang muncul IP lain, atau tidak muncul apa pun, **tunggu 1 sampai 5
menit** lalu coba lagi. DNS butuh waktu menyebar. Jangan lanjut sebelum IP-nya
benar, karena sertifikat akan gagal diterbitkan.

---

## Langkah 3: buka port 80 dan 443

**Ini langkah yang paling sering terlupa, dan penyebab kegagalan nomor satu.**
Skrip setup tidak bisa mengerjakannya, karena firewall-nya ada di panel
penyedia, di luar server.

Di panel Tencent Cloud, buka **Firewall** atau **Security Group** untuk
instance Anda, lalu tambahkan dua aturan masuk:

| Protokol | Port | Sumber |
|---|---|---|
| TCP | 80 | 0.0.0.0/0 |
| TCP | 443 | 0.0.0.0/0 |

Port 80 dipakai Let's Encrypt untuk memverifikasi bahwa domain memang milik
Anda. Port 443 dipakai untuk lalu lintas HTTPS.

Kalau firewall di dalam server juga aktif, izinkan juga di sana:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

Kalau `ufw` tidak terpasang, perintah itu akan gagal dengan pesan `command not
found`. Itu tidak masalah, berarti firewall di dalam server tidak aktif dan
hanya panel penyedia yang mengatur.

---

## Langkah 4: jalankan skrip setup

Satu perintah ini mengerjakan semuanya: swap, Docker, mengunduh kode,
konfigurasi, build, menjalankan, dan memeriksa.

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/aldyardnsyh/IntelligenceDocumentSystem.git /opt/ida
cd /opt/ida/backend
sudo bash scripts/setup-vps.sh
```

### Yang akan ditanyakan, dan cara menjawabnya

Skrip bertanya empat hal. Ketikan passcode dan API key **tidak terlihat di
layar**, itu normal dan disengaja.

| Pertanyaan | Jawaban |
|---|---|
| Domain | Domain dari Langkah 2, tanpa `https://`. Contoh: `ida-anda.duckdns.org` |
| Email | Alamat email Anda. Dipakai hanya kalau sertifikat gagal diperbarui |
| Passcode | Buat sendiri, minimal 12 karakter. **Catat di tempat aman** |
| Groq API key | Kunci dari <https://console.groq.com/keys>, diawali `gsk_` |

### Apa yang akan terlihat, dan berapa lama

Skrip menampilkan delapan langkah bernomor. Yang paling lama:

| Langkah | Perkiraan waktu | Yang terjadi |
|---|---|---|
| 1-3 | 1 menit | Memeriksa sistem, memasang swap |
| 3 | 2-4 menit | Memasang Docker |
| 4 | 10 detik | Mengunduh kode |
| 5 | 5-15 menit | Membangun image backend untuk menghitung hash passcode |
| 6 | 5-15 menit | Membangun image frontend dan backend |
| 7 | 1-10 menit | Menyalakan layanan, mengunduh model 470 MB |

**Kalau layar terlihat diam selama beberapa menit, itu normal.** Server sedang
mengunduh atau membangun. Jangan menekan `Ctrl + C`.

Untuk melihat bahwa masih bekerja, buka satu terminal lagi dan ketik:

```bash
docker stats --no-stream
```

Kalau angka CPU tinggi, artinya sedang bekerja. Kalau muncul daftar kosong,
berarti belum ada container yang jalan.

### Kalau skrip berhenti dengan tulisan GAGAL

Skrip berhenti dengan sengaja saat ada masalah, supaya Anda tidak menunggu
sia-sia. Pesannya menyebutkan penyebabnya. Lihat bagian
[Masalah yang sering terjadi](#masalah-yang-sering-terjadi) di bawah.

Skrip ini **aman dijalankan ulang**. Langkah yang sudah selesai dilewati, dan
konfigurasi yang sudah ada tidak ditimpa tanpa bertanya.

---

## Langkah 5: verifikasi

Skrip sudah memeriksa sendiri di akhir. Untuk memastikan sekali lagi, jalankan
tiga pemeriksaan ini.

### Periksa 1: layanan berjalan

```bash
cd /opt/ida/backend
sudo docker compose ps
```

Yang benar: kolom `STATUS` berisi `Up` atau `Up (healthy)` untuk `api`, `frontend`,
dan `caddy`.

### Periksa 2: backend menjawab

```bash
curl -s http://127.0.0.1:8000/api/v1/health
```

Yang benar menampilkan JSON:

```json
{"status":"ok","llm":"ok","vector_store":"ok","memory":"ok","version":"1.0.0"}
```

`status` boleh `degraded` dalam dua hal: tracing mati, atau vector store
in-memory. Keduanya normal untuk pemasangan satu server.

### Periksa 3: HTTPS bisa dibuka

Dari browser di komputer Anda, buka:

```
https://ida-anda.duckdns.org
```

Yang benar: halaman login muncul, dan ikon gembok di bilah alamat berwarna
normal (bukan peringatan).

Masuk dengan passcode yang Anda buat di Langkah 4.

### Kalau HTTPS belum bisa dibuka

Tunggu 2 menit dan coba lagi. Penerbitan sertifikat Let's Encrypt butuh
verifikasi lewat port 80, dan kadang mengulang beberapa kali.

Kalau setelah 5 menit masih gagal:

```bash
cd /opt/ida/backend
sudo docker compose logs caddy --tail 40
```

Cari kata `acme` atau `error`. Penyebab yang paling sering:

| Pesan di log | Artinya | Tindakan |
|---|---|---|
| `connection refused` pada port 80 | Port 80 belum dibuka | Ulangi Langkah 3 |
| `no such host` | Domain belum mengarah ke server | Ulangi Langkah 2, tunggu 5 menit |
| `already in use` | Ada web server lain di port 80 | Hentikan: `sudo systemctl stop nginx apache2` |

---

## Langkah 6: mencoba aplikasinya

Setelah masuk, lakukan ini untuk memastikan semuanya benar-benar bekerja.

1. Buka halaman **Dokumen**.
2. Klik **Unggah dokumen** dan pilih satu berkas PDF, TXT, atau Markdown milik
   Anda. Kalau belum punya, tidak apa-apa, lanjut ke langkah berikutnya.
3. Tunggu sampai kartunya berubah menjadi **"Siap ditanyai"**.
4. Buka **Chat**, tanyakan sesuatu yang ada di dokumen itu.
5. Jawaban muncul, diikuti tombol **"N sumber ditemukan"**.

Kalau langkah 4 dijawab "tidak ditemukan" padahal isinya ada, periksa:

```bash
cd /opt/ida/backend
sudo docker compose logs api --tail 30
```

Cari baris `embedding`. Kalau tertulis `hashing-fallback`, model embedding
gagal dimuat dan retrieval memakai cadangan yang kualitasnya rendah. Muat ulang
layanan untuk mencoba lagi:

```bash
sudo docker compose restart api
```

---

## Memperbarui aplikasi ke versi terbaru

Setelah pemasangan pertama, untuk mengambil pembaruan dari repositori:

```bash
cd /opt/ida
sudo git pull
cd backend
sudo docker compose up -d --build
```

Tunggu sampai selesai, lalu periksa ulang dengan Langkah 5.

Konfigurasi Anda di `backend/.env` **tidak tersentuh** oleh pembaruan, karena
berkas itu tidak ada di repositori.

---

## Masalah yang sering terjadi

### `Permission denied` saat menjalankan skrip

Lupakan `sudo`. Gunakan:

```bash
sudo bash scripts/setup-vps.sh
```

### `docker: command not found` setelah skrip selesai

Docker baru terpasang dan shell Anda belum memuat ulang. Jalankan:

```bash
newgrp docker
```

Atau tutup terminal dan buka lagi.

### Build berhenti dengan `Killed` atau `signal: killed`

Server kehabisan memori saat membangun. Ini jarang terjadi karena skrip sudah
memasang swap, tetapi kalau terjadi:

```bash
free -h
sudo fallocate -l 4G /swapfile2
sudo chmod 600 /swapfile2
sudo mkswap /swapfile2
sudo swapon /swapfile2
```

Lalu jalankan ulang skrip setup. Langkah yang sudah selesai akan dilewati.

### `port is already allocated`

Ada container lama yang masih memakai port yang sama:

```bash
cd /opt/ida/backend
sudo docker compose down
sudo docker compose up -d
```

### Halaman terbuka tapi semua tombol gagal

Biasanya cookie ditolak karena situs dibuka lewat `http://` padahal seharusnya
`https://`. Pastikan alamatnya diawali `https://`.

### Lupa passcode

Passcode tidak bisa dibaca kembali, hanya hash-nya yang disimpan. Buat yang
baru:

```bash
cd /opt/ida/backend
sudo docker compose run --rm -T api python -m scripts.make_passcode
```

Salin baris `ACCESS_PASSCODE_SHA256=` yang muncul, lalu ganti di `.env`:

```bash
sudo nano .env
```

Cari baris `ACCESS_PASSCODE_SHA256=`, ganti nilainya, simpan dengan `Ctrl + O`
lalu `Enter`, keluar dengan `Ctrl + X`. Setelah itu:

```bash
sudo docker compose up -d --force-recreate api
```

### Ingin melihat log secara langsung

```bash
cd /opt/ida/backend
sudo docker compose logs -f api      # backend
sudo docker compose logs -f frontend # frontend
sudo docker compose logs -f caddy    # sertifikat dan akses
```

Hentikan dengan `Ctrl + C`. Itu hanya menghentikan tampilan log, bukan
aplikasinya.

---

## Perintah yang akan sering dipakai

| Keperluan | Perintah |
|---|---|
| Lihat status | `cd /opt/ida/backend && sudo docker compose ps` |
| Lihat log backend | `sudo docker compose logs -f api` |
| Nyalakan ulang backend | `sudo docker compose restart api` |
| Hentikan semua | `sudo docker compose down` |
| Nyalakan semua | `sudo docker compose up -d` |
| Perbarui ke versi terbaru | `cd /opt/ida && sudo git pull && cd backend && sudo docker compose up -d --build` |
| Cek pemakaian disk | `df -h /` dan `docker system df` |
| Bersihkan image lama | `sudo docker image prune -af` |

---

## Keamanan: yang sudah diatur, dan yang perlu Anda jaga

**Sudah diatur aplikasi:**

- Passcode disimpan sebagai hash, bukan teks asli
- Percobaan login dibatasi per alamat IP
- Dokumen hanya bisa diakses setelah login
- HTTPS dengan sertifikat yang diperbarui otomatis
- Dokumentasi API (`/docs`) dimatikan secara default

**Yang perlu Anda jaga:**

- **Passcode minimal 12 karakter.** Ini satu-satunya yang melindungi seluruh
  dokumen Anda. Jangan pakai `123456` atau nama sendiri.
- **Jangan bagikan Groq API key.** Kalau bocor, orang lain bisa memakai kuota
  Anda.
- **Perbarui berkala.** Jalankan Langkah 6 setiap beberapa minggu untuk
  mengambil perbaikan keamanan.
- **Cadangkan dokumen penting.** Data ada di volume Docker di server. Kalau
  server hilang, datanya ikut hilang.

Untuk mencadangkan seluruh data:

```bash
cd /opt/ida/backend
sudo docker run --rm \
  -v ida-data:/data:ro \
  -v "$PWD:/keluaran" \
  alpine tar -czf /keluaran/cadangan-$(date +%F).tar.gz -C /data .
ls -lh cadangan-*.tar.gz
```

Perintah itu memakai container Alpine sementara yang membaca volume `ida-data`
langsung, bukan lewat container `api`. Alasannya: container `api` berjalan
sebagai pengguna biasa, sehingga sebagian berkas di `/data` bisa tidak terbaca
dan hasil cadangannya tidak lengkap tanpa terlihat gagal. Nama volume
`ida-data` berasal dari `docker-compose.yml`; kalau Anda mengubah nama proyek,
sesuaikan namanya (lihat dengan `sudo docker volume ls`).

Untuk memulihkan dari cadangan:

```bash
cd /opt/ida/backend
sudo docker compose down
sudo docker run --rm \
  -v ida-data:/data \
  -v "$PWD:/sumber:ro" \
  alpine sh -c "cd /data && tar -xzf /sumber/cadangan-2026-01-01.tar.gz"
sudo docker compose up -d
```

---

## Setelah semuanya jalan

Kalau Anda ingin mengubah tampilan atau menambah fitur, panduan untuk
menjalankan di komputer sendiri ada di [PANDUAN-LOKAL.md](PANDUAN-LOKAL.md).
Di sana Anda bisa mengubah kode dan langsung melihat hasilnya tanpa
menyentuh server.
