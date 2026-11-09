import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "echr-lookup",
  description: "Ask questions of UK–ECHR case law. Every claim cites the exact paragraph.",
};

const NAV = [
  { href: "/ask", label: "Ask" },
  { href: "/lab", label: "Lab" },
  { href: "/stats", label: "Stats" },
];

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">
        <header className="border-b border-stone-200 bg-white" data-testid="site-nav">
          <nav className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3 text-sm">
            <Link href="/" className="font-semibold tracking-tight">
              echr-lookup
            </Link>
            {NAV.map((item) => (
              <Link key={item.href} href={item.href} className="text-stone-600 hover:text-stone-900">
                {item.label}
              </Link>
            ))}
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
