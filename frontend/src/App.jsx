import { useCallback, useEffect, useState } from "react";
import { getArea, getRoute } from "./api.js";
import { comparison, todayAt } from "./format.js";
import MapView from "./MapView.jsx";
import { PRESETS } from "./presets.js";

const inArea = (area, p) =>
  area && p.lon >= area.bbox[0] && p.lat >= area.bbox[1] && p.lon <= area.bbox[2] && p.lat <= area.bbox[3];

function Toggle({ label, value, options, onChange }) {
  return (
    <fieldset className="toggle">
      <legend>{label}</legend>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}>
          {text}
        </button>
      ))}
    </fieldset>
  );
}

function Stats({ title, s, mode, swatch }) {
  return (
    <div className="stat">
      <span className={`swatch ${swatch}`} aria-hidden="true" />
      <strong>{title}</strong>
      <span>
        {(s.distance_m / 1000).toFixed(1)} km · {Math.round(s.duration_min)} min ·{" "}
        {mode === "summer" ? `${s.shaded_pct}% shaded` : `${s.risk_streets} flood-risk streets`}
      </span>
    </div>
  );
}

export default function App() {
  const [area, setArea] = useState(null);
  const [origin, setOrigin] = useState(null);
  const [destination, setDestination] = useState(null);
  const [mode, setMode] = useState("summer");
  const [transport, setTransport] = useState("walk");
  const [time, setTime] = useState(""); // "" = leave now
  const [rainScenario, setRainScenario] = useState("live");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getArea().then(setArea).catch((e) => setError(e.message));
  }, []);

  const pick = useCallback(
    (p) => {
      if (area && !inArea(area, p)) {
        setError(`That point is outside the covered area (${area.name}). Try a preset trip.`);
        return;
      }
      setError(null);
      if (!origin || destination) {
        setOrigin(p);
        setDestination(null);
        setResult(null);
      } else {
        setDestination(p);
      }
    },
    [area, origin, destination],
  );

  useEffect(() => {
    if (!origin || !destination) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRoute({
      origin,
      destination,
      mode,
      transport,
      rain_scenario: rainScenario,
      ...(time && { departure_time: todayAt(time) }),
    })
      .then((r) => !cancelled && setResult(r))
      .catch((e) => {
        if (cancelled) return;
        setResult(null);
        setError(e.code === "RAIN_UNAVAILABLE" ? `${e.message}` : e.message);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [origin, destination, mode, transport, time, rainScenario]);

  const useMyLocation = () => {
    if (!navigator.geolocation) return setError("Location isn't available in this browser.");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setDestination(null);
        setResult(null);
        setOrigin(null);
        pick({ lat: pos.coords.latitude, lon: pos.coords.longitude });
      },
      () => setError("Couldn't get your location. Tap the map instead."),
    );
  };

  const applyPreset = (p) => {
    setMode(p.mode);
    setTransport(p.transport);
    setTime(p.time ?? "");
    setRainScenario(p.rainScenario ?? "live");
    setOrigin(p.origin);
    setDestination(p.destination);
  };

  const hint = !origin
    ? "Tap the map to set your start, or pick a demo trip."
    : !destination
      ? "Now tap your destination."
      : null;

  return (
    <div className="app">
      <MapView
        area={area}
        origin={origin}
        destination={destination}
        result={result}
        mode={mode}
        onPick={pick}
      />
      <aside className="panel" aria-label="Route options">
        <header>
          <h1>ClimaRoute</h1>
          <p className="tagline">Shaded routes in the heat. Dry routes in the rain.</p>
        </header>

        <Toggle label="Conditions" value={mode} onChange={setMode}
          options={[["summer", "☀️ Summer"], ["monsoon", "🌧️ Monsoon"]]} />
        <Toggle label="Travelling by" value={transport} onChange={setTransport}
          options={[["walk", "🚶 Walk"], ["two_wheeler", "🛵 Two-wheeler"]]} />

        <div className="row">
          {mode === "monsoon" ? (
            <Toggle label="Rain" value={rainScenario} onChange={setRainScenario}
              options={[["live", "Live"], ["heavy", "Heavy rain demo"]]} />
          ) : (
            <label className="time">
              Leaving at
              <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
              {time && (
                <button type="button" className="link" onClick={() => setTime("")}>now</button>
              )}
            </label>
          )}
        </div>

        <div className="row actions">
          <button type="button" onClick={useMyLocation}>📍 Use my location</button>
          {(origin || destination) && (
            <button type="button" className="link" onClick={() => { setOrigin(null); setDestination(null); setResult(null); }}>
              Clear
            </button>
          )}
        </div>

        <div aria-live="polite">
          {hint && <p className="hint">{hint}</p>}
          {loading && <p className="hint">Finding the safest route…</p>}
          {error && <p className="error" role="alert">{error}</p>}
          {result && !loading && (
            <section className="result">
              <p className="headline">{comparison(result.stats, mode)}</p>
              <Stats title="Safe route" s={result.stats.safe} mode={mode} swatch="safe" />
              <Stats title="Direct route" s={result.stats.direct} mode={mode} swatch="direct" />
              {mode === "monsoon" && (
                <p className="fine">Rain: {result.conditions.rain_mm_per_hour} mm/hour</p>
              )}
            </section>
          )}
        </div>

        <section className="presets">
          <h2>Demo trips</h2>
          {PRESETS.map((p) => (
            <button key={p.label} type="button" onClick={() => applyPreset(p)}>{p.label}</button>
          ))}
        </section>

        <footer className="fine">
          Covers {area?.name ?? "Koramangala, Bengaluru"}. Map © OpenStreetMap contributors.
          Heights: Google Open Buildings. Elevation: Copernicus DEM. Rain: Open-Meteo.
        </footer>
      </aside>
    </div>
  );
}
