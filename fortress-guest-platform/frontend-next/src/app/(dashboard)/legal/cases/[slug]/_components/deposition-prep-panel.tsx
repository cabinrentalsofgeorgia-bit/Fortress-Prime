type DepositionPrepPanelProps = {
  caseSlug: string;
};

export function DepositionPrepPanel({ caseSlug }: DepositionPrepPanelProps) {
  return <div className="rounded border border-border p-3 text-xs text-muted-foreground">Deposition prep unavailable for case {caseSlug} in this branch snapshot.</div>;
}
