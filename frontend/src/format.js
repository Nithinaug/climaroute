// Human-readable comparison of the safe route against the direct one.
export function comparison(stats, mode) {
  const { safe, direct } = stats;
  const extra = Math.round(safe.duration_min - direct.duration_min);
  const time =
    extra > 0 ? `${extra} min longer` : extra < 0 ? `${-extra} min shorter` : "Same time";

  if (mode === "summer") {
    if (safe.shaded_pct === direct.shaded_pct && extra === 0) {
      return "The direct route is already the shadiest";
    }
    return `${time} · ${safe.shaded_pct}% shaded vs ${direct.shaded_pct}%`;
  }
  const avoided = direct.risk_streets - safe.risk_streets;
  if (avoided <= 0) {
    return direct.risk_streets === 0
      ? "No flood-risk streets on the way right now"
      : `${time} · no safer route available`;
  }
  return `${time} · avoids ${avoided} flood-risk street${avoided === 1 ? "" : "s"}`;
}

export function todayAt(hhmm) {
  // Local wall-clock time today in Bengaluru (UTC+05:30), as ISO 8601 with offset.
  const now = new Date(Date.now() + 5.5 * 3600 * 1000).toISOString().slice(0, 10);
  return `${now}T${hhmm}:00+05:30`;
}
