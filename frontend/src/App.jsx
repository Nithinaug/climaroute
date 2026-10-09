import { motion, MotionConfig, useSpring, useTransform } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_URLS, getArea, getBestTime, getPlaceName, getReports, getRoute, postReport, searchPlaces, setCityApi } from "./api.js";
import { comparison, conditionsText, duration, todayAt } from "./format.js";
import MapView from "./MapView.jsx";

const inArea = (area, p) =>
  area && p.lon >= area.bbox[0] && p.lat >= area.bbox[1] && p.lon <= area.bbox[2] && p.lat <= area.bbox[3];

// Segmented switch; the selected pill slides between options.
function Toggle({ label, value, options, onChange, tone = "bg-white", text = "text-ink", track = "bg-black/5" }) {
  return (
    <fieldset className={`grid grid-flow-col auto-cols-fr rounded-full p-1 ${track}`}>
      <legend className="sr-only">{label}</legend>
      {options.map(([v, name]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
          className="relative min-h-10 rounded-full px-3 font-semibold cursor-pointer">
          {value === v && (
            <motion.span layoutId={label} className={`absolute inset-0 rounded-full shadow-sm ${tone}`}
              transition={{ type: "spring", stiffness: 500, damping: 38 }} />
          )}
          <span className={`relative ${value === v ? text : "opacity-70"}`}>{name}</span>
        </button>
      ))}
    </fieldset>
  );
}

// Number that counts up to its new value.
function Count({ value }) {
  const spring = useSpring(0, { stiffness: 90, damping: 18 });
  const shown = useTransform(spring, (n) => Math.round(n));
  useEffect(() => spring.set(value), [spring, value]);
  return <motion.span>{shown}</motion.span>;
}

// Shade as a ring that fills to its percentage.
function Ring({ pct, color }) {
  return (
    <span className="relative grid size-14 shrink-0 place-items-center">
      <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90" aria-hidden="true">
        <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--color-line)" strokeWidth="3.5" />
        <motion.circle cx="18" cy="18" r="15.5" fill="none" stroke={color} strokeWidth="3.5" strokeLinecap="round"
          initial={{ pathLength: 0 }} animate={{ pathLength: pct / 100 }}
          transition={{ type: "spring", stiffness: 60, damping: 16 }} />
      </svg>
      <span className="text-sm font-extrabold tabular-nums"><Count value={pct} />%</span>
    </span>
  );
}

// Google's Material Symbols, loaded as a font in index.html.
const Icon = ({ name, className = "" }) => (
  <span className={`material-symbols-rounded align-middle ${className}`} aria-hidden="true">{name}</span>
);

