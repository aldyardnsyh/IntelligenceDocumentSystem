"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renderer jawaban berbasis markdown sungguhan.
 *
 * Jawaban backend kini sengaja berformat markdown ringan (jawaban inti di
 * atas, poin bukti dengan rujukan [SUMBER n], tebal untuk angka kunci), jadi
 * renderer regex buatan sendiri diganti react-markdown. ReactMarkdown tanpa
 * rehype-raw TIDAK merender HTML mentah, jadi isi dokumen milik pengguna
 * tidak pernah bisa menyuntik markup ke DOM.
 *
 * Saat streaming, markdown bisa sementara tidak lengkap (misal `**` belum
 * ditutup); react-markdown merender itu sebagai teks biasa, jadi tidak ada
 * artefak yang perlu dibersihkan manual.
 */
const components: Components = {
  p: ({ children }) => (
    <p className="my-2 text-[13px] leading-relaxed first:mt-0 last:mb-0">
      {children}
    </p>
  ),
  ul: ({ children }) => (
    // Titik brand per item lewat pseudo-element, supaya <ol> bernomor tidak
    // ikut mendapat titik.
    <ul
      className="my-2 flex flex-col gap-1.5 [&>li]:relative [&>li]:pl-4 [&>li]:text-[13px] [&>li]:leading-relaxed
        [&>li]:before:absolute [&>li]:before:left-0 [&>li]:before:top-2 [&>li]:before:size-1
        [&>li]:before:rounded-full [&>li]:before:bg-brand [&>li]:before:content-['']"
    >
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="my-2 flex flex-col gap-1.5 pl-5 [list-style:decimal] [&>li]:text-[13px] [&>li]:leading-relaxed marker:text-muted-foreground">
      {children}
    </ol>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  em: ({ children }) => <em className="text-foreground/90">{children}</em>,
  h1: ({ children }) => (
    <h1 className="mt-3 mb-1 text-[13px] font-semibold tracking-tight first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-3 mb-1 text-[13px] font-semibold tracking-tight first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-3 mb-1 text-[13px] font-semibold tracking-tight first:mt-0">
      {children}
    </h3>
  ),
  h4: ({ children }) => (
    <h4 className="mt-3 mb-1 text-[13px] font-semibold tracking-tight first:mt-0">
      {children}
    </h4>
  ),
  h5: ({ children }) => (
    <h5 className="mt-3 mb-1 text-[13px] font-semibold tracking-tight first:mt-0">
      {children}
    </h5>
  ),
  h6: ({ children }) => (
    <h6 className="mt-3 mb-1 text-[13px] font-semibold tracking-tight first:mt-0">
      {children}
    </h6>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3 rounded-md border-l-2 border-brand bg-brand-wash px-3 py-2 text-[13px] leading-relaxed [&>p]:my-0">
      {children}
    </blockquote>
  ),
  code: ({ children }) => (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[12px]">
      {children}
    </code>
  ),
  a: ({ children, href }) => (
    <a
      href={href}
      className="text-brand underline underline-offset-2"
      rel="noreferrer noopener"
    >
      {children}
    </a>
  ),
};

export function AnswerText({ text }: { text: string }) {
  // Kursor "mengalir" hanya tampil saat teks belum berakhir di spasi/baris
  // baru, sama perilakunya dengan renderer lama.
  const flowing = text.length > 0 && !text.endsWith("\n") && !text.endsWith(" ");

  return (
    <span className={flowing ? "stream-caret" : undefined}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </span>
  );
}
