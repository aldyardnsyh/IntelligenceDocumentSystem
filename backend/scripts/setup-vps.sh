#!/usr/bin/env bash
#
# Setup satu kali untuk VPS yang menjalankan Intelligent Document Assistant.
#
# Skrip ini menyiapkan semuanya dari server kosong sampai aplikasi jalan:
# swap, Docker, kode, konfigurasi, build, dan verifikasi. Bisa dijalankan
# langsung dari OrcaTerm (terminal web Tencent) tanpa SSH dari komputer lain.
#
# Pemakaian:
#   bash setup-vps.sh
#
# Skrip ini idempoten: aman dijalankan ulang. Langkah yang sudah selesai
# akan dilewati, dan konfigurasi yang sudah ada tidak ditimpa tanpa bertanya.
#
# Yang TIDAK bisa dikerjakan skrip ini, dan harus Anda lakukan di panel:
#   Buka port 80 dan 443 di firewall penyedia. Tanpa itu, Caddy tidak bisa
#   menerbitkan sertifikat dan situs tidak bisa diakses dari internet.

set -euo pipefail

# ------------------------------------------------------------------ pengaturan
REPO_URL="${REPO_URL:-https://github.com/aldyardnsyh/IntelligenceDocumentSystem.git}"
APP_DIR="${APP_DIR:-/opt/ida}"
DOMAIN=""
EMAIL=""
GROQ_KEY=""
PASSCODE=""

# Warna, dimatikan kalau output bukan terminal (misalnya saat di-log ke berkas).
if [ -t 1 ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'
    GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
    BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi

step() { printf '\n%s==> %s%s\n' "$BOLD" "$1" "$RESET"; }
info() { printf '    %s\n' "$1"; }
ok()   { printf '    %s%s%s\n' "$GREEN" "$1" "$RESET"; }
warn() { printf '    %s%s%s\n' "$YELLOW" "$1" "$RESET"; }
die()  { printf '\n%sGAGAL: %s%s\n' "$RED" "$1" "$RESET" >&2; exit 1; }

# Jalankan perintah sebagai root, lewat sudo kalau perlu.
as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

# Set atau ganti satu nilai di berkas .env.
# Dipakai awk, bukan sed, karena nilai seperti URL memuat karakter yang
# dianggap istimewa oleh sed (``/`` dan ``&``), dan escaping manual di sana
# mudah salah.
set_env() {
    local key="$1" value="$2" file="$3"
    if grep -q "^${key}=" "$file"; then
        awk -v k="$key" -v v="$value" '
            index($0, k"=") == 1 { print k"="v; next }
            { print }
        ' "$file" > "${file}.tmp"
        mv "${file}.tmp" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}

# Baca satu baris tanpa menampilkan isinya.
#
# `read -s` mematikan echo lewat termios, dan itu tidak bekerja kalau stdin
# bukan terminal. OrcaTerm dan sebagian terminal web lain kadang begitu,
# terutama saat skrip dijalankan lewat pipa. Tanpa fallback, `read -s` gagal
# dengan "not a tty" dan skrip berhenti di tengah jalan.
#
# Fallback-nya `read` biasa, dengan peringatan supaya pengguna tahu isinya
# akan terlihat. Lebih baik memberi tahu daripada gagal diam-diam.
baca_rahasia() {
    local prompt="$1" var="$2" hasil
    if [ -t 0 ]; then
        read -r -s -p "$prompt" hasil
        printf '\n'
    else
        warn "Terminal ini tidak mendukung input tersembunyi."
        warn "Isi yang Anda ketik akan terlihat di layar."
        read -r -p "$prompt" hasil
    fi
    printf -v "$var" '%s' "$hasil"
}

# ------------------------------------------------------------------ 1. periksa
step "1/8  Memeriksa sistem"

if [ ! -r /etc/os-release ]; then
    die "Berkas /etc/os-release tidak ada, sistem operasi tidak dikenali."
fi
# shellcheck disable=SC1091
. /etc/os-release
info "Sistem operasi : ${PRETTY_NAME:-tidak diketahui}"

case "${ID:-}" in
    ubuntu|debian) ;;
    *) warn "Skrip ini diuji di Ubuntu dan Debian. Distro lain mungkin berbeda." ;;
