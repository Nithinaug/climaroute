import { useCallback, useEffect, useState } from "react";
import { API_URLS, getArea, getBestTime, getPlaceName, getReports, getRoute, postReport, searchPlaces, setCityApi } from "./api.js";
import { comparison, conditionsText, duration, todayAt } from "./format.js";
import MapView from "./MapView.jsx";

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

// Fill in a tapped point's street name once it arrives (if the point hasn't changed since).
const nameIt = (p, set) =>
  getPlaceName(p)
    .then(({ name }) => name && set((cur) => (cur?.lat === p.lat && cur?.lon === p.lon ? { ...cur, name } : cur)))
    .catch(() => {});
const SIMULATED_RAIN = 50; // mm/h: a heavy Indian monsoon downpour
const slug = (name) => name.toLowerCase().split(",")[0].trim().replace(/\s+/g, "-");

function PlaceSearch({ label, place, onSelect }) {
  const [text, setText] = useState("");
  const [results, setResults] = useState([]);
  const shown = place?.name ?? "";

  useEffect(() => setText(shown), [shown]);

  useEffect(() => {
    if (text.trim().length < 3 || text === shown) return setResults([]);
    let cancelled = false;
    const timer = setTimeout(() => {
      searchPlaces(text.trim())
        .then((r) => !cancelled && setResults(r.results))
        .catch(() => !cancelled && setResults([]));
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [text, shown]);

  return (
    <div className="search">
      <label>
        {label}
        <input
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      {results.length > 0 && (
        <ul className="results">
          {results.map((r) => (
            <li key={`${r.lat},${r.lon}`}>
              <button type="button" onClick={() => onSelect(r)}>{r.name}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Stats({ title, s, mode, swatch }) {
  return (
    <div className="stat">
      <span className={`swatch ${swatch}`} aria-hidden="true" />
      <strong>{title}</strong>
      <span>
        {(s.distance_m / 1000).toFixed(1)} km · {duration(s.duration_min)} ·{" "}
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
  const [simulateRain, setSimulateRain] = useState(false);
  const [sensitive, setSensitive] = useState(false);
  const [best, setBest] = useState(null);
  const [reports, setReports] = useState(null);
  const [reporting, setReporting] = useState(false);
  const [notice, setNotice] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const [cities, setCities] = useState([]);

  const chooseCity = useCallback((city) => {
    setCityApi(city.url);
    history.replaceState(null, "", `#${slug(city.name)}`);
    setArea(city);
    setOrigin(null);
    setDestination(null);
    setResult(null);
    setReports(null);
    setError(null);
    getReports().then(setReports).catch(() => {});
  }, []);

  useEffect(() => {
    Promise.all(API_URLS.map((url) => getArea(url).then((a) => ({ ...a, url })).catch(() => null)))
      .then((found) => {
        const ok = found.filter(Boolean);
        if (!ok.length) throw new Error("Can't reach the server. Check your connection and try again.");
        setCities(ok);
        chooseCity(ok.find((c) => `#${slug(c.name)}` === location.hash) ?? ok[0]);
      })
      .catch((e) => setError(e.message));
  }, [chooseCity]);

  const report = useCallback(async (p) => {
    setReporting(false);
    try {
      await postReport(p);
      setReports(await getReports());
      setNotice("Thanks! Routes will avoid this street for the next 3 hours.");
    } catch (e) {
      setError(e.message);
    }
  }, []);

  const pick = useCallback(
    (p) => {
      setNotice(null);
      if (reporting) return report(p);
      if (area && !inArea(area, p)) return; // greyed out on the map
      setError(null);
      if (!origin || destination) {
        setOrigin(p);
        nameIt(p, setOrigin);
        setDestination(null);
        setResult(null);
      } else {
        setDestination(p);
        nameIt(p, setDestination);
      }
    },
    [area, origin, destination, reporting, report],
  );

  useEffect(() => {
    if (!origin || !destination) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setBest(null);
    getRoute({
      origin: { lat: origin.lat, lon: origin.lon },
      destination: { lat: destination.lat, lon: destination.lon },
      mode,
      transport,
      ...(time && { departure_time: todayAt(time) }),
      ...(mode === "monsoon" && simulateRain && { simulate_rain_mm_per_hour: SIMULATED_RAIN }),
      sensitive,
    })
      .then((r) => !cancelled && setResult(r))
      .catch((e) => {
        if (cancelled) return;
        setResult(null);
        setError(e.message);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  // Coordinates, not objects: adding a place name to a point must not re-route.
  }, [origin?.lat, origin?.lon, destination?.lat, destination?.lon, mode, transport, time, simulateRain, sensitive, reports]);

  const findBestTime = () =>
    getBestTime({
      origin: { lat: origin.lat, lon: origin.lon },
      destination: { lat: destination.lat, lon: destination.lon },
      mode: "summer",
      transport,
      sensitive,
      ...(time && { departure_time: todayAt(time) }),
    })
      .then(setBest)
      .catch((e) => setError(e.message));

  const useMyLocation = () => {
    if (!navigator.geolocation) return setError("Location isn't available in this browser.");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const p = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        if (area && !inArea(area, p)) return setError(`You're outside ${area.name}.`);
        setDestination(null);
        setResult(null);
        setOrigin(null);
        pick(p);
      },
      () => setError("Couldn't get your location. Tap the map instead."),
    );
  };

  const hint = reporting
    ? "Tap the flooded street on the map."
    : !origin
    ? "Search or tap the map to set your start."
    : !destination
      ? "Now search or tap your destination."
      : null;

  return (
    <div className="app">
      <MapView
        area={area}
        origin={origin}
        destination={destination}
        result={result}
        mode={mode}
        reports={reports}
        onPick={pick}
      />
      <aside className="panel" aria-label="Route options">
        <header>
          <h1>ClimaRoute</h1>
          <p className="tagline">Shaded routes in the heat. Dry routes in the rain.</p>
        </header>

        {cities.length > 1 && (
          <label className="city">
            City
            <select value={area?.url}
              onChange={(e) => chooseCity(cities.find((c) => c.url === e.target.value))}>
              {cities.map((c) => <option key={c.url} value={c.url}>{c.name}</option>)}
            </select>
          </label>
        )}

        <PlaceSearch label="From" place={origin}
          onSelect={(p) => { setError(null); setResult(null); setOrigin(p); }} />
        <PlaceSearch label="To" place={destination}
          onSelect={(p) => { setError(null); setResult(null); setDestination(p); }} />

        <Toggle label="Conditions" value={mode} onChange={setMode}
          options={[["summer", "☀️ Summer"], ["monsoon", "🌧️ Monsoon"]]} />
        <Toggle label="Travelling by" value={transport} onChange={setTransport}
          options={[["walk", "🚶 Walk"], ["two_wheeler", "🛵 Two-wheeler"]]} />

        <label className="simulate">
          <input type="checkbox" checked={sensitive} onChange={(e) => setSensitive(e.target.checked)} />
          Heat-sensitive (elderly, children)
        </label>

        {mode === "monsoon" && (
          <label className="simulate">
            <input type="checkbox" checked={simulateRain} onChange={(e) => setSimulateRain(e.target.checked)} />
            Simulate heavy rain ({SIMULATED_RAIN} mm/h)
          </label>
        )}

        {mode === "summer" && (
          <div className="row">
            <label className="time">
              Leaving at
              <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
              {time && (
                <button type="button" className="link" onClick={() => setTime("")}>now</button>
              )}
            </label>
          </div>
        )}

        <div className="row actions">
          <button type="button" onClick={useMyLocation}>📍 Use my location</button>
          <button type="button" aria-pressed={reporting} onClick={() => setReporting((r) => !r)}>
            🚩 Report flooding
          </button>
          {(origin || destination) && (
            <button type="button" className="link" onClick={() => { setOrigin(null); setDestination(null); setResult(null); }}>
              Clear
            </button>
          )}
        </div>

        <div aria-live="polite">
          {hint && <p className="hint">{hint}</p>}
          {loading && <p className="hint">Finding the safest route…</p>}
          {notice && <p className="notice">{notice}</p>}
          {error && <p className="error" role="alert">{error}</p>}
          {result && !loading && (
            <section className="result">
              <p className="headline">{comparison(result.stats, mode)}</p>
              <Stats title="Safe route" s={result.stats.safe} mode={mode} swatch="safe" />
              {mode === "summer" && !best && (
                <button type="button" className="link" onClick={findBestTime}>Best time to leave?</button>
              )}
              {best && (
                <p className="notice">
                  Best in the next 3 h: leave at <strong>{best.best.time}</strong> ({best.best.shaded_pct}% shaded
                  {best.best.temperature_c != null && `, ${Math.round(best.best.temperature_c)}°C`}).{" "}
                  {best.best.time !== best.options[0].time && (
                    <button type="button" className="link" onClick={() => setTime(best.best.time)}>Use this time</button>
                  )}
                </p>
              )}
              <Stats title="Direct route" s={result.stats.direct} mode={mode} swatch="direct" />
              <p className="fine">{conditionsText(result.conditions, mode)}</p>
              {reports?.features?.length > 0 && (
                <p className="fine"><span className="dot report" aria-hidden="true" /> Reported flooding (fades over 3 h)</p>
              )}
            </section>
          )}
        </div>

        <footer className="fine">
          {area && `Covers ${area.name}.`} Map © OpenStreetMap contributors.
          Heights: Google Open Buildings. Elevation: Copernicus DEM. Weather: Open-Meteo (live).
        </footer>
      </aside>
    </div>
  );
}
