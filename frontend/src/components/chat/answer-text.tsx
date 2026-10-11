"use client";

import { Fragment } from "react";

/**
 * Renderer jawaban yang sengaja sederhana: paragraf, daftar, dan blockquote.
 *
 * Jawaban RAG sering berisi kutipan chunk dan daftar poin, dan teksnya berasal
 * dari dokumen milik pengguna. Merender sendiri berarti tidak ada HTML mentah
 * dari server yang masuk ke DOM, dan tidak perlu menarik pustaka markdown
 * hanya untuk lima baris format.
 *
 * Satu hal yang tetap harus dilakukan di sini: **membuang penanda markup
 * mentah** yang ikut tersalin model dari chunk (`**tebal**`, `# judul`,
 * garis `====`). Jawaban tampil sambil mengalir, jadi pembersihan di backend
 * saja datang terlambat, pengguna sudah melihat tanda bintangnya.
 */
function stripInlineMarkup(value: string): string {
  return value
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1");
}

export function AnswerText({ text }: { text: string }) {
  const cleaned = text
    .split("\n")
    .filter((line) => !/^[=\-]{3,}\s*$/.test(line))
    .map((line) => line.replace(/^#{1,6}\s+/, ""))
    .join("\n");

  const blocks = cleaned.split("\n\n");
  const flowing = cleaned.length > 0 && !cleaned.endsWith("\n") && !cleaned.endsWith(" ");

  return (
    <span className={flowing ? "stream-caret" : undefined}>
      {blocks.map((block, blockIndex) => {
        const lines = block.split("\n");

        if (lines.length > 0 && lines.every((line) => line.startsWith("> "))) {
          return (
            <blockquote
              key={blockIndex}
              className="my-3 rounded-md border-l-2 border-brand bg-brand-wash px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap"
            >
              {stripInlineMarkup(lines.map((line) => line.slice(2)).join("\n"))}
            </blockquote>
          );
        }

        if (lines.length > 0 && lines.every((line) => line.startsWith("- "))) {
          return (
            <ul key={blockIndex} className="my-2 flex flex-col gap-1.5 pl-1">
              {lines.map((line, lineIndex) => (
                <li key={lineIndex} className="flex gap-2 text-[13px] leading-relaxed">
                  <span className="mt-2 size-1 shrink-0 rounded-full bg-brand" aria-hidden />
                  <span>{stripInlineMarkup(line.slice(2))}</span>
                </li>
              ))}
            </ul>
          );
        }

        return (
          <Fragment key={blockIndex}>
            {blockIndex > 0 ? <br /> : null}
            {lines.map((line, lineIndex) => (
              <Fragment key={lineIndex}>
                {lineIndex > 0 ? <br /> : null}
                {stripInlineMarkup(line)}
              </Fragment>
            ))}
          </Fragment>
        );
      })}
    </span>
  );
}