esac

# RAM total dalam MB.
RAM_MB=$(awk '/MemTotal/ { printf "%d", $2 / 1024 }' /proc/meminfo)
info "RAM            : ${RAM_MB} MB"

# Aplikasi ini butuh sekitar 1,6 GB: Ubuntu dan Docker 300 MB, FastAPI dan
# ChromaDB 250 MB, torch 600 MB, model embedding 470 MB.
if [ "$RAM_MB" -lt 900 ]; then
    die "RAM ${RAM_MB} MB terlalu kecil. Minimum 1 GB, disarankan 2 GB."
elif [ "$RAM_MB" -lt 1500 ]; then
    SWAP_GB=4
    warn "RAM kurang dari 1,5 GB, swap ${SWAP_GB} GB akan ditambahkan."
else
    SWAP_GB=2
    info "RAM cukup, swap ${SWAP_GB} GB dipasang sebagai jaring pengaman."
fi

# Ruang disk. Sistem, image, dan build cache memakai sekitar 9 GB.
AVAIL_GB=$(df -BG --output=avail / | tail -1 | tr -d 'G ')
info "Disk tersedia  : ${AVAIL_GB} GB"
if [ "$AVAIL_GB" -lt 15 ]; then
    die "Disk hanya ${AVAIL_GB} GB. Butuh minimal 15 GB, disarankan 20 GB."
fi

if ! command -v curl >/dev/null 2>&1; then
    info "Memasang curl..."
    as_root apt-get update -qq
    as_root apt-get install -y -qq curl
fi

# ------------------------------------------------------------------ 2. swap
step "2/8  Menyiapkan swap"

if swapon --show | grep -q .; then
    CURRENT_SWAP=$(free -m | awk '/^Swap:/ { print $2 }')
    ok "Swap sudah aktif (${CURRENT_SWAP} MB), dilewati."
else
    info "Membuat /swapfile ${SWAP_GB} GB..."
    # fallocate gagal di sebagian filesystem. Kalau itu terjadi, dd dipakai:
    # lebih lambat karena benar-benar menulis, tapi selalu bekerja.
    if ! as_root fallocate -l "${SWAP_GB}G" /swapfile 2>/dev/null; then
        warn "fallocate tidak didukung, memakai dd (lebih lambat)."
        as_root dd if=/dev/zero of=/swapfile bs=1M count=$((SWAP_GB * 1024)) status=none
    fi
    # Berkas swap berisi salinan memori proses, termasuk passcode yang sedang
    # dibandingkan dan potongan dokumen yang sedang diproses.
    as_root chmod 600 /swapfile
    as_root mkswap -q /swapfile >/dev/null
    as_root swapon /swapfile

    if ! grep -q '^/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' | as_root tee -a /etc/fstab >/dev/null
    fi
    # Nilai rendah membuat sistem lebih memilih membuang cache daripada
    # memindahkan memori aktif ke disk.
    if ! grep -q '^vm.swappiness' /etc/sysctl.conf; then
        echo 'vm.swappiness=10' | as_root tee -a /etc/sysctl.conf >/dev/null
    fi
    as_root sysctl -q -p

    SWAP_NOW=$(free -m | awk '/^Swap:/ { print $2 }')
    ok "Swap aktif: ${SWAP_NOW} MB"
fi

# ------------------------------------------------------------------ 3. docker
step "3/8  Memasang Docker"

if command -v docker >/dev/null 2>&1; then
    ok "Docker sudah terpasang: $(docker --version)"
else
    info "Memasang Docker dari repositori resmi..."
    as_root apt-get update -qq
    as_root apt-get install -y -qq ca-certificates gnupg git

    as_root install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | as_root gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    as_root chmod a+r /etc/apt/keyrings/docker.gpg

    ARCH=$(dpkg --print-architecture)
    CODENAME=$(. /etc/os-release && echo "${VERSION_CODENAME:-noble}")
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
        | as_root tee /etc/apt/sources.list.d/docker.list >/dev/null

    as_root apt-get update -qq
    as_root apt-get install -y -qq \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ok "Docker terpasang: $(docker --version)"
