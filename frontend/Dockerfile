# syntax=docker/dockerfile:1.7
#
# Image produksi untuk frontend Next.js.
#
# `output: "standalone"` di next.config.ts membuat build_next_only menghasilkan
# server yang tidak butuh `node_modules` penuh. Tanpa itu, image ini akan
# membawa seluruh dependency Next.js (~400 MB); dengan standalone, biasanya
# turun ke ~150 MB.

# ---------------------------------------------------------------- deps
FROM node:22-alpine AS deps

# Alpine punya musl libc. `libc6-compat` menyediakan glibc shim yang dibutuhkan
# beberapa paket native (misalnya swc, compiler WASM Next.js). Tanpa itu build
# gagal dengan error `ld-linux-x86-64.so.2: not found` yang membingungkan.
RUN apk add --no-cache libc6-compat

WORKDIR /app
COPY package.json package-lock.json* ./

# `--legacy-peer-deps` dipakai karena beberapa paket UI punya rentang peer yang
# saling tumpang tindih. npm 10 lebih ketat soal ini dan build gagal walaupun
# pohon dependensinya sebenarnya valid.
RUN --mount=type=cache,target=/root/.npm \
    npm ci --legacy-peer-deps --no-audit --no-fund

# ---------------------------------------------------------------- builder
FROM node:22-alpine AS builder

RUN apk add --no-cache libc6-compat
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Argumen build perlu ada saat `next build` berjalan, bukan hanya saat runtime.
# Rewrite di next.config.ts dievaluasi pada waktu build, jadi `BACKEND_ORIGIN`
# yang salah di sini akan menghasilkan proxy yang menunjuk ke host yang tidak
# benar -- dan gejalanya baru muncul saat request pertama.
ARG NEXT_PUBLIC_USE_BACKEND=1
ARG BACKEND_ORIGIN=http://api:8000
ARG NEXT_PUBLIC_API_BASE_URL=
ARG NEXT_PUBLIC_REPO_URL=
ARG NEXT_PUBLIC_API_DOCS_URL=
ARG NEXT_PUBLIC_LANGFUSE_URL=
# Hash passcode mode lokal (FNV-1a 16 hex). SENGaja tanpa prefiks
# `NEXT_PUBLIC_`: nilai ini hanya dibaca server (`src/lib/auth/session.ts`),
# dan prefix itu akan meng-inline nilainya ke bundle browser.
ARG DEMO_PASSCODE=
ENV NEXT_PUBLIC_USE_BACKEND=$NEXT_PUBLIC_USE_BACKEND \
    BACKEND_ORIGIN=$BACKEND_ORIGIN \
    NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_REPO_URL=$NEXT_PUBLIC_REPO_URL \
    NEXT_PUBLIC_API_DOCS_URL=$NEXT_PUBLIC_API_DOCS_URL \
    NEXT_PUBLIC_LANGFUSE_URL=$NEXT_PUBLIC_LANGFUSE_URL \
    DEMO_PASSCODE=$DEMO_PASSCODE

# `NEXT_TELEMETRY_DISABLED` mematikan telemetry Next.js. Selain privasi, build
# jadi lebih cepat dan tidak pernah gagal karena tries menghubungi jaringan.
ENV NEXT_TELEMETRY_DISABLED=1

# Batas heap Node saat build.
#
# Node menghitung batas heap defaultnya dari RAM yang terlihat, dan di
# container dengan batas memori, perhitungan itu bisa terlalu optimistis.
# Di server 2 GB, `next build` yang memakai heap besar akan membuat kernel
# memilih antara membunuh proses build (gagal, harus ulang dari awal) atau
# memakai swap (lambat tapi selesai).
#
# 1536 MB cukup untuk proyek ini dan menyisakan ruang untuk sistem. Kalau
# nanti build gagal dengan "JavaScript heap out of memory", naikkan angka
# ini, bukan RAM server.
ENV NODE_OPTIONS="--max-old-space-size=1536"

RUN --mount=type=cache,target=/root/.npm \
    npm run build

# ---------------------------------------------------------------- runtime
FROM node:22-alpine AS runtime

RUN apk add --no-cache libc6-compat
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Server standalone berjalan sebagai non-root. Menjalankan Next sebagai root di
# dalam container berarti satu RCE di aplikasi langsung memberi akses root ke
# host.
RUN addgroup -g 1001 -S nodejs \
    && adduser -S -u 1001 -G nodejs nextjs

# Yang disalin hanya hasil build standalone beserta asset statis dan publik.
# `node_modules` penuh sengaja tidak ikut.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD wget -qO- http://127.0.0.1:3000/api/healthz >/dev/null || exit 1

CMD ["node", "server.js"]
