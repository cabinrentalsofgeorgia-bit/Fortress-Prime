"use client";

import { useMemo, useState } from "react";

interface StreamlineCheckoutProps {
  propertyId: string;
  streamlineBaseUrl?: string;
}

export function StreamlineCheckoutFrame({
  propertyId,
  streamlineBaseUrl = "https://secure.streamlinevrs.com/components/booking",
}: StreamlineCheckoutProps) {
  const [isLoading, setIsLoading] = useState(true);

  const iframeSrc = useMemo(() => {
    const params = new URLSearchParams({
      property_id: propertyId,
      style: "modern",
    });
    return `${streamlineBaseUrl}?${params.toString()}`;
  }, [propertyId, streamlineBaseUrl]);

  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      {isLoading ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-slate-900" />
            <span className="text-sm font-medium text-slate-600">Loading secure checkout...</span>
          </div>
        </div>
      ) : null}
      <iframe
        src={iframeSrc}
        className="h-[700px] w-full border-0"
        title="Secure Property Checkout"
        loading="lazy"
        onLoad={() => setIsLoading(false)}
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"
      />
    </div>
  );
}