fi

if ! docker compose version >/dev/null 2>&1; then
    die "Plugin 'docker compose' tidak tersedia. Pastikan docker-compose-plugin terpasang."
fi
info "Compose        : $(docker compose version --short 2>/dev/null || echo ada)"

if ! docker info >/dev/null 2>&1; then
    die "Docker daemon tidak berjalan. Coba: sudo systemctl start docker"
fi

if ! command -v git >/dev/null 2>&1; then
    as_root apt-get install -y -qq git
fi

# ------------------------------------------------------------------ 4. kode
step "4/8  Mengambil kode"

# Unduh kode lewat git, dengan fallback arsip HTTPS.
#
# Fallback ini bukan kemewahan: `git clone` bisa gagal di server baru karena
# jaringan yang memblokir git, versi TLS yang tidak cocok, atau permintaan
# kredensial yang tidak bisa dijawab dari terminal web. Kegagalan di sini
# menghentikan seluruh setup, padahal kode yang sama bisa diunduh lewat HTTPS
# biasa tanpa git sama sekali.
unduh_arsip() {
    local arsip="/tmp/ida-$$.zip"
    local url="${REPO_URL%.git}/archive/refs/heads/master.zip"
    info "Mengunduh arsip dari ${url}..."
    if ! as_root curl -fsSL --retry 3 -o "$arsip" "$url"; then
        die "Gagal mengunduh arsip. Periksa koneksi server, atau salin kode secara manual ke ${APP_DIR}."
    fi
    if ! command -v unzip >/dev/null 2>&1; then
        as_root apt-get install -y -qq unzip >/dev/null 2>&1 || true
    fi
    command -v unzip >/dev/null 2>&1 \
        || die "unzip tidak tersedia. Pasang dengan: sudo apt-get install -y unzip"
    as_root rm -rf "${APP_DIR}.tmp"
    as_root mkdir -p "${APP_DIR}.tmp"
    as_root unzip -q "$arsip" -d "${APP_DIR}.tmp"
    # Arsip GitHub membungkus isinya dalam satu direktori bernama
    # "<repo>-master". Isinya dipindah ke APP_DIR supaya strukturnya sama
    # dengan hasil git clone.
    local dalam
    dalam=$(as_root find "${APP_DIR}.tmp" -maxdepth 1 -mindepth 1 -type d | head -1)
    [ -n "$dalam" ] || die "Arsip tidak berisi direktori proyek."
    as_root rm -rf "$APP_DIR"
    as_root mv "$dalam" "$APP_DIR"
    as_root rm -rf "${APP_DIR}.tmp" "$arsip"
    ok "Kode diunduh lewat arsip ke ${APP_DIR}"
}

if [ -d "${APP_DIR}/.git" ]; then
    info "Kode sudah ada di ${APP_DIR}, memperbarui..."
    if as_root git -C "$APP_DIR" fetch --quiet origin \
        && as_root git -C "$APP_DIR" reset --hard --quiet origin/master; then
        ok "Kode diperbarui ke $(git -C "$APP_DIR" log -1 --format=%h)"
    else
        warn "Pembaruan lewat git gagal, mengunduh arsip sebagai gantinya."
        unduh_arsip
    fi
elif [ -d "$APP_DIR" ] && [ -f "${APP_DIR}/backend/docker-compose.yml" ]; then
    # Kode sudah ada tetapi tanpa .git, misalnya hasil unduhan arsip sebelumnya.
    # Membiarkannya apa adanya lebih aman daripada menimpanya, karena bisa jadi
    # operator menyalin kode secara manual dan mengubah sesuatu di sana.
    info "Kode sudah ada di ${APP_DIR} (tanpa git), dilewati."
else
    info "Mengunduh dari ${REPO_URL}..."
    as_root mkdir -p "$(dirname "$APP_DIR")"
    if as_root git clone --quiet "$REPO_URL" "$APP_DIR" 2>/dev/null; then
        ok "Kode diunduh ke ${APP_DIR}"
    else
        warn "git clone gagal, mencoba unduh arsip."
        unduh_arsip
    fi
