"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { STOREFRONT_SESSION_STORAGE_KEY } from "@/lib/storefront-session";

const CONSENT_KEY = "fgp_marketing_consent";
const PAGE_SENT_KEY = "fgp_intent_page_view_sent";
const POLL_MS = 45_000;

function readSessionId(): string {
  if (typeof window === "undefined") return "";
  try {
    let id = window.sessionStorage.getItem(STOREFRONT_SESSION_STORAGE_KEY);
    if (!id) {
      id = crypto.randomUUID();
      window.sessionStorage.setItem(STOREFRONT_SESSION_STORAGE_KEY, id);
    }
    return id;
  } catch {
    return "";
  }
}

function readConsent(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(CONSENT_KEY) === "true";
}

async function postEvent(payload: Record<string, unknown>) {
  await fetch("/api/storefront/intent/event", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    credentials: "same-origin",
  });
}

type NudgeResponse = {
  eligible?: boolean;
  variant?: string | null;
  score_window?: number;
  consent_active?: boolean;
};

/**
 * Consent-gated intent telemetry + Sovereign Nudge modal.
 * Does not capture email/phone keystrokes — see docs/architecture/sovereign-intent-engine-boundaries.md
 */
export function SovereignNudge() {
  const pathname = usePathname() || "";
  const cabinSlug = useMemo(() => {
    const m = pathname.match(/^\/cabins\/([^/]+)\/?$/i);
    return m ? m[1].toLowerCase() : undefined;
  }, [pathname]);

  const [sessionId, setSessionId] = useState("");
  const [consent, setConsent] = useState(false);
  const [bannerOpen, setBannerOpen] = useState(false);
  const [nudgeOpen, setNudgeOpen] = useState(false);
  const shownRef = useRef(false);

  useEffect(() => {
    setSessionId(readSessionId());
    setConsent(readConsent());
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    if (!consent) {
      setBannerOpen(true);
      return;
    }
    setBannerOpen(false);
  }, [sessionId, consent]);

  const sendCoarsePageSignals = useCallback(async () => {
    if (!sessionId || !consent) return;
    try {
      if (typeof window !== "undefined" && !window.sessionStorage.getItem(PAGE_SENT_KEY)) {
        await postEvent({
          session_id: sessionId,
          event_type: "page_view",
          consent_marketing: true,
          meta: { path: pathname.slice(0, 200) },
        });
        window.sessionStorage.setItem(PAGE_SENT_KEY, "1");
      }
      if (cabinSlug) {
        const pvKey = `fgp_intent_property_${cabinSlug}`;
        if (!window.sessionStorage.getItem(pvKey)) {
          await postEvent({
            session_id: sessionId,
            event_type: "property_view",
            consent_marketing: true,
            property_slug: cabinSlug,
            meta: {},
          });
          window.sessionStorage.setItem(pvKey, "1");
        }
      }
    } catch {
      /* non-blocking */
    }
  }, [sessionId, consent, pathname, cabinSlug]);

  useEffect(() => {
    void sendCoarsePageSignals();
  }, [sendCoarsePageSignals]);

  useEffect(() => {
    if (!sessionId || !consent) return;

    const poll = async () => {
      try {
        const res = await fetch(
          `/api/storefront/intent/nudge?session_id=${encodeURIComponent(sessionId)}`,
          { credentials: "same-origin", cache: "no-store" },
        );
        if (!res.ok) return;
        const data = (await res.json()) as NudgeResponse;
        if (data.eligible && !shownRef.current) {
          shownRef.current = true;
          setNudgeOpen(true);
        }
      } catch {
        /* ignore */
      }
    };

    void poll();
    const id = window.setInterval(poll, POLL_MS);
    return () => window.clearInterval(id);
  }, [sessionId, consent]);

  const acceptConsent = async () => {
    if (!sessionId) return;
    try {
      await postEvent({
        session_id: sessionId,
        event_type: "consent_granted",
        consent_marketing: true,
        meta: {},
      });
      window.localStorage.setItem(CONSENT_KEY, "true");
      setConsent(true);
      setBannerOpen(false);
    } catch {
      setBannerOpen(false);
    }
  };

  const declineConsent = async () => {
    if (!sessionId) return;
    try {
      await postEvent({
        session_id: sessionId,
        event_type: "consent_revoked",
        consent_marketing: false,
        meta: {},
      });
    } catch {
      /* ignore */
    }
    window.localStorage.removeItem(CONSENT_KEY);
    setConsent(false);
    setBannerOpen(false);
  };

  const dismissNudge = async () => {
    if (sessionId) {
      try {
        await postEvent({
          session_id: sessionId,
          event_type: "nudge_dismissed",
          consent_marketing: true,
          meta: {},
        });
      } catch {
        /* ignore */
      }
    }
    setNudgeOpen(false);
  };

  if (!sessionId) return null;

  return (
    <>
      {bannerOpen && !consent ? (
        <div className="fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-card/95 p-4 shadow-lg backdrop-blur sm:p-3">
          <div className="mx-auto flex max-w-3xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              First-party analytics &amp; trip planning help. We do <strong>not</strong> capture email or
              phone until you submit a form.{" "}
              <Link href="/privacy" className="underline underline-offset-2">
                Privacy
              </Link>
            </p>
            <div className="flex shrink-0 gap-2">
              <Button variant="outline" size="sm" onClick={() => void declineConsent()}>
                Decline
              </Button>
              <Button size="sm" onClick={() => void acceptConsent()}>
                Accept
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <Dialog open={nudgeOpen} onOpenChange={(open) => !open && void dismissNudge()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Planning a stay?</DialogTitle>
            <DialogDescription>
              Our concierge can answer questions about this cabin or hold dates while you decide — no
              pressure.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:justify-between">
            <Button variant="ghost" size="sm" onClick={() => void dismissNudge()}>
              Not now
            </Button>
            <Button asChild size="sm">
              <Link href="/book">Continue to booking</Link>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
