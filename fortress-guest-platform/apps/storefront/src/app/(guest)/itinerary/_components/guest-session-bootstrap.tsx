"use client";

import { useEffect, useRef } from "react";

interface GuestSessionBootstrapProps {
  token: string;
}

export function GuestSessionBootstrap({
  token,
}: GuestSessionBootstrapProps) {
  const handledRef = useRef(false);

  useEffect(() => {
    if (handledRef.current) {
      return;
    }
    handledRef.current = true;

    void (async () => {
      await fetch("/api/guest/session", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({ token }),
      }).catch(() => undefined);

      if (typeof window === "undefined") {
        return;
      }

      const nextUrl = new URL(window.location.href);
      nextUrl.searchParams.delete("token");
      const replacement =
        nextUrl.searchParams.size > 0
          ? `${nextUrl.pathname}?${nextUrl.searchParams.toString()}`
          : nextUrl.pathname;
      window.history.replaceState({}, "", replacement);
    })();
  }, [token]);

  return null;
}