fi

BACKEND_DIR="${APP_DIR}/backend"
[ -f "${BACKEND_DIR}/docker-compose.yml" ] \
    || die "docker-compose.yml tidak ditemukan di ${BACKEND_DIR}."

# ------------------------------------------------------------------ 5. konfig
step "5/8  Menyiapkan konfigurasi"

ENV_FILE="${BACKEND_DIR}/.env"
if [ ! -f "$ENV_FILE" ]; then
    as_root cp "${BACKEND_DIR}/.env.example" "$ENV_FILE"
    info "Membuat ${ENV_FILE} dari contoh."
fi

# Kalau sudah dikonfigurasi, tanya mau diubah atau tidak. Tanpa ini,
# menjalankan ulang skrip akan menimpa passcode dan domain yang sudah benar.
SUDAH_ADA=0
if grep -q '^ACCESS_PASSCODE_SHA256=.\+' "$ENV_FILE" 2>/dev/null; then
    SUDAH_ADA=1
    DOMAIN_LAMA=$(grep '^CORS_ORIGINS=' "$ENV_FILE" | head -1 | cut -d= -f2- | sed 's|https\?://||')
    printf '\n'
    warn "Konfigurasi sudah ada (domain: ${DOMAIN_LAMA:-tidak diketahui})."
    if [ -t 0 ]; then
        read -r -p "    Ubah konfigurasi? [y/N] " jawab
    else
        # Tanpa terminal, pertanyaan tidak bisa dijawab. Yang aman adalah
        # tidak mengubah apa pun: konfigurasi yang sudah ada kemungkinan
        # sudah benar, dan menimpanya tanpa konfirmasi bisa mengganti
        # passcode yang sedang dipakai.
        warn "Tidak ada terminal untuk bertanya, konfigurasi dilewati."
        jawab="n"
    fi
    if [[ ! "$jawab" =~ ^[Yy]$ ]]; then
        info "Konfigurasi dilewati."
        SKIP_CONFIG=1
    else
        SKIP_CONFIG=0
    fi
else
    SKIP_CONFIG=0
fi

