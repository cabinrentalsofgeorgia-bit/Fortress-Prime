import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";
import { getStorefrontBaseUrl } from "@/lib/server/storefront-base-url";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

import type { Viewport } from "next";

const baseUrl = getStorefrontBaseUrl();

export const metadata: Metadata = {
  title: "Fortress Guest Platform",
  description: "Enterprise vacation rental management",
  metadataBase: new URL(baseUrl),
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Fortress",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className="dark bg-slate-950"
      style={{ colorScheme: "dark", backgroundColor: "#020617", color: "#f8fafc" }}
      suppressHydrationWarning
    >
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                var retried = false;
                window.addEventListener('error', function(e) {
                  if (retried) return;
                  var msg = (e.message || '').toLowerCase();
                  var src = (e.filename || '').toLowerCase();
                  if (
                    msg.indexOf('loading chunk') !== -1 ||
                    msg.indexOf('loading css chunk') !== -1 ||
                    msg.indexOf('failed to fetch') !== -1 ||
                    (src.indexOf('/_next/') !== -1 && msg.indexOf('syntaxerror') !== -1)
                  ) {
                    retried = true;
                    window.location.reload();
                  }
                });
              })();
            `,
          }}
        />
      </head>
      <body
        className={`${inter.variable} bg-slate-950 font-sans antialiased text-slate-50`}
        style={{ colorScheme: "dark", backgroundColor: "#020617", color: "#f8fafc" }}
        suppressHydrationWarning
      >
        <div
          className="min-h-screen bg-slate-950 text-slate-50"
          style={{ backgroundColor: "#020617", color: "#f8fafc" }}
        >
          <Providers>{children}</Providers>
        </div>
      </body>
    </html>
  );
}
