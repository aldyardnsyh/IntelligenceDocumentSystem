"""Bangun ulang seluruh vektor dengan model embedding yang aktif sekarang.

Kenapa ini perlu: vektor yang tersimpan dibuat oleh model tertentu. Kalau
modelnya berganti (`USE_LOCAL_EMBEDDING` diubah, atau `EMBEDDING_MODEL`
diganti), vektor lama dan baru **tidak sebanding** walau dimensinya sama.
Gejalanya menipu: dokumen berstatus `ready`, pertanyaan wajar, tapi
retrieval mengembalikan hasil acak atau tidak menemukan apa pun, tanpa
satu pun error yang menunjuk penyebabnya.

Skrip ini membaca ulang isi chunk dari database metadata (isinya masih utuh),
menghitung vektor baru dengan provider yang aktif, lalu mengganti seluruh isi
koleksi vektor. Dokumen tidak perlu diunggah ulang.

Jalankan dari direktori `backend`:

    python -m scripts.reindex
    python -m scripts.reindex --dry-run   # hanya laporkan apa yang akan dikerjakan
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.core.config import get_settings
from app.dependencies import _index_entries  # noqa: PLC0415
from app.providers.embedding import build_embedding_provider
from app.repositories.sqlite_repo import SqliteRepository
from app.services.retrieval.retriever import COLLECTION, HybridRetriever
from app.services.retrieval.vector_store import VectorRecord, build_vector_store

logger = logging.getLogger(__name__)


async def run(*, dry_run: bool) -> int:
    settings = get_settings()

    if not settings.is_sqlite_mode:
        print(
            "Skrip ini hanya untuk mode SQLite. Mode Supabase belum didukung; "
            "jalankan reindex lewat tooling Supabase.",
            file=sys.stderr,
        )
        return 1

    repository = SqliteRepository(settings.sqlite_fallback_path, defaults=settings)
    chunks = await asyncio.to_thread(repository.all_chunks)
    if not chunks:
        print("Tidak ada chunk tersimpan. Tidak ada yang perlu diindeks ulang.")
        return 0

    embedding = build_embedding_provider(settings)
    print(f"Provider embedding: {embedding.name} ({settings.embedding_model})")
    print(f"Chunk tersimpan   : {len(chunks)}")

    if dry_run:
        print("Dry run: tidak ada yang diubah.")
        return 0

    store = build_vector_store(settings)
    retriever = HybridRetriever(store)

    # Vektor lama dibuang lebih dulu. Menggabungkan vektor dari dua model
    # berbeda di satu koleksi menghasilkan skor yang tidak berarti.
    await asyncio.to_thread(store.delete_collection, COLLECTION)
    print("Koleksi lama dihapus.")

    batch_size = max(1, settings.embedding_batch_size)
    total = 0
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = await asyncio.to_thread(
            embedding.embed_documents, [chunk.content for chunk in batch]
        )
        records = [
            VectorRecord(
                id=chunk.id,
                embedding=vector,
                metadata={
                    "document_id": chunk.document_id,
                    "document_name": chunk.document_name or "dokumen",
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                },
            )
            for chunk, vector in zip(batch, vectors, strict=True)
        ]
        await asyncio.to_thread(store.upsert, records, COLLECTION)
        total += len(records)
        print(f"  {total}/{len(chunks)} chunk diindeks ulang", end="\r")

    print()
    restored = retriever.rebuild(_index_entries(repository))
    print(f"Selesai: {total} chunk diindeks ulang, indeks kata {restored} entri.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Laporkan jumlah chunk tanpa mengubah apa pun.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)-8s %(message)s")
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())