if [ "$SKIP_CONFIG" -eq 0 ]; then
    # --- domain
    printf '\n'
    info "Domain yang menunjuk ke server ini."
    info "Nama bebas, asalkan domainnya sudah mengarah ke IP publik server ini."
    info "DuckDNS gratis di https://www.duckdns.org, isi kolom 'current ip'."
    while [ -z "$DOMAIN" ]; do
        read -r -p "    Domain: " DOMAIN
        DOMAIN=$(printf '%s' "$DOMAIN" | tr -d '[:space:]' | sed 's|https\?://||; s|/$||')
        if ! printf '%s' "$DOMAIN" | grep -qE '^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$'; then
            warn "Format domain tidak valid: '${DOMAIN}'. Coba lagi."
            DOMAIN=""
        fi
    done

    # --- email
    printf '\n'
    info "Email untuk pemberitahuan kedaluwarsa sertifikat Let's Encrypt."
    info "Isinya bebas, hanya dipakai kalau sertifikat gagal diperbarui."
    read -r -p "    Email [admin@${DOMAIN}]: " EMAIL
    EMAIL=$(printf '%s' "$EMAIL" | tr -d '[:space:]')
    [ -n "$EMAIL" ] || EMAIL="admin@${DOMAIN}"

    # --- passcode
    printf '\n'
    info "Passcode untuk masuk ke aplikasi. Minimal 12 karakter."
    info "Ini satu-satunya yang melindungi seluruh dokumen Anda."
    while [ -z "$PASSCODE" ]; do
        baca_rahasia "    Passcode: " PASSCODE
        if [ "${#PASSCODE}" -lt 12 ]; then
            warn "Kurang dari 12 karakter. Coba lagi."
            PASSCODE=""
        fi
    done
    passcode_ulang=""
    baca_rahasia "    Ulangi passcode: " passcode_ulang
    [ "$PASSCODE" = "$passcode_ulang" ] || die "Passcode tidak sama."
    unset passcode_ulang

    # --- Groq
    printf '\n'
    info "Groq API key dari https://console.groq.com/keys (gratis, 1000 request/hari)."
    while [ -z "$GROQ_KEY" ]; do
        baca_rahasia "    Groq API key: " GROQ_KEY
        case "$GROQ_KEY" in
            gsk_*) ;;
            *) warn "Kunci Groq biasanya diawali 'gsk_'. Periksa lagi."; GROQ_KEY="" ;;
        esac
    done

    # --- hitung hash passcode
    printf '\n'
    info "Membangun image backend untuk menghitung hash passcode."
    info "Ini bagian paling lama, sekitar 5 sampai 15 menit. Tunggu sampai selesai."
    printf '\n'
    ( cd "$BACKEND_DIR" && as_root docker compose build api )

    HASH=$(printf '%s\n' "$PASSCODE" | ( cd "$BACKEND_DIR" && as_root docker compose run --rm -T api \
        python -m scripts.make_passcode --stdin ) 2>/dev/null \
        | grep '^ACCESS_PASSCODE_SHA256=' | head -1 | cut -d= -f2)

    [ -n "$HASH" ] || die "Gagal membuat hash passcode. Lihat pesan di atas."
    [ "${#HASH}" -eq 64 ] || die "Hash yang dihasilkan tidak 64 karakter: ${#HASH}."
    ok "Hash passcode dibuat dan diverifikasi."
    unset PASSCODE

    # --- tulis .env
    set_env ACCESS_PASSCODE_SHA256 "$HASH" "$ENV_FILE"
    set_env LLM_PROVIDER          "groq"                "$ENV_FILE"
    set_env GROQ_API_KEY          "$GROQ_KEY"           "$ENV_FILE"
    set_env CORS_ORIGINS          "https://${DOMAIN}"   "$ENV_FILE"
    set_env DEBUG                 "false"               "$ENV_FILE"
    set_env API_DOCS_ENABLED      "0"                   "$ENV_FILE"
    set_env TRUST_PROXY_HEADERS   "1"                   "$ENV_FILE"
    ok ".env diperbarui."

    # --- tulis Caddyfile
    CADDY="${BACKEND_DIR}/Caddyfile"
    # Polanya dipatok ke awal baris. Mengganti semua kemunculan
    # 'example.com' juga akan mengubah komentar dan alamat email di berkas
    # yang sama, dan komentarnya jadi berbunyi salah.
    as_root sed -i "s|^example\.com {|${DOMAIN} {|" "$CADDY"
    as_root sed -i "s|^\(\s*email\s*\)admin@example\.com|\1${EMAIL}|" "$CADDY"

    if grep -q '^example\.com {' "$CADDY"; then
        die "Ganti domain gagal: 'example.com {' masih ada di Caddyfile."
    fi
    ok "Caddyfile memakai domain ${DOMAIN}."
fi

# ------------------------------------------------------------------ 6. build
step "6/8  Membangun image"

if [ "$SKIP_CONFIG" -eq 1 ]; then
    info "Memeriksa image yang sudah ada..."
fi

info "Membangun backend dan frontend. Bisa 5 sampai 15 menit di server 2 GB."
info "Kalau layar terlihat diam, itu normal: sedang mengunduh torch dan model."
printf '\n'
( cd "$BACKEND_DIR" && as_root docker compose build )
ok "Semua image selesai dibangun."

# ------------------------------------------------------------------ 7. jalan
step "7/8  Menjalankan layanan"

( cd "$BACKEND_DIR" && as_root docker compose up -d )

info "Menunggu API menjawab (maksimal 10 menit)..."
info "Di sini model embedding 470 MB diunduh kalau belum ada."
printf '    '
DEADLINE=$((SECONDS + 600))
SEHAT=0
while [ "$SECONDS" -lt "$DEADLINE" ]; do
    # Yang diperiksa adalah API-nya benar-benar menjawab, bukan status
    # container. Status "healthy" tidak muncul sama sekali selama
    # `start_period` berjalan, sehingga menunggu field itu berarti menunggu
    # tanpa tanda apa pun selama sepuluh menit.
    if curl -fsS --max-time 5 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
        SEHAT=1
        break
    fi
    sleep 10
    printf '.'
