import type { StreamlineSyncHealth } from "@/lib/types";

function statusClass(status?: StreamlineSyncHealth["status"]): string {
  if (status === "online") {
    return "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  }
  if (status === "degraded") {
    return "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300";
  }
  return "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400";
}

function titleFor(health?: StreamlineSyncHealth): string {
  if (!health) return "Streamline sync health unavailable";
  if (!health.worker_active) return "Streamline sync worker is offline";
  if (health.primary_circuit_method) {
    const methods = health.recent_circuit_methods?.map((item) => `${item.method}: ${item.count}`).join(", ");
    return `Streamline fallback by method: ${methods || health.primary_circuit_method}`;
  }
  if (health.circuit_open_recent) {
    return health.latest_circuit_summary || "Recent Streamline circuit breaker fallback";
  }
  if (health.last_error_categories && Object.keys(health.last_error_categories).length > 0) {
    const categories = Object.entries(health.last_error_categories)
      .map(([name, count]) => `${name}: ${count}`)
      .join(", ");
    return `Streamline sync errors by category: ${categories}`;
  }
  if ((health.last_error_count ?? 0) > 0 || (health.last_reservation_errors ?? 0) > 0) {
    return health.last_cycle_summary || health.last_sync_summary || "Recent Streamline sync errors";
  }
  return health.last_cycle_summary || "Streamline sync worker online";
}

export function StreamlineSyncButton({ health }: { health?: StreamlineSyncHealth }) {
  const status = health?.status ?? "offline";
  const label =
    status === "online" ? "Streamline Online" : status === "degraded" ? "Streamline Degraded" : "Streamline Offline";
  const topErrorCategory = health?.last_error_categories
    ? Object.entries(health.last_error_categories).sort((a, b) => b[1] - a[1])[0]
    : undefined;
  const detail =
    health?.primary_circuit_method
      ? `${health.primary_circuit_method} fallback`
      : topErrorCategory
        ? `${topErrorCategory[0]} errors`
      : health?.last_reservations_updated != null
      ? `${health.last_reservations_updated.toLocaleString()} reservations`
      : health?.recent_circuit_events
        ? `${health.recent_circuit_events} circuit events`
        : "sync health";

  return (
    <button
      className={`px-3 py-1 rounded border text-xs ${statusClass(status)}`}
      type="button"
      title={titleFor(health)}
    >
      <span className="font-medium">{label}</span>
      <span className="ml-2 opacity-80">{detail}</span>
    </button>
  );
}
