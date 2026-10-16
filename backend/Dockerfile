# syntax=docker/dockerfile:1.7
#
# Image produksi untuk backend RAG.
#
# Tiga keputusan di sini yang perlu dijelaskan, karena semuanya terlihat
# sepele tapi menentukan besar image dan apakah image-nya bisa dibangun
# sama sekali:
#
# 1. **Torch CPU-only.** `pip install torch` dari PyPI menarik build CUDA
#    beserta seluruh runtime NVIDIA-nya -- ratusan megabyte dependency yang
#    tidak pernah dipakai di CPU. Index `download.pytorch.org/whl/cpu`
#    menghasilkan wheel yang jauh lebih kecil. Untuk aplikasi ini yang hanya
#    memakai CPU, build CUDA murni sia-sia.
#
# 2. **Index CPU dipaksa, bukan sekadar di Preferensikan.** Menulis
#    `--index-url cpu --extra-index-url pypi` -- dan itu pola yang biasa
#    dipakai -- justru *membahayakan* usaha. Kedua flag itu membuat pip
#    menggabungkan kedua index lalu memilih versi tertinggi di gabungan itu.
#    PyPI punya torch 2.8.0 (build CUDA) dan index CPU juga punya 2.8.0, jadi
#    pip berpeluang memilih yang CUDA. Torch karena itu dipasang dengan
#    `--index-url` saja, tanpa extra: paksa dari CPU, tidak ada membran.
#
# 3. **Multi-stage.** Toolchain kompilasi (gcc, headers) hanya ada di stage
#    builder; image runtime tidak membawa compiler sama sekali. Image akhir
#    jadi lebih kecil dan permukaan serangannya lebih kecil.

# ---------------------------------------------------------------- builder
FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv

RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# gcc dan friends hanya untuk membangun wheel yang tidak punya build publik,
# misalnya `tokenizers` (Rust) dan beberapa addon Chroma. Tidak ikut ke image
# runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# pip/setuptools/wheel harus dari PyPI, jadi tahap ini sengaja membiarkan index
# bawaan -- tidak ada kebutuhan index CPU di sini.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Layer dependensi dipisah dari layer source supaya perubahan kode tidak
# memicu unduhan ulang torch. Ini bedanya rebuild 5 menit dan 40 detik.
COPY pyproject.toml README.md ./

# Torch CPU, dipaksa dari index CPU saja. Setelah ini terpasang, langkah
# `pip install .` di bawah memenuhi `torch>=2.8` tanpa memasang ulang --
# termasuk tanpa menarik build CUDA dari PyPI.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        torch==2.8.0

# Stub supaya `pip install .` punya paket yang bisa dideteksi setuptools,
# tanpa menyalin seluruh source ke dalam layer yang sudah berisi torch.
COPY app/__init__.py app/__init__.py

# Source lengkap, lalu satu-satunya `pip install .`. Versi dependency hidup di
# pyproject; tidak ada daftar kedua yang bisa berubah sendiri.
COPY app/ ./app/
# Extra `[observability]` ikut dipasang: tanpa itu, `TRACING_ENABLED=1` di env
# tidak pernah efektif di image karena langfuse tidak terpasang. Kegagalannya
# hanya muncul sebagai warning di log saat tracing dimatikan diam-diam.
RUN pip install --no-cache-dir ".[observability]"

# --------------------------------------------------------------- runtime
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Data harus berada di path yang di-mount sebagai volume. Kalau data ditulis
    # ke /tmp atau direktori image, semuanya hilang saat container dibuang.
    CHROMA_PERSIST_DIR=/data/chroma \
    SQLITE_FALLBACK_PATH=/data/metadata.db \
    # Cache model embedding diletakkan di volume yang sama dengan metadata.
    # Defaultnya ada di home user, yang merupakan writable layer container:
    # setiap `up --build` mengunduh ulang model ~470 MB.
    HF_HOME=/data/huggingface \
    # Caddy ada di depan API, jadi header proxy boleh dipercaya: API hanya
    # terekspos di network internal compose, tidak pernah langsung dari
    # internet. Tanpa ini, semua klien terlihat sebagai IP Caddy dan rate limit
    # login jadi satu bucket global.
    TRUST_PROXY_HEADERS=1

# `curl` hanya untuk health check; `tini` untuk reaps proses zombie dan
# meneruskan sinyal SIGTERM dengan benar.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data && chown -R appuser:appuser /data

COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser scripts ./scripts
COPY --chown=appuser:appuser pyproject.toml ./

# `scripts/` ikut ke image, bukan hanya `app`. Alasannya operasional:
# `make_passcode` mengimpor `app.core.config`, yang butuh pydantic. Di server
# Ubuntu yang polos, `python3 -m scripts.make_passcode` akan gagal dengan
# ModuleNotFoundError, padahal itu justru langkah bootstrap pertama. Dengan
# skripnya di dalam image, langkah itu cukup lewat `docker compose run` --
# tanpa memasang Python apa pun di host.

USER appuser
EXPOSE 8000

# Health check memakai endpoint yang benar-benar memeriksa dependensi, bukan
# sekadar "/". `/api/v1/health` menyentuh repository, memory store, dan vector
# store, jadi container yang dilaporkan "up" tapi dependensinya mati akan
# terdeteksi.
#
# `start-period` longgar karena lifespan mengunduh model embedding (~470 MB)
# sebelum server listen. Versi 90s sering habis di server 1 GB dengan disk
# lambat, dan karena healthcheck tidak memicu restart, `docker compose up`
# berhenti dengan "dependency failed to start".
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

# `tini` sebagai PID 1: tanpa itu, SIGTERM tidak sampai ke uvicorn dan
# `lifespan` tidak pernah menjalankan shutdown, sehingga ingestion yang sedang
# berjalan menggantung.
#
# `--proxy-headers --forwarded-allow-ips=*` aman di sini karena container ini
# hanya terjangkau dari network compose (lihat docker-compose.yml: Caddy
# satu-satunya yang mempublikasikan port).
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--no-server-header", "--timeout-keep-alive", "65", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
