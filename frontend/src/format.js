export function comparison(stats, mode) {
  const { safe, direct } = stats;
  const extra = Math.round(safe.duration_min - direct.duration_min);
  const time =
    extra > 0 ? `${duration(extra)} longer` : extra < 0 ? `${duration(-extra)} shorter` : "Same time";

  if (mode === "summer") {
    if (safe.shaded_pct === direct.shaded_pct && extra === 0) {
      return "The direct route is already the shadiest";
    }
    return `${time} · ${safe.shaded_pct}% shaded vs ${direct.shaded_pct}%`;
  }
  const avoided =
    direct.risk_streets + direct.reported_streets - safe.risk_streets - safe.reported_streets;
  if (avoided <= 0) {
    return direct.risk_streets === 0
      ? "No flood-risk streets on the way right now"
      : `${time} · no safer route available`;
  }
  return `${time} · avoids ${avoided} flood-risk street${avoided === 1 ? "" : "s"}`;
}

// Nothing to compare: the safe route is no better than the direct one and takes the same time.
export function noDifference({ safe, direct }, mode) {
  if (Math.round(safe.duration_min) !== Math.round(direct.duration_min)) return false;
  return mode === "summer"
    ? safe.shaded_pct === direct.shaded_pct
    : safe.risk_streets + safe.reported_streets === direct.risk_streets + direct.reported_streets;
}

export function todayAt(hhmm) {
  // Local wall-clock time today in Bengaluru (UTC+05:30), as ISO 8601 with offset.
  const now = new Date(Date.now() + 5.5 * 3600 * 1000).toISOString().slice(0, 10);
  return `${now}T${hhmm}:00+05:30`;
}

export function duration(minutes) {
  const m = Math.round(minutes);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}
