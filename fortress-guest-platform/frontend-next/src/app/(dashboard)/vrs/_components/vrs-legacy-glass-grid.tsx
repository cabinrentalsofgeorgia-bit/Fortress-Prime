type VrsLegacyGlassGridProps = {
  moduleHealth?: Record<string, unknown>;
  moduleMaturityByPath?: Record<string, unknown>;
};

export function VrsLegacyGlassGrid(_props: VrsLegacyGlassGridProps) {
  return <div className="p-4 text-sm text-muted-foreground">Legacy VRS grid unavailable in this branch snapshot.</div>;
}
