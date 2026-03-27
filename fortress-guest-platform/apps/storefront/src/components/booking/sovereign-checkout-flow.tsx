"use client";

import { useEffect, useState, useTransition } from "react";
import {
  getDirectBookingConfig,
  getSignedSovereignQuote,
  type DirectBookingConfig,
  type SignedSovereignQuotePayload,
} from "@/app/actions/checkout";
import { getFastQuote, type QuoteActionState } from "@/app/actions/quote";

const DEBOUNCE_MS = 250;

export type SovereignCheckoutFlowState = {
  /** Backend config; null until loaded or on hard failure */
  config: DirectBookingConfig | null;
  configLoading: boolean;
  configError: string | null;
  sovereign_quote_signing_required: boolean;
  /** Live quote for display (always from ledger path) */
  quoteState: QuoteActionState | null;
  quotePending: boolean;
  quoteError: string | null;
  /** Sealed payload for POST /book when signing is required */
  signedQuote: SignedSovereignQuotePayload | null;
  signingPending: boolean;
  signingError: string | null;
  /** True when user can proceed to hold (quote OK and signed quote present if required) */
  readyForHold: boolean;
};

export type SovereignCheckoutFlowInput = {
  enabled: boolean;
  propertyId: string;
  checkIn: string;
  checkOut: string;
  guests: number;
  adults: number;
  children: number;
  pets: number;
};

/**
 * Sovereign checkout logic center: loads config, refreshes ledger quote, and acquires
 * a signed quote when `sovereign_quote_signing_required` is true.
 */
export function useSovereignCheckoutFlow(input: SovereignCheckoutFlowInput): SovereignCheckoutFlowState {
  const [config, setConfig] = useState<DirectBookingConfig | null>(null);
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);

  const [quoteState, setQuoteState] = useState<QuoteActionState | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [flowPending, startFlowTransition] = useTransition();

  const [signedQuote, setSignedQuote] = useState<SignedSovereignQuotePayload | null>(null);
  const [signingError, setSigningError] = useState<string | null>(null);

  const signingRequired = Boolean(config?.sovereign_quote_signing_required);

  useEffect(() => {
    if (!input.enabled) {
      return;
    }
    let cancelled = false;
    setConfigLoading(true);
    setConfigError(null);
    void (async () => {
      const next = await getDirectBookingConfig();
      if (cancelled) {
        return;
      }
      setConfigLoading(false);
      if (!next) {
        setConfigError("Unable to load booking configuration.");
        setConfig(null);
        return;
      }
      setConfig(next);
    })();
    return () => {
      cancelled = true;
    };
  }, [input.enabled]);

  useEffect(() => {
    if (!input.enabled || !input.propertyId || !input.checkIn || !input.checkOut) {
      return;
    }
    if (input.checkOut <= input.checkIn) {
      setQuoteState(null);
      setQuoteError("Check-out must be after check-in.");
      setSignedQuote(null);
      setSigningError(null);
      return;
    }
    if (input.guests < 1) {
      setQuoteState(null);
      setQuoteError("At least one guest is required.");
      setSignedQuote(null);
      setSigningError(null);
      return;
    }

    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      startFlowTransition(() => {
        void (async () => {
          setQuoteError(null);
          setSigningError(null);
          const nextQuote = await getFastQuote({
            propertyId: input.propertyId,
            checkIn: input.checkIn,
            checkOut: input.checkOut,
            adults: input.adults,
            children: input.children,
            pets: input.pets,
          });
          if (cancelled) {
            return;
          }
          setQuoteState(nextQuote);
          if (!nextQuote.ok) {
            setQuoteError(nextQuote.error);
            setSignedQuote(null);
            return;
          }

          const needSign = Boolean(config?.sovereign_quote_signing_required);
          if (!needSign) {
            setSignedQuote(null);
            return;
          }

          const sealed = await getSignedSovereignQuote({
            propertyId: input.propertyId,
            checkIn: input.checkIn,
            checkOut: input.checkOut,
            guests: input.guests,
            adults: input.adults,
            children: input.children,
            pets: input.pets,
          });
          if (cancelled) {
            return;
          }
          if (!sealed.ok) {
            setSignedQuote(null);
            setSigningError(sealed.error);
            return;
          }
          setSignedQuote(sealed.quote);
        })();
      });
    }, DEBOUNCE_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [
    config?.sovereign_quote_signing_required,
    input.adults,
    input.checkIn,
    input.checkOut,
    input.children,
    input.enabled,
    input.guests,
    input.pets,
    input.propertyId,
    startFlowTransition,
    config,
  ]);

  const readyForHold =
    Boolean(quoteState?.ok && quoteState.quote) &&
    (!signingRequired || Boolean(signedQuote && !signingError));

  return {
    config,
    configLoading,
    configError,
    sovereign_quote_signing_required: signingRequired,
    quoteState,
    quotePending: flowPending,
    quoteError,
    signedQuote,
    signingPending: flowPending,
    signingError,
    readyForHold,
  };
}

/**
 * Named export for blueprint alignment; the active API is {@link useSovereignCheckoutFlow}.
 */
export function SovereignCheckoutFlow(_props: { children?: never }): null {
  return null;
}
