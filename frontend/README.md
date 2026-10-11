# Frontend, Intelligent Document Assistant

Next.js 16 (App Router) + React 19 + Tailwind v4. Tujuh halaman: `/`,
`/chat`, `/documents`, `/analytics`, `/settings`, `/about`, `/login`.

## Dua mode, satu sakelar

| Mode | `NEXT_PUBLIC_USE_BACKEND` | Data dari |
|---|---|---|
| Demo | kosong/tidak diisi | fixture in-browser (`src/lib/mock`) |
| Backend | `1` | FastAPI lewat proxy same-origin |

`NEXT_PUBLIC_*` di-inline saat build. Mengganti mode berarti **restart dev
server atau build ulang**, bukan sekadar restart API.

## Menjalankan

```bash
npm install
cp .env.example .env.local   # set BACKEND_ORIGIN=http://127.0.0.1:8000
npm run dev                  # http://localhost:3000
```

Tanpa `.env.local` sama sekali, aplikasi tetap jalan penuh dengan fixture --
cukup untuk melihat semua halaman tanpa backend.

## Kenapa proxy, bukan CORS

Rewrite `/api/v1/*` ke FastAPI membuat browser hanya mengenal satu origin.
Kalau browser menembak backend langsung, `Set-Cookie: ida_session` milik
origin backend tidak akan sampai ke server action Next, dan login selalu
gagal tanpa pesan yang jelas. `NEXT_PUBLIC_API_BASE_URL` sengaja dibiarkan
kosong; mengisinya dengan URL absolut justru merusak cookie sesi.

## Aturan yang tidak boleh dilanggar

1. **Angka dari API, bukan placeholder.** Chunk count, latency, token,
   ambang retrieval: semua dari endpoint. Angka tebatan di UI adalah bug,
   bukan penyederhanaan.
2. **Kesalahan 401 selalu punya jalan keluar.** `lib/api/http.ts`
   membersihkan gate dan mengarahkan ke login; `ErrorState` menampilkan
   tombol "Masuk ulang".
3. **Tidak ada state yang menebak.** Mode demo dan mode backend harus
   berperilaku sama, termasuk saat 404.

## Verifikasi

```bash
npx tsc --noEmit
npm run lint
npm run build
npx playwright test          # butuh backend + frontend hidup
```

`src/proxy.ts` (bukan `middleware.ts`, sudah deprecated di Next 16) menjaga
halaman. Gate ini memeriksa keberadaan cookie penanda saja;
penegakan sesungguhnya ada di backend.

## Struktur penting

- `src/app/login/actions.ts`, server action login; meneruskan `Set-Cookie`
  backend ke browser (tanpa ini sesi tidak pernah terbentuk).
- `src/lib/api/http.ts`, satu pintu untuk semua request backend.
- `src/components/chat/use-chat.ts`, seluruh state percakapan; stream
  dibatalkan hanya saat pengguna benar-benar pergi.
- `src/proxy.ts`, access gate per halaman.