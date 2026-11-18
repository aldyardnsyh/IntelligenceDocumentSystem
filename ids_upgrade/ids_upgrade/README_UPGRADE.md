# Upgrade ingest: PDF hukum hasil scan -> chunk terstruktur + multimodal

## Masalah pada hasil chunk sebelumnya (dari teks yang Anda tempel)
1. **Sumber teks salah**: PDF ini scan yang membawa lapisan teks OCR bawaan berkualitas buruk (CER 42%, urutan baca kacau,
   mis. "Menimbang/Mengingat" di akhir, Pasal 3 sebelum Pasal 2). Lapisan itu harus diabaikan; render halaman lalu OCR ulang.
2. **Chunk karakter tetap** memotong di tengah kata ("yediakan sarana ... Pelaksan") dan tanpa metadata Pasal/halaman.
3. **Furnitur halaman ikut terindeks**: kop "PRESIDEN REPUBLIK INDONESIA", nomor halaman, penanda lanjutan ("(2) Penyediaan ...").
4. **Elemen visual hilang** (lambang, paraf, tanda tangan, stempel) -> bukan multimodal.

## Alur baru
`ocr_pipeline.py` render 300 DPI -> normalisasi cahaya + deskew -> Tesseract `ind` (urutan baca per baris) -> deteksi elemen visual
`text_cleaning.py` buang kop/nomor/catchword (berdasar posisi), koreksi salah-OCR (leksikon internal + huruf tertukar c~e, l~i, rn~m, cl~d),
pulihkan penanda butir/ayat yang hilang, sambung baris & kata terpotong lintas halaman
`legal_chunker.py` chunk per Pasal / ayat / butir definisi (small-to-big), metadata BAB>Bagian>Pasal>ayat, halaman, sitasi siap pakai,
`contextual_text` untuk embedding, chunk visual
`evaluate.py` bandingkan dengan data valid (`gold_perpres_76_2013.json`) + `gold_qa.json`

## Menjalankan
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-ind
pip install -r requirements.txt
python ingest.py --pdf Perpres_76_2013.pdf --out out \
  --title "Perpres No. 76 Tahun 2013 tentang Pengelolaan Pengaduan Pelayanan Publik" --short "Perpres 76/2013"
python evaluate.py --pdf Perpres_76_2013.pdf --out out
python evaluate.py --pdf Perpres_76_2013.pdf --out out --retriever app_adapter:search   # uji retriever Anda
```
`app_adapter.search(question, k) -> list[str]` mengembalikan teks chunk teratas dari aplikasi Anda.

## Integrasi ke aplikasi
- Ganti tahap ekstraksi+chunking dengan `ingest.run(...)`; keluarannya `out/chunks.jsonl`.
- Embed field `contextual_text`; simpan `citation`, `pasal`, `ayat`, `page_start/end`, `parent_text` sebagai metadata.
- Chunk dengan `extra.has_children=true` (induk Pasal yang dipecah) tidak perlu diindeks; pakai untuk ekspansi konteks saat menjawab.
- Chunk `visual` punya `extra.crop_path`: tampilkan sebagai thumbnail pada sitasi.

## Hasil pada Perpres 76/2013 (in-sample, 1 dokumen)
| | lapisan bawaan | OCR mentah | pipeline baru |
|---|---|---|---|
| CER / WER | 42.4% / 59.5% | 5.9% / 6.0% | 0.9% / 1.1% |

Struktur: 21/21 Pasal, 41/41 ayat; kemiripan teks per Pasal rata-rata 100.0%, minimum 99.6%.
Retrieval BM25 saja (24 pertanyaan): hit@1 62.5% -> 75.0%, hit@5 83.3% -> 91.7%.

## Keterbatasan yang perlu diketahui
- Aturan pembersihan dikembangkan sambil melihat dokumen ini; **belum diuji pada scan lain**. Uji pada 1-2 UU/Perpres lain sebelum demo.
- Sisa galat OCR yang diketahui: "lan" (seharusnya "lain") di Pasal 2 ayat (2) huruf d; nama "Bistok Simbolon" terbaca salah pada halaman 14.
- Caption visual default berupa template (jenis + posisi + teks terdekat). Caption semantik via Claude vision (`--vlm`) dan
  transkripsi halaman via VLM **belum diuji** di sini (tidak ada API key di sandbox).
- Retrieval yang diukur hanya BM25. Embedding multibahasa, reranker, dan fusi hibrida belum diuji (model tidak bisa diunduh di sandbox).
- Baseline "chunk 500 karakter" adalah perkiraan saya dari keluaran yang Anda tempel, bukan kode aplikasi Anda (repo tidak bisa saya akses).
