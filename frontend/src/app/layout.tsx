import type { Metadata } from "next";
import Link from "next/link";
import Providers from "@/app/providers";
import { SocialLinks } from "@/components/social-links";
import "./globals.css";

export const metadata: Metadata = {
  title: "Steam 2026 Indie Intelligence",
  description:
    "Every Steam indie game released during 2026 — discovered, classified and analysed. " +
    "Business metrics are always marked Confirmed, Estimated or Unknown.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <Providers>
          <header className="border-b border-hairline bg-surface">
            <div className="flex w-full items-center gap-4 px-6 py-4">
              <Link href="/" className="text-lg font-semibold tracking-tight">
                Steam 2026 <span className="text-accent">Indie Intelligence</span>
              </Link>
              <Link
                href="/community"
                className="text-sm text-ink2 transition-colors hover:text-ink"
              >
                Community
              </Link>
              <span className="ml-auto text-xs text-muted">
                Wishlist &amp; revenue are never exposed by Steam — values are
                Confirmed / Estimated / Unknown, with sources.
              </span>
              <SocialLinks />
            </div>
          </header>
          <main className="w-full px-6 py-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
