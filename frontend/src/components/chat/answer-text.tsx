"use client";

import { Fragment } from "react";

/**
 * Renderer jawaban yang sangat sengaja: hanyablockquote, bullet, dan paragraf.
 *
 * Jawaban RAG lebih sering berisi kutipan chunk dan daftar poin, dan teksnya
 * datang dari dokumen milik pengguna. Render ourselves berarti tidak ada
 * HTML mentah dari server yang masuk ke DOM, dan tidak perlu menarik pustaka
 * markdown untuk lima baris format.
 */
export function AnswerText({ text }: { text: string }) {
  const blocks = text.split("\n\n");
  const flowing = text.length > 0 && !text.endsWith("\n") && !text.endsWith(" ");

  return (
    <span className={flowing ? "stream-caret" : undefined}>
      {blocks.map((block, blockIndex) => {
        const lines = block.split("\n");

        if (lines.every((line) => line.startsWith("> "))) {
          return (
            <blockquote
              key={blockIndex}
              className="my-3 rounded-md border-l-2 border-brand bg-brand-wash px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap"
            >
              {lines.map((line) => line.slice(2)).join("\n")}
            </blockquote>
          );
        }

        if (lines.every((line) => line.startsWith("- "))) {
          return (
            <ul key={blockIndex} className="my-2 flex flex-col gap-1.5 pl-1">
              {lines.map((line, lineIndex) => (
                <li key={lineIndex} className="flex gap-2 text-[13px] leading-relaxed">
                  <span className="mt-2 size-1 shrink-0 rounded-full bg-brand" aria-hidden />
                  <span>{line.slice(2)}</span>
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
                {line}
              </Fragment>
            ))}
          </Fragment>
        );
      })}
    </span>
  );
}
