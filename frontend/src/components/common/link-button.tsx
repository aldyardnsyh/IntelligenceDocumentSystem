import Link from "next/link";
import { Button, type buttonVariants } from "@/components/ui/button";
import type { VariantProps } from "class-variance-authority";

type LinkButtonProps = VariantProps<typeof buttonVariants> & {
  href: string;
  children: React.ReactNode;
  className?: string;
  title?: string;
  target?: "_self" | "_blank";
  rel?: string;
  "aria-label"?: string;
};

/**
 * Tombol yang sebenarnya sebuah tautan.
 *
 * `nativeButton={false}` wajib ada di sini: Base UI mengasumsikan elemen
 * hasil `render` adalah `<button>`, dan akan memperingatkan saat yang
 * dirender adalah `<a>`. Selain menghilangkan peringatan, ini juga membetulkan
 * semantik: navigasi lewat tautan, bukan tombol, supaya klik tengah dan
 * "buka di tab baru" tetap bekerja.
 */
export function LinkButton({ href, children, target, rel, ...props }: LinkButtonProps) {
  return (
    <Button
      nativeButton={false}
      render={<Link href={href} target={target} rel={rel} />}
      {...props}
    >
      {children}
    </Button>
  );
}
