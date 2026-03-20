import Link from "next/link";

export default function StorefrontLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b bg-card/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="font-semibold tracking-tight">
            Cabin Rentals of Georgia
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <Link
              href="/book"
              className="rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              Book Now
            </Link>
          </nav>
        </div>
      </header>
      {children}
      <footer className="border-t bg-card/60">
        <div className="mx-auto max-w-6xl px-6 py-6 text-sm text-muted-foreground">
          Secure direct booking and guest access for Cabin Rentals of Georgia.
        </div>
      </footer>
    </div>
  );
}
