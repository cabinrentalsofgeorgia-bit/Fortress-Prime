"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTriggerExtraction } from "@/lib/legal-hooks";
import type { LegalCase, ExtractedEntities, ExtractedParty, ExtractedAmount } from "@/lib/legal-types";
import { Brain, Loader2, AlertCircle, User, DollarSign, FileText } from "lucide-react";

function RiskMeter({ score }: { score: number }) {
  const segments = [1, 2, 3, 4, 5];
  return (
    <div className="flex gap-1">
      {segments.map((s) => (
        <div
          key={s}
          className={`h-2 w-6 rounded-full ${
            s <= score
              ? s <= 2
                ? "bg-green-500"
                : s <= 3
                  ? "bg-amber-500"
                  : "bg-red-500"
              : "bg-muted"
          }`}
        />
      ))}
    </div>
  );
}

export function ExtractionPanel({ legalCase, slug }: { legalCase: LegalCase; slug: string }) {
  const trigger = useTriggerExtraction(slug);
  const status = legalCase.extraction_status;
  const entities = legalCase.extracted_entities as ExtractedEntities | null | Record<string, never>;
  const isExtracting = status === "queued" || status === "processing";
  const hasEntities =
    entities && "summary" in entities && !!entities.summary;

  return (
    <div className="p-4 border-b space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Brain className="h-4 w-4 text-primary" />
          AI Extraction Engine
        </h3>
        <Button
          size="sm"
          variant="outline"
          disabled={isExtracting || trigger.isPending}
          onClick={() =>
            trigger.mutate({ target: "case", text: legalCase.notes ?? "" })
          }
        >
          {isExtracting ? (
            <><Loader2 className="h-3 w-3 animate-spin mr-1" /> Extracting...</>
          ) : hasEntities ? (
            "Re-Extract"
          ) : (
            "Run Extraction"
          )}
        </Button>
      </div>

      {isExtracting && (
        <Card>
          <CardContent className="p-4 flex items-center gap-3">
            <Loader2 className="h-5 w-5 animate-spin text-blue-400" />
            <span className="text-sm text-muted-foreground">
              AI extraction in progress. Results will appear automatically.
            </span>
          </CardContent>
        </Card>
      )}

      {status === "failed" && (
        <Card className="border-red-500/20">
          <CardContent className="p-4 flex items-center gap-3">
            <AlertCircle className="h-5 w-5 text-red-500" />
            <span className="text-sm text-red-400">
              Extraction failed. Try again or check backend logs.
            </span>
          </CardContent>
        </Card>
      )}

      {hasEntities && entities && "summary" in entities && (
        <div className="space-y-3">
          <Card>
            <CardContent className="p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">AI Summary</span>
                <RiskMeter score={entities.risk_score} />
              </div>
              <p className="text-xs leading-relaxed">{entities.summary}</p>
              {entities.risk_justification && (
                <p className="text-[11px] text-muted-foreground italic">{entities.risk_justification}</p>
              )}
            </CardContent>
          </Card>

          {entities.parties?.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground mb-1.5 flex items-center gap-1">
                <User className="h-3 w-3" /> Parties
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {entities.parties.map((p: ExtractedParty, i: number) => (
                  <Badge key={i} variant="outline" className="text-[10px]">
                    {p.role}: {p.name}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {entities.amounts?.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground mb-1.5 flex items-center gap-1">
                <DollarSign className="h-3 w-3" /> Financial Exposure
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {entities.amounts.map((a: ExtractedAmount, i: number) => (
                  <Badge key={i} variant="outline" className="text-[10px] bg-amber-500/10 border-amber-500/30">
                    {a.currency} {a.value.toLocaleString()} — {a.description}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {entities.key_claims?.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground mb-1.5 flex items-center gap-1">
                <FileText className="h-3 w-3" /> Claims
              </h4>
              <ul className="space-y-1">
                {entities.key_claims.map((claim: string, i: number) => (
                  <li key={i} className="text-xs text-muted-foreground pl-2 border-l-2 border-primary/30">
                    {claim}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex gap-2 text-[10px] text-muted-foreground">
            {entities.document_type && <span>Type: {entities.document_type}</span>}
            {entities.jurisdiction && <span>&middot; {entities.jurisdiction}</span>}
            {entities.case_number && <span>&middot; Case: {entities.case_number}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
