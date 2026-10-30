"use client";

import { useEffect, useRef, useState } from "react";
import { FileWarning } from "lucide-react";

const WORKER_SRC = "/pdf.worker.min.mjs";

/**
 * Pratinjau PDF tanpa iframe: tiap halaman di-render PDF.js ke canvas.
 * Iframe blob diblokir Edge ("This page has been blocked"), canvas tidak.
 */
export function PdfCanvasPreview({ fileUrl, filename }: { fileUrl: string; filename: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [pageCount, setPageCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");

    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = WORKER_SRC;

        const response = await fetch(fileUrl);
        const data = new Uint8Array(await response.arrayBuffer());
        const task = pdfjs.getDocument({ data });
        const pdf = await task.promise;
        if (cancelled) {
          await task.destroy();
          return;
        }
        setPageCount(pdf.numPages);

        const container = containerRef.current;
        if (!container) {
          await task.destroy();
          return;
        }
        container.innerHTML = "";

        for (let n = 1; n <= pdf.numPages; n += 1) {
          if (cancelled) break;
          const page = await pdf.getPage(n);
          const viewport = page.getViewport({ scale: 1.5 });
          const canvas = document.createElement("canvas");
          canvas.style.width = "100%";
          canvas.style.height = "auto";
          canvas.style.display = "block";
          canvas.style.background = "#fff";
          canvas.width = Math.floor(viewport.width);
          canvas.height = Math.floor(viewport.height);
          canvas.setAttribute("aria-label", `Halaman ${n} dari ${filename}`);
          container.appendChild(canvas);
          if (n > 1) {
            const divider = document.createElement("div");
            divider.style.height = "8px";
            container.appendChild(divider);
          }
          await page.render({ canvas, canvasContext: canvas.getContext("2d")!, viewport }).promise;
          page.cleanup();
        }

        await task.destroy();
        if (!cancelled) setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [fileUrl, filename]);

  if (status === "error") {
    return (
      <p className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-6 text-[13px] text-muted-foreground">
        <FileWarning className="size-4 shrink-0" aria-hidden />
        Pratinjau visual gagal dirender. Teks hasil ekstraksi tetap bisa dibaca di tab Chunk hasil ingestion.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {status === "loading" ? (
        <div className="flex flex-col gap-3 rounded-lg bg-card p-5 ring-1 ring-border" aria-hidden>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-40 rounded bg-muted" />
          ))}
        </div>
      ) : null}
      {pageCount > 0 && status === "ready" ? (
        <p className="text-[12px] text-muted-foreground">{pageCount} halaman, di-render langsung di halaman ini.</p>
      ) : null}
      <div
        ref={containerRef}
        className="flex max-h-[70vh] flex-col overflow-y-auto rounded-lg bg-muted/40 p-2 ring-1 ring-border"
      />
    </div>
  );
}
