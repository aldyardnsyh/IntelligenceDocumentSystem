"""Uji end-to-end: frontend proxy -> backend. Tanpa browser, memakai HTTP langsung.

Jalankan dengan backend di :8000 dan frontend di :3000.
Setiap langkah mencetak PASS/FAIL dan berhenti di kegagalan pertama.
"""

import contextlib
import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:3000"
PASSCODE = "uji-e2e"
SAMPLE = (
    "# Panduan\n\nSLA Penyelesaian adalah batas waktu maksimal penyelesaian "
    "permintaan, yaitu dua hari kerja sejak permintaan dicatat.\n"
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" -- {detail}" if detail else ""))
    return ok


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        # 1. Proxy meneruskan ke backend
        r = client.get("/api/v1/health")
        if not check("proxy /api/v1/health", r.status_code == 200, r.text[:80]):
            return 1
        if not check(
            "respons berupa JSON, bukan HTML",
            "application/json" in r.headers.get("content-type", ""),
        ):
            return 1

        # 2. Login
        r = client.post("/api/v1/auth/verify", json={"passcode": PASSCODE})
        if not check("login 200", r.status_code == 200, r.text[:60]):
            return 1
        token = client.cookies.get("ida_session")
        if not check("cookie ida_session diterbitkan", bool(token)):
            return 1

        # 3. Endpoint terlindungi dengan cookie
        r = client.get("/api/v1/settings")
        if not check("settings dengan cookie", r.status_code == 200, r.text[:80]):
            return 1

        # Bersihkan dokumen sisa run sebelumnya. E2E harus idempoten: run kedua
        # tidak boleh mewarisi data run pertama, karena langkah 4 membutuhkan
        # indeks yang benar-benar kosong.
        r = client.get("/api/v1/documents")
        for doc in r.json():
            client.delete(f"/api/v1/documents/{doc['id']}")
        r = client.get("/api/v1/documents")
        if not check("mulai dari indeks kosong", r.json() == [], f"sisa={len(r.json())}"):
            return 1

        # 4. Gerbang not_found: tanyakan saat indeks masih kosong. Tanpa satu
        # pun kandidat, gate harus menolak -- pada threshold berapa pun. Ini
        # membuktikan gate-nya bekerja pada kondisi yang pasti, tanpa
        # bergantung pada kalibrasi skor stub vs model asli.
        with client.stream(
            "POST", "/api/v1/chat/query",
            json={"question": "berapa hari untuk penyelesaian permintaan"},
        ) as r:
            types = set()
            for line in r.iter_lines():
                if line.startswith("data:") and line.strip() != "data: [DONE]":
                    with contextlib.suppress(json.JSONDecodeError):
                        types.add(json.loads(line[5:].strip()).get("type", "?"))
        if not check(
            "not_found saat indeks kosong",
            "not_found" in types,
            f"events={sorted(types)}",
        ):
            return 1

        # 4. Endpoint terlindungi tanpa cookie -> 401
        with httpx.Client(base_url=BASE, timeout=30.0) as anon:
            r = anon.get("/api/v1/settings")
            if not check("settings tanpa cookie ditolak", r.status_code == 401):
                return 1

        # 5. Upload dokumen fokus. Dipilih yang overlap-nya tinggi supaya lolos
        # ambang produksi 0.5 bahkan dengan stub -- yang diuji di sini adalah
        # pipeline ujung-ke-ujung pada pengaturan default, bukan kalibrasi.
        doc_text = (
            "Penyelesaian permintaan membutuhkan dua hari. "
            "Penyelesaian permintaan dicatat segera.\n"
        )
        r = client.post(
            "/api/v1/documents/upload",
            files={"file": ("fokus.md", doc_text.encode(), "text/markdown")},
        )
        if not check("upload 202", r.status_code == 202, r.text[:100]):
            return 1
        doc_id = r.json()["id"]
        print(f"       document id: {doc_id}")

        # 6. Tunggu ingestion
        ready = False
        for _ in range(20):
            r = client.get(f"/api/v1/documents/{doc_id}/status")
            status = r.json().get("status")
            if status in ("ready", "failed"):
                ready = status == "ready"
                break
            time.sleep(0.5)
        if not check("ingestion ready", ready, f"status={status}"):
            return 1

        # 7. Chat -> SSE harus memuat sitasi, pada ambang default produksi.
        with client.stream(
            "POST", "/api/v1/chat/query",
            json={"question": "penyelesaian permintaan"},
        ) as r:
            if not check("chat stream 200", r.status_code == 200):
                return 1
            types: set[str] = set()
            for line in r.iter_lines():
                if line.startswith("data:") and line.strip() != "data: [DONE]":
                    with contextlib.suppress(json.JSONDecodeError):
                        types.add(json.loads(line[5:].strip()).get("type", "?"))
        if not check("event sitasi ada", "citations" in types, f"events={sorted(types)}"):
            return 1
        if not check("event done ada", "done" in types):
            return 1

        # 8. (Dihapus: dulu menguji not_found dengan pertanyaan asing pada
        # threshold 0. Itu tidak valid -- threshold 0 menerima apa pun yang
        # punya satu tabrakan hash. not_found sudah diuji pada langkah 4
        # dengan indeks kosong, yang pasti benar pada threshold berapa pun.)

        # 9. Analitik terisi dari log nyata
        r = client.get("/api/v1/analytics/summary")
        has_latency = len(r.json().get("latency", [])) >= 1
        if not check("analitik latency terisi", has_latency):
            return 1

        # 10. Logout mencabut akses
        r = client.post("/api/v1/auth/logout")
        if not check("logout 204", r.status_code == 204):
            return 1
        r = client.get("/api/v1/settings")
        if not check("setelah logout ditolak", r.status_code == 401):
            return 1

    failed = sum(1 for _, ok, _ in results if not ok)
    print()
    print(f"{len(results) - failed}/{len(results)} lulus")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