done
printf '\n'

if [ "$SEHAT" -eq 1 ]; then
    ok "Container berjalan dan sehat."
else
    warn "Container belum melaporkan sehat dalam 10 menit."
    warn "Ini normal kalau model embedding masih diunduh. Cek dengan:"
    warn "    cd ${BACKEND_DIR} && docker compose logs -f api"
fi

# ------------------------------------------------------------------ 8. verif
step "8/8  Verifikasi"

if curl -fsS --max-time 10 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    ok "API menjawab di port 8000."
    printf '\n'
    curl -fsS --max-time 10 http://127.0.0.1:8000/api/v1/health \
        | (command -v python3 >/dev/null 2>&1 && python3 -m json.tool || cat)
    printf '\n'
else
    warn "API belum menjawab. Cek log:"
    warn "    cd ${BACKEND_DIR} && docker compose logs -f api"
fi

if [ "$SKIP_CONFIG" -eq 0 ]; then
    printf '\n'
    info "Memeriksa sertifikat TLS (bisa sampai 1 menit)..."
    TERBIT=0
    for _ in $(seq 1 12); do
        if curl -fsS --max-time 10 "https://${DOMAIN}/api/v1/health" >/dev/null 2>&1; then
            TERBIT=1
            break
        fi
        sleep 5
    done
    if [ "$TERBIT" -eq 1 ]; then
        ok "HTTPS aktif di https://${DOMAIN}"
    else
        warn "HTTPS belum aktif. Tiga penyebab yang paling sering:"
        warn "  1. Port 80 dan 443 belum dibuka di firewall penyedia."
        warn "     Ini paling sering terjadi. Buka di panel, bukan di dalam server."
        warn "  2. DNS belum menunjuk ke IP server ini."
        warn "     Periksa dengan: nslookup ${DOMAIN}"
        warn "  3. Caddy masih meminta sertifikat. Lihat: docker compose logs caddy"
    fi
fi

# ------------------------------------------------------------------ selesai
printf '\n%s%s%s\n' "$BOLD" "Setup selesai." "$RESET"
printf '\n'
if [ "$SKIP_CONFIG" -eq 0 ]; then
    printf '  Buka di browser : %shttps://%s%s\n' "$GREEN" "$DOMAIN" "$RESET"
    printf '  Masuk dengan    : passcode yang Anda buat tadi\n'
else
    printf '  Aplikasi sudah berjalan di %s\n' "$APP_DIR"
fi
printf '\n'
printf '  %sPerintah harian:%s\n' "$BOLD" "$RESET"
printf '    cd %s\n' "$BACKEND_DIR"
printf '    docker compose logs -f api      # lihat log\n'
printf '    docker compose ps               # status container\n'
printf '    docker compose down             # hentikan\n'
printf '    docker compose up -d            # jalankan lagi\n'
printf '\n'
printf '  %sYang tidak boleh dilakukan:%s\n' "$BOLD" "$RESET"
printf '    Jangan hapus volume ida_ida-data, isinya seluruh dokumen Anda.\n'
printf '    Jangan pakai docker system prune --volumes, flag itu menghapusnya.\n'
printf '\n'
# Kalau memakai DuckDNS, alamatnya bergantung pada IP yang tercatat di sana.
# Kalau IP server berubah, situs mati sampai DuckDNS diperbarui.
case "${DOMAIN:-}" in
    *.duckdns.org)
        SUBDOMAIN="${DOMAIN%%.duckdns.org}"
        printf '  %sCatatan untuk DuckDNS:%s\n' "$BOLD" "$RESET"
        printf '    Kalau IP server ini berubah, perbarui DuckDNS dengan:\n'
        printf '    curl -s "https://www.duckdns.org/update?domains=%s&token=<token>&ip="\n' "$SUBDOMAIN"
        printf '    Token ada di halaman utama duckdns.org setelah masuk.\n'
        printf '\n'
        ;;
esac
