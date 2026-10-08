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
  const avoided =
    direct.risk_streets + direct.reported_streets - safe.risk_streets - safe.reported_streets;
  if (avoided <= 0) {
    return direct.risk_streets === 0
      ? "No flood-risk streets on the way right now"
      : `${time} · no safer route available`;
  }
  return `${time} · avoids ${avoided} flood-risk street${avoided === 1 ? "" : "s"}`;
}

export function conditionsText(c, mode) {
  if (!c) return "";
  const parts = [];
  if (mode === "summer") {
    if (c.temperature_c != null) parts.push(`${Math.round(c.temperature_c)}°C`);
    if (c.cloud_cover_pct != null) parts.push(`${Math.round(c.cloud_cover_pct)}% cloud`);
    if (c.heat_factor != null) parts.push(`heat weight ${c.heat_factor}`);
    if (c.shade_date) parts.push(`shade for ${c.shade_date}`);
  } else {
    parts.push(`Rain ${c.rain_mm_per_hour} mm/h`);
  }
  if (c.active_reports) parts.push(`${c.active_reports} flood report${c.active_reports === 1 ? "" : "s"}`);
  return parts.join(" · ");
}

export function todayAt(hhmm) {
  // Local wall-clock time today in Bengaluru (UTC+05:30), as ISO 8601 with offset.
  const now = new Date(Date.now() + 5.5 * 3600 * 1000).toISOString().slice(0, 10);
  return `${now}T${hhmm}:00+05:30`;
}
