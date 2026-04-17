import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

import type { Viewport } from "next";

const appUrl = (
  process.env.NEXT_PUBLIC_COMMAND_CENTER_URL ||
  process.env.NEXT_PUBLIC_APP_URL ||
  "https://crog-ai.com"
).replace(/\/$/, "");

export const metadata: Metadata = {
  title: "Fortress Prime",
  description: "Internal command center for Fortress Prime operations",
  metadataBase: new URL(appUrl),
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Fortress Prime",
  },
  robots: {
    index: false,
    follow: false,
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
