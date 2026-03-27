"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import SignaturePad from "signature_pad";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";

interface Section {
  title: string;
  content: string;
  index: number;
}

interface AgreementData {
  agreement_id: string;
  agreement_type: string;
  status: string;
  rendered_content: string;
  sections: Section[];
  requires_signature: boolean;
  requires_initials: boolean;
  guest_name: string;
  guest_email: string;
  property_name: string;
  expires_at: string | null;
}

type SigMode = "draw" | "type";

export default function SignPage() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<AgreementData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sigMode, setSigMode] = useState<SigMode>("draw");
  const [typedName, setTypedName] = useState("");
  const [consent, setConsent] = useState(false);
  const [currentSection, setCurrentSection] = useState(0);
  const [initialed, setInitialed] = useState<Set<number>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const sigCanvasRef = useRef<HTMLCanvasElement>(null);
  const sigPadRef = useRef<SignaturePad | null>(null);
  const initialCanvasRef = useRef<HTMLCanvasElement>(null);
  const initialPadRef = useRef<SignaturePad | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!token) return;
    fetch(`${API}/api/agreements/public/${token}`)
      .then(async (r) => {
        if (!r.ok) {
          const d = await r.json().catch(() => null);
          throw new Error(d?.detail || "Failed to load agreement");
        }
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => {
    if (!sigCanvasRef.current) return;
    const pad = new SignaturePad(sigCanvasRef.current, {
      backgroundColor: "rgb(255,255,255)",
      penColor: "rgb(15,23,42)",
    });
    sigPadRef.current = pad;
    return () => pad.off();
  }, [data, sigMode]);

  useEffect(() => {
    if (!initialCanvasRef.current || !data?.requires_initials) return;
    const pad = new SignaturePad(initialCanvasRef.current, {
      backgroundColor: "rgb(255,255,255)",
      penColor: "rgb(15,23,42)",
      minWidth: 1,
      maxWidth: 2,
    });
    initialPadRef.current = pad;
    return () => pad.off();
  }, [data, currentSection]);

  const handleInitial = useCallback(() => {
    if (!initialPadRef.current || initialPadRef.current.isEmpty()) return;
    setInitialed((prev) => new Set(prev).add(currentSection));
    initialPadRef.current.clear();
    if (data && currentSection < data.sections.length - 1) {
      setCurrentSection((s) => s + 1);
    }
  }, [currentSection, data]);

  const allInitialed =
    !data?.requires_initials ||
    (data?.sections.length ?? 0) <= (initialed.size ?? 0);

  const hasSignature =
    sigMode === "type" ? typedName.trim().length >= 2 : !sigPadRef.current?.isEmpty();

  const canSubmit = consent && hasSignature && allInitialed && !submitting;

  async function handleSubmit() {
    if (!data || !token) return;
    setSubmitting(true);

    let signatureData = "";
    if (sigMode === "draw" && sigPadRef.current) {
      signatureData = sigPadRef.current.toDataURL("image/png");
    } else {
      signatureData = typedName;
    }

    try {
      const resp = await fetch(`${API}/api/agreements/public/${token}/sign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          signer_name: typedName || data.guest_name,
          signer_email: data.guest_email,
          signature_type: sigMode === "draw" ? "drawn" : "typed",
          signature_data: signatureData,
          initials_data: null,
          initials_pages: Array.from(initialed),
          consent_recorded: consent,
        }),
      });

      if (!resp.ok) {
        const d = await resp.json().catch(() => null);
        throw new Error(d?.detail || "Signing failed");
      }

      setSuccess(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Signing failed");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto" />
          <p className="mt-4 text-slate-500">Loading agreement...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="max-w-md text-center p-8 bg-white rounded-xl shadow-lg">
          <div className="w-14 h-14 mx-auto mb-4 bg-red-100 rounded-full flex items-center justify-center">
            <svg className="w-7 h-7 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M12 3a9 9 0 100 18 9 9 0 000-18z" />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-slate-900">Unable to Load Agreement</h2>
          <p className="mt-2 text-sm text-slate-500">{error}</p>
        </div>
      </div>
    );
  }

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="max-w-md text-center p-8 bg-white rounded-xl shadow-lg">
          <div className="w-16 h-16 mx-auto mb-4 bg-green-100 rounded-full flex items-center justify-center">
            <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-slate-900">Agreement Signed</h2>
          <p className="mt-2 text-slate-500">
            Thank you, {data?.guest_name}! Your rental agreement for{" "}
            <strong>{data?.property_name}</strong> has been signed successfully.
          </p>
          <p className="mt-3 text-sm text-slate-400">
            A signed copy will be emailed to {data?.guest_email}.
          </p>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const progress = data.requires_initials
    ? Math.round((initialed.size / Math.max(data.sections.length, 1)) * 100)
    : 100;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b sticky top-0 z-20">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-slate-900">
              Cabin Rentals of Georgia
            </h1>
            <p className="text-xs text-slate-500">
              {data.agreement_type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
              {data.property_name ? ` — ${data.property_name}` : ""}
            </p>
          </div>
          <div className="text-right text-xs text-slate-400">
            {data.expires_at && (
              <p>Expires {new Date(data.expires_at).toLocaleDateString()}</p>
            )}
          </div>
        </div>
        {data.requires_initials && (
          <div className="h-1 bg-slate-100">
            <div
              className="h-1 bg-blue-600 transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        )}
      </header>

      <main className="max-w-4xl mx-auto px-4 py-6 pb-32">
        {/* Document */}
        <div
          ref={scrollRef}
          className="bg-white rounded-xl shadow-sm border p-6 md:p-10 prose prose-slate max-w-none"
        >
          {data.sections.map((section, idx) => (
            <div key={idx} className="mb-8">
              {section.title !== "Introduction" && (
                <h2 className="text-lg font-semibold text-slate-900 border-b pb-2 mb-3">
                  {section.title}
                </h2>
              )}
              <div
                className="text-sm leading-relaxed text-slate-700 whitespace-pre-wrap"
                dangerouslySetInnerHTML={{ __html: section.content }}
              />

              {data.requires_initials && (
                <div className="mt-4 flex items-center gap-3">
                  {initialed.has(idx) ? (
                    <span className="inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 px-3 py-1 rounded-full">
                      <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                      Initialed
                    </span>
                  ) : (
                    <button
                      onClick={() => setCurrentSection(idx)}
                      className="text-xs text-blue-600 bg-blue-50 hover:bg-blue-100 px-3 py-1 rounded-full transition-colors"
                    >
                      Initial here
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Initials pad (if needed) */}
        {data.requires_initials && !allInitialed && (
          <div className="mt-6 bg-white rounded-xl shadow-sm border p-6">
            <h3 className="text-sm font-semibold text-slate-900 mb-1">
              Initial Section {currentSection + 1}: {data.sections[currentSection]?.title}
            </h3>
            <p className="text-xs text-slate-500 mb-3">
              Draw your initials below to acknowledge this section
            </p>
            <canvas
              ref={initialCanvasRef}
              width={300}
              height={80}
              className="border rounded-lg bg-white w-full max-w-xs"
            />
            <div className="mt-2 flex gap-2">
              <button
                onClick={handleInitial}
                className="px-4 py-1.5 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-700"
              >
                Confirm Initial
              </button>
              <button
                onClick={() => initialPadRef.current?.clear()}
                className="px-4 py-1.5 bg-slate-100 text-slate-600 text-xs rounded-lg hover:bg-slate-200"
              >
                Clear
              </button>
            </div>
          </div>
        )}

        {/* Signature Block */}
        <div className="mt-6 bg-white rounded-xl shadow-sm border p-6">
          <h3 className="text-sm font-semibold text-slate-900 mb-4">
            Sign Agreement
          </h3>

          {/* Mode toggle */}
          <div className="flex gap-1 bg-slate-100 rounded-lg p-1 w-fit mb-4">
            <button
              onClick={() => setSigMode("draw")}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                sigMode === "draw"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              Draw
            </button>
            <button
              onClick={() => setSigMode("type")}
              className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
                sigMode === "type"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              Type
            </button>
          </div>

          {sigMode === "draw" ? (
            <div>
              <canvas
                ref={sigCanvasRef}
                width={500}
                height={150}
                className="border-2 border-dashed border-slate-300 rounded-lg bg-white w-full"
                style={{ touchAction: "none" }}
              />
              <div className="flex justify-between items-center mt-2">
                <p className="text-xs text-slate-400">
                  Draw your signature above
                </p>
                <button
                  onClick={() => sigPadRef.current?.clear()}
                  className="text-xs text-slate-500 hover:text-slate-700"
                >
                  Clear
                </button>
              </div>
            </div>
          ) : (
            <div>
              <input
                type="text"
                value={typedName}
                onChange={(e) => setTypedName(e.target.value)}
                placeholder="Type your full legal name"
                className="w-full px-4 py-3 border rounded-lg text-lg"
              />
              {typedName && (
                <div className="mt-3 p-4 bg-slate-50 rounded-lg border">
                  <p
                    className="text-2xl text-slate-900"
                    style={{ fontFamily: "'Georgia', 'Times New Roman', serif", fontStyle: "italic" }}
                  >
                    {typedName}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Consent */}
          <label className="flex items-start gap-3 mt-6 cursor-pointer">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-xs text-slate-600 leading-relaxed">
              I agree that my electronic signature is the legal equivalent of my
              manual/handwritten signature and that this agreement is legally
              binding. I consent to conducting this transaction electronically
              pursuant to the E-SIGN Act and UETA.
            </span>
          </label>

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className={`mt-6 w-full py-3 rounded-lg text-sm font-semibold transition-colors ${
              canSubmit
                ? "bg-blue-600 text-white hover:bg-blue-700"
                : "bg-slate-200 text-slate-400 cursor-not-allowed"
            }`}
          >
            {submitting ? (
              <span className="flex items-center justify-center gap-2">
                <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                Signing...
              </span>
            ) : (
              "Sign Agreement"
            )}
          </button>
        </div>
      </main>
    </div>
  );
}