const field = "w-full rounded-xl border border-line bg-white px-3 py-2.5 text-base";
const linkBtn = "cursor-pointer font-semibold underline underline-offset-2";

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
    <div className="relative">
      <label className="grid gap-1 text-sm text-muted">
        {label}
        <input type="search" value={text} onChange={(e) => setText(e.target.value)}
          className={`${field} text-ink`} />
      </label>
      {results.length > 0 && (
        <ul className="absolute inset-x-0 z-10 mt-1 rounded-xl border border-line bg-white p-1 shadow-lg">
          {results.map((r) => (
            <li key={`${r.lat},${r.lon}`}>
              <button type="button" onClick={() => onSelect(r)}
                className="w-full cursor-pointer rounded-lg px-3 py-2 text-left hover:bg-black/5">{r.name}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Stats({ title, s, mode, color }) {
  const summer = mode === "summer";
  return (
    <div className="flex items-center gap-3">
      <span className="h-10 w-1.5 shrink-0 rounded-full" style={{ background: color }} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{title}</p>
        <p className="text-sm text-muted">{(s.distance_m / 1000).toFixed(1)} km, {duration(s.duration_min)}</p>
      </div>
      {summer ? (
        <span className="grid justify-items-center gap-0.5 text-xs text-muted">
          <Ring pct={s.shaded_pct} color={color} />shaded
        </span>
      ) : (
        <p className="text-right leading-none">
          <span className="text-3xl font-extrabold tabular-nums"><Count value={s.risk_streets} /></span>
          <span className="block text-xs text-muted">flood-risk streets</span>
        </p>
      )}
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
  const timeRef = useRef(null);
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
  }, [origin?.lat, origin?.lon, destination?.lat, destination?.lon, mode, transport, time, simulateRain, reports]);

  const findBestTime = () =>
    getBestTime({
      origin: { lat: origin.lat, lon: origin.lon },
      destination: { lat: destination.lat, lon: destination.lon },
      mode: "summer",
      transport,
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

  const summer = mode === "summer";

  return (
    <MotionConfig reducedMotion="user">
    <div className="relative h-dvh">
      <MapView
        area={area}
        origin={origin}
        destination={destination}
        result={result}
        mode={mode}
        reports={reports}
        onPick={pick}
      />
      <aside aria-label="Route options"
        className="absolute inset-x-0 bottom-0 max-h-[55dvh] overflow-y-auto overscroll-none rounded-t-3xl bg-white shadow-[0_-8px_30px_rgb(0_0_0/0.18)]
          md:inset-x-auto md:top-4 md:bottom-auto md:left-4 md:w-[380px] md:max-h-[calc(100dvh-2rem)] md:rounded-3xl">
        <header className={`grid gap-3 px-5 pt-5 pb-4 transition-colors duration-500 ${summer ? "bg-sun text-sun-deep" : "bg-rain text-white"}`}>
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight">ClimaRoute</h1>
            <p className="opacity-80">{summer ? "Shaded routes in the heat." : "Dry routes in the rain."}</p>
          </div>
          <Toggle label="Season" value={mode} onChange={setMode} track="bg-black/15"
            tone={summer ? "bg-sun-soft" : "bg-white"} text={summer ? "text-sun-deep" : "text-rain"}
            options={[["summer", "Summer"], ["monsoon", "Monsoon"]]} />
        </header>

        <div className="grid gap-4 p-5">
          {cities.length > 1 && (
            <label className="grid gap-1 text-sm text-muted">
              City
              <select value={area?.url} className={`${field} text-ink`}
                onChange={(e) => chooseCity(cities.find((c) => c.url === e.target.value))}>
                {cities.map((c) => <option key={c.url} value={c.url}>{c.name}</option>)}
              </select>
            </label>
          )}

          <Toggle label="Travelling by" value={transport} onChange={setTransport}
            tone={summer ? "bg-sun-soft" : "bg-rain-soft"} text={summer ? "text-sun-deep" : "text-rain"}
            options={[["walk", <><Icon name="directions_walk" /><span className="sr-only">Walk</span></>],
                      ["two_wheeler", <><Icon name="two_wheeler" /><span className="sr-only">Two-wheeler</span></>]]} />

          {/* From and To joined like the two ends of a trip on the map. */}
          <div className="grid grid-cols-[14px_1fr_auto] gap-x-3">
            <div className="flex flex-col items-center pt-[41px] pb-[17px]" aria-hidden="true">
              <span className="size-3 rounded-full bg-origin ring-2 ring-white" />
              <span className="my-1 flex-1 border-l-2 border-dotted border-muted/50" />
              <span className="size-3 rounded-full bg-ink ring-2 ring-white" />
            </div>
            <div className="grid gap-3">
              <PlaceSearch label="From" place={origin}
                onSelect={(p) => { setError(null); setResult(null); setOrigin(p); }} />
              <PlaceSearch label="To" place={destination}
                onSelect={(p) => { setError(null); setResult(null); setDestination(p); }} />
            </div>
            <button type="button" aria-label="Swap start and destination" disabled={!origin && !destination}
              onClick={() => { setResult(null); setOrigin(destination); setDestination(origin); }}
              className="mt-6 grid size-10 cursor-pointer place-items-center self-center rounded-full hover:bg-black/5 disabled:cursor-default disabled:opacity-40">
              <Icon name="swap_vert" />
            </button>
          </div>

          {mode === "monsoon" && (
            <label className="flex items-center gap-3 rounded-xl bg-rain-soft px-3 py-2.5 text-rain">
              <input type="checkbox" className="size-5 accent-rain" checked={simulateRain}
                onChange={(e) => setSimulateRain(e.target.checked)} />
              Simulate heavy rain ({SIMULATED_RAIN} mm/h)
            </label>
          )}

          {summer && (
            <label className="grid gap-1 text-sm text-muted">
              <span className="sr-only">Leaving at</span>
              {/* A "Leave now" pill; the real time input sits invisibly on top of it. */}
              <span className="relative inline-flex min-h-10 items-center gap-2 justify-self-start rounded-full bg-black/5 pl-3 pr-2 text-base font-semibold text-ink">
                <Icon name="schedule" />
                {time ? `Leave at ${time}` : "Leave now"}
                <Icon name="arrow_drop_down" />
                <input ref={timeRef} type="time" value={time}
                  className="absolute inset-0 cursor-pointer opacity-0"
                  onChange={(e) => setTime(e.target.value)} onClick={() => timeRef.current?.showPicker?.()} />
              </span>
              {time && <button type="button" className={`${linkBtn} justify-self-start text-sun-deep`} onClick={() => setTime("")}>Leave now instead</button>}
            </label>
          )}

          <div aria-live="polite" className="grid gap-3">
            {hint && <p className="text-muted">{hint}</p>}
            {loading && <p className="shiny font-semibold">Finding the safest route…</p>}
            {notice && <p className="rounded-xl bg-safe/10 px-3 py-2 text-green-900">{notice}</p>}
            {error && <p className="rounded-xl bg-risk/10 px-3 py-2 text-red-800" role="alert">{error}</p>}
            {result && !loading && (
              <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                className="grid gap-4 rounded-2xl border border-line p-4">
                <p className="text-lg font-extrabold leading-snug">{comparison(result.stats, mode)}</p>
                <Stats title="Safe route" s={result.stats.safe} mode={mode} color="var(--color-safe)" />
                <Stats title="Direct route" s={result.stats.direct} mode={mode} color="var(--color-risk)" />
                {summer && !best && (
                  <button type="button" className={`${linkBtn} justify-self-start text-sun-deep`} onClick={findBestTime}>Best time to leave?</button>
                )}
                {best && (
                  <p className="rounded-xl bg-sun-soft px-3 py-2 text-sun-deep">
                    Best in the next 3 h: leave at <strong>{best.best.time}</strong> ({best.best.shaded_pct}% shaded
                    {best.best.temperature_c != null && `, ${Math.round(best.best.temperature_c)}°C`}).{" "}
                    {best.best.time !== best.options[0].time && (
                      <button type="button" className={linkBtn} onClick={() => setTime(best.best.time)}>Use this time</button>
                    )}
                  </p>
                )}
                <p className="text-xs text-muted">{conditionsText(result.conditions, mode)}</p>
                {reports?.features?.length > 0 && (
                  <p className="flex items-center gap-2 text-xs text-muted">
                    <span className="size-2.5 rounded-full border-2 border-amber-900 bg-amber-500" aria-hidden="true" />
                    Reported flooding (fades over 3 h)
                  </p>
                )}
              </motion.section>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={useMyLocation}
              className="min-h-10 cursor-pointer rounded-full border border-line px-4 font-semibold hover:bg-black/5">
              Use my location
            </button>
            <button type="button" aria-pressed={reporting} onClick={() => setReporting((r) => !r)}
              className={`relative min-h-10 cursor-pointer rounded-full border px-4 font-semibold ${reporting ? "border-amber-600 bg-amber-500 text-amber-950" : "border-line hover:bg-black/5"}`}>
              {reporting && <span className="absolute inset-0 rounded-full bg-amber-500 motion-safe:animate-ping" aria-hidden="true" />}
              <span className="relative">{reporting ? "Tap the flooded street" : "Report flooding"}</span>
            </button>
            {(origin || destination) && (
              <button type="button" className={`${linkBtn} px-2 text-muted`}
                onClick={() => { setOrigin(null); setDestination(null); setResult(null); }}>
                Clear
              </button>
            )}
          </div>

        </div>
        {/* Fades the panel's bottom edge while there's more to scroll; sits empty at the end. */}
        <div className="pointer-events-none sticky bottom-0 h-8 bg-gradient-to-t from-white" aria-hidden="true" />
      </aside>
    </div>
    </MotionConfig>
  );
}
