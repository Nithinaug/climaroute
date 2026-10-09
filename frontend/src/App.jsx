import { motion, MotionConfig, useSpring, useTransform } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_URLS, getArea, getBestTime, getNow, getPlaceName, getRoute, searchPlaces, setCityApi } from "./api.js";
import { comparison, duration, noDifference, todayAt } from "./format.js";
import MapView from "./MapView.jsx";
import RainOverlay from "./RainOverlay.jsx";

const inArea = (area, p) =>
  area && p.lon >= area.bbox[0] && p.lat >= area.bbox[1] && p.lon <= area.bbox[2] && p.lat <= area.bbox[3];

// Segmented switch; the selected pill slides between options. Plain CSS on purpose: Motion's
// layoutId re-animated the pill whenever the panel above it changed height or scrolled.
function Toggle({ label, value, options, onChange, tone = "bg-white", text = "text-ink", track = "bg-black/5" }) {
  const i = options.findIndex(([v]) => v === value);
  return (
    <fieldset className={`relative grid grid-flow-col auto-cols-fr rounded-full p-1 ${track}`}>
      <legend className="sr-only">{label}</legend>
      <span aria-hidden="true"
        className={`absolute inset-y-1 left-1 rounded-full shadow-sm transition-transform duration-300 ease-out motion-reduce:transition-none ${tone}`}
        style={{ width: `calc((100% - 0.5rem) / ${options.length})`, transform: `translateX(${i * 100}%)` }} />
      {options.map(([v, name]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
          className="relative min-h-10 cursor-pointer rounded-full px-3 font-semibold">
          <span className={value === v ? text : "opacity-70"}>{name}</span>
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
    <span className="relative grid size-12 shrink-0 place-items-center">
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

const pad = (n) => String(n).padStart(2, "0");
const hhmm = (mins) => `${pad(Math.floor(mins / 60) % 24)}:${pad(mins % 60)}`;
const minutesNow = () => { const d = new Date(); return d.getHours() * 60 + d.getMinutes(); };
const sunIcon = (mins) => (mins < 360 || mins >= 1140 ? "dark_mode" : mins < 480 || mins >= 1020 ? "wb_twilight" : "light_mode");

// "Leave now" pill with a small menu to type the time, applied with a button (or Enter) so
// half-typed times don't re-route.
function TimeMenu({ time, onChange, children }) {
  const [open, setOpen] = useState(false);
  const [hh, setHh] = useState("");
  const [mm, setMm] = useState("");
  const minuteRef = useRef(null);
  const box = useRef(null);

  useEffect(() => {
    if (!open) return;
    box.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    const outside = (e) => !box.current.contains(e.target) && setOpen(false);
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const toggle = () => {
    if (!open) {
      const [h, m] = (time || hhmm(minutesNow())).split(":");
      setHh(h);
      setMm(m);
    }
    setOpen((o) => !o);
  };
  const apply = (v) => {
    onChange(v);
    setOpen(false);
    // Focus back on the pill (the typed field is going away) without scrolling the panel.
    box.current.querySelector("button").focus({ preventScroll: true });
  };
  const hourOk = /^\d{1,2}$/.test(hh) && Number(hh) < 24;
  const minuteOk = /^\d{1,2}$/.test(mm) && Number(mm) < 60;
  const valid = hourOk && minuteOk;
  const value = valid ? `${pad(Number(hh))}:${pad(Number(mm))}` : "";
  // preventDefault: otherwise the same Enter also "clicks" the pill that gets focus, reopening the menu.
  const applyOnEnter = (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    if (valid) apply(value);
  };

  return (
    <div ref={box} className="grid">
      <div className="flex items-center gap-2">
        <button type="button" aria-expanded={open} aria-haspopup="dialog" onClick={toggle}
          className="inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-full bg-black/5 pl-3 pr-2 font-semibold">
          <Icon name="schedule" />
          {time ? `Leave at ${time}` : "Leave now"}
          <Icon name="arrow_drop_down" className={`transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
        {children}
      </div>
      {open && (
        <div role="dialog" aria-label="Departure time"
          className="mt-2 grid w-full gap-4 rounded-2xl border border-line bg-white p-4">
          {/* Typed hours and minutes; two hour digits jump to the minutes, Enter applies. */}
          <div className="flex items-center gap-2 text-3xl font-extrabold tabular-nums">
            <Icon name={valid ? sunIcon(Number(hh) * 60 + Number(mm)) : "schedule"} className="text-sun" />
            <input value={hh} inputMode="numeric" aria-label="Hour (0 to 23)" autoFocus
              onFocus={(e) => e.target.select()} onKeyDown={applyOnEnter}
              onChange={(e) => {
                // Typing "2100" in one go: the first two digits are the hour, the rest the minutes.
                const v = e.target.value.replace(/\D/g, "");
                setHh(v.slice(0, 2));
                if (v.length > 2) setMm(v.slice(2, 4));
                if (v.length >= 2) minuteRef.current.focus();
              }}
              className={`w-[2.6ch] rounded-lg border bg-white text-center ${hourOk ? "border-line" : "border-risk"}`} />
            :
            <input ref={minuteRef} value={mm} inputMode="numeric" maxLength={2} aria-label="Minute (0 to 59)"
              onFocus={(e) => e.target.select()} onKeyDown={applyOnEnter}
              onChange={(e) => setMm(e.target.value.replace(/\D/g, ""))}
              className={`w-[2.6ch] rounded-lg border bg-white text-center ${minuteOk ? "border-line" : "border-risk"}`} />
          </div>
          <div className="flex gap-2">
            <button type="button" disabled={!valid} onClick={() => apply(value)}
              className="min-h-10 flex-1 cursor-pointer rounded-full bg-sun font-semibold text-sun-deep disabled:cursor-default disabled:opacity-50">
              {valid ? `Leave at ${value}` : "Enter a time"}
            </button>
            {/* The only way back to "now" once a time is set. */}
            {time && (
              <button type="button" onClick={() => apply("")}
                className="min-h-10 cursor-pointer rounded-full border border-line px-4 font-semibold hover:bg-black/5">
                Leave now
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// A choice kept in this browser across reloads (the city is kept in the URL instead). Storage can
// be blocked (private windows): then it's just a normal state.
function useRemembered(key, fallback, allowed) {
  const [value, setValue] = useState(() => {
    try {
      const saved = localStorage.getItem(`climaroute.${key}`);
      return allowed.includes(saved) ? saved : fallback;
    } catch {
      return fallback;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(`climaroute.${key}`, value);
    } catch {
      // not saved; fine
    }
  }, [key, value]);
  return [value, setValue];
}

const field = "w-full rounded-xl border border-line bg-white px-3 py-2 text-base";
const linkBtn = "cursor-pointer font-semibold underline underline-offset-2";

// Fill in a tapped point's street name once it arrives (if the point hasn't changed since).
const nameIt = (p, set, transport) =>
  getPlaceName(p, transport)
    .then(({ name, near_street }) => {
      if (name) set((cur) => (cur?.lat === p.lat && cur?.lon === p.lon ? { ...cur, name } : cur));
      return near_street;
    })
    .catch(() => true); // can't check: let the route request decide
const NOT_NEAR_STREET = (end) => `${end} isn't near a street. Pick a point on or next to a road.`;
const REFRESH_MS = 10 * 60 * 1000;
// Feels-like (heat + humidity) thresholds: caution from 37°C, danger from 42°C.
const HEAT_CAUTION_C = 37;
const HEAT_DANGER_C = 42;
// Heat haze: none at 33°C feels-like, full at 42°C.
const hazeStrength = (feels) => (feels == null ? 0 : Math.min(1, Math.max(0, (feels - 33) / 9)));

// "Feels like": temperature with humidity (apparent temperature); amber, red from 42°C.
function HeatWarning({ feels, at }) {
  const danger = feels >= HEAT_DANGER_C;
  return (
    <p className={`flex items-start gap-2 rounded-xl px-3 py-2 ${danger ? "bg-risk/10 text-red-800" : "bg-sun-soft text-sun-deep"}`}>
      <Icon name="thermostat" className="mt-0.5" />
      <span>Feels like <strong>{Math.round(feels)}°C</strong> at {at}.</span>
    </p>
  );
}
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
      <label>
        <span className="sr-only">{label}</span>
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
          <Ring pct={s.shaded_pct ?? 0} color={color} />shaded
        </span>
      ) : (
        <p className="text-right leading-none">
          <span className="text-3xl font-extrabold tabular-nums"><Count value={s.risk_streets ?? 0} /></span>
          <span className="block text-xs text-muted">flood-risk streets</span>
        </p>
      )}
    </div>
  );
}

export default function App() {
  const [area, setArea] = useState(null);
  const [origin, setOrigin] = useState(null);
  const originRef = useRef(null); // latest start, for checks that answer after a delay
  originRef.current = origin;
  const [destination, setDestination] = useState(null);
  const [mode, setMode] = useRemembered("mode", "summer", ["summer", "monsoon"]);
  const [transport, setTransport] = useRemembered("transport", "walk", ["walk", "two_wheeler"]);
  const [time, setTime] = useState(""); // "" = leave now
  const [simulateRain, setSimulateRain] = useState(false);
  const [best, setBest] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0); // bumped to re-route the same trip
  const [nowWeather, setNowWeather] = useState(null);

  const [cities, setCities] = useState([]);

  const chooseCity = useCallback((city) => {
    setCityApi(city.url);
    history.replaceState(null, "", `#${slug(city.name)}`);
    setArea(city);
    setOrigin(null);
    setDestination(null);
    setResult(null);
    setError(null);
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

  const pick = useCallback(
    (p) => {
      if (area && !inArea(area, p)) return; // greyed out on the map
      setError(null);
      if (!origin || destination) {
        setOrigin(p);
        // Checked as soon as it's tapped: a start in a lake or park is removed with a message.
        nameIt(p, setOrigin, transport).then((near) => {
          const cur = originRef.current;
          if (near !== false || cur?.lat !== p.lat || cur?.lon !== p.lon) return;
          setOrigin(null);
          setError(NOT_NEAR_STREET("Start"));
        });
        setDestination(null);
        setResult(null);
      } else {
        setDestination(p); // named once its route is back (see the route effect)
      }
    },
    [area, origin, destination],
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
        // Drop the end that isn't near a street, so the next tap replaces it.
        if (e.code === "DESTINATION_NOT_NEAR_STREET") setDestination(null);
        if (e.code === "START_NOT_NEAR_STREET") setOrigin(null);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
        // Name a tapped destination only after the route: sent together, the two requests need
        // two Lambdas, and the second is usually cold (seconds to load the street graph).
        if (!destination.name) nameIt(destination, setDestination, transport);
      });
    return () => {
      cancelled = true;
    };
  // Coordinates, not objects: adding a place name to a point must not re-route.
  }, [origin?.lat, origin?.lon, destination?.lat, destination?.lon, mode, transport, time, simulateRain, refresh]);

  // The city's temperature: now, or the forecast for the chosen departure time. Loaded on choosing
  // a city or a time, then every 10 minutes while the tab is visible.
  useEffect(() => {
    if (!area) return;
    let cancelled = false;
    const load = () =>
      document.visibilityState === "visible" &&
      getNow(time && todayAt(time)).then((w) => !cancelled && setNowWeather(w)).catch(() => {});
    setNowWeather(null);
    load();
    const id = setInterval(load, REFRESH_MS);
    document.addEventListener("visibilitychange", load); // back on the tab: fresh reading
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", load);
    };
  }, [area, time]);

  // "Leave now" routes go stale (sun, rain): re-route every 10 minutes while the tab is visible,
  // and on coming back to the tab if it's been longer. Set times are plans, so they're left alone.
  const routedAt = useRef(0);
  useEffect(() => {
    if (result) routedAt.current = Date.now();
  }, [result]);
  useEffect(() => {
    if (!result || time) return;
    const check = () => {
      if (document.visibilityState === "visible" && Date.now() - routedAt.current >= REFRESH_MS) {
        routedAt.current = Date.now(); // one refresh at a time
        setRefresh((n) => n + 1);
      }
    };
    const id = setInterval(check, 60 * 1000);
    document.addEventListener("visibilitychange", check);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", check);
    };
  }, [result, time]);

  const findBestTime = () =>
    getBestTime({
      origin: { lat: origin.lat, lon: origin.lon },
      destination: { lat: destination.lat, lon: destination.lon },
      mode,
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

  const hint = !origin
    ? "Search or tap the map to set your start."
    : !destination
      ? "Now search or tap your destination."
      : null;

  const summer = mode === "summer";
  // Temperature in the city now, or forecast for the departure time when one is set.
  const tempChip = nowWeather?.temperature_c != null && (
    <span className="inline-flex items-center gap-1 rounded-full px-2 text-sm font-semibold text-muted"
      title={time ? `Forecast for ${time} in ${area?.name}` : `Temperature in ${area?.name} now`}>
      <Icon name="thermostat" className="!text-[18px]" />
      {Math.round(nowWeather.temperature_c)}°C
      <span className="sr-only">{time ? `forecast for ${time}` : `in ${area?.name} now`}</span>
    </span>
  );
  const clearButton = (origin || destination) && (
    <button type="button" className={`${linkBtn} ml-auto px-2 text-muted`}
      onClick={() => { setOrigin(null); setDestination(null); setResult(null); }}>
      Clear
    </button>
  );
  // Same shade (or flood risk) and same time both ways: show just the one (green) route.
  const same = result && noDifference(result.stats, mode);

  return (
    <MotionConfig reducedMotion="user">
    <div className="relative h-dvh">
      <MapView
        area={area}
        origin={origin}
        destination={destination}
        result={same ? { ...result, direct_route: null } : result}
        mode={mode}
        departure={time}
        onPick={pick}
      />
      {/* Summer: a warm glow at the map's edges when the trip will feel hot. */}
      <div aria-hidden="true" className="heat-haze pointer-events-none absolute inset-0"
        style={{ opacity: summer ? hazeStrength(result?.conditions?.feels_like_c) : 0 }} />
      {/* Simulated rain shows at once; otherwise the live rain the last route was planned for. */}
      <RainOverlay mmPerHour={summer ? 0 : simulateRain ? SIMULATED_RAIN : (result?.conditions?.rain_mm_per_hour ?? 0)} />
      <aside aria-label="Route options"
        className="absolute inset-x-0 bottom-0 max-h-[55dvh] overflow-y-auto overscroll-none rounded-t-3xl bg-white shadow-[0_-8px_30px_rgb(0_0_0/0.18)]
          md:inset-x-auto md:top-4 md:bottom-auto md:left-4 md:w-[380px] md:max-h-[calc(100dvh-2rem)] md:rounded-3xl">
        <header className={`grid gap-3 p-4 transition-colors duration-500 ${summer ? "bg-sun text-sun-deep" : "bg-rain text-white"}`}>
          <h1 className="sr-only">ClimaRoute</h1>
          <Toggle label="Season" value={mode} onChange={setMode} track="bg-black/15"
            tone={summer ? "bg-sun-soft" : "bg-white"} text={summer ? "text-sun-deep" : "text-rain"}
            options={[["summer", "Summer"], ["monsoon", "Monsoon"]]} />
        </header>

        <div className="grid gap-3 p-4">
          {/* City and how you're travelling share a row. */}
          <div className="flex items-end gap-2">
            {cities.length > 1 && (
              <label className="grid min-w-0 flex-1 gap-0.5 text-xs text-muted">
                City
                <select value={area?.url} className={`${field} text-ink`}
                  onChange={(e) => chooseCity(cities.find((c) => c.url === e.target.value))}>
                  {cities.map((c) => <option key={c.url} value={c.url}>{c.name}</option>)}
                </select>
              </label>
            )}
            <div className="w-36 shrink-0">
              <Toggle label="Travelling by" value={transport} onChange={setTransport}
                tone={summer ? "bg-sun-soft" : "bg-rain-soft"} text={summer ? "text-sun-deep" : "text-rain"}
                options={[["walk", <><Icon name="directions_walk" /><span className="sr-only">Walk</span></>],
                          ["two_wheeler", <><Icon name="two_wheeler" /><span className="sr-only">Two-wheeler</span></>]]} />
            </div>
          </div>

          {/* From and To joined like the two ends of a trip on the map. */}
          <div className="grid grid-cols-[14px_1fr_auto] gap-x-3">
            {/* Start: hollow circle; end: red pin (same marks as on the map), dots between. */}
            <div className="flex flex-col items-center pt-[15px] pb-[11px]" aria-hidden="true">
              <span className="size-3 rounded-full border-2 border-ink bg-white" />
              <span className="flex flex-1 flex-col items-center justify-evenly">
                <span className="size-1 rounded-full bg-muted" />
                <span className="size-1 rounded-full bg-muted" />
                <span className="size-1 rounded-full bg-muted" />
              </span>
              <Icon name="location_on" className="!text-[20px] leading-none text-risk" />
            </div>
            <div className="grid gap-3">
              <PlaceSearch label="From" place={origin}
                onSelect={(p) => { setError(null); setResult(null); setOrigin(p); }} />
              <PlaceSearch label="To" place={destination}
                onSelect={(p) => { setError(null); setResult(null); setDestination(p); }} />
            </div>
            {/* Beside the From box: use my location. Beside the To box: swap the two. */}
            <div className="flex flex-col gap-[14px] pt-px">
              <button type="button" aria-label="Use my location" title="Use my location" onClick={useMyLocation}
                className="grid size-10 cursor-pointer place-items-center rounded-full text-origin hover:bg-black/5">
                <Icon name="my_location" />
              </button>
              <button type="button" aria-label="Swap start and destination" title="Swap start and destination"
                disabled={!origin && !destination} onClick={() => { setOrigin(destination); setDestination(origin); }}
                className="grid size-10 cursor-pointer place-items-center rounded-full hover:bg-black/5 disabled:cursor-default disabled:opacity-40">
                <Icon name="swap_vert" />
              </button>
            </div>
          </div>

          {mode === "monsoon" && (
            <label className="flex items-center gap-3 rounded-xl bg-rain-soft px-3 py-2.5 text-rain">
              <input type="checkbox" className="size-5 accent-rain" checked={simulateRain}
                onChange={(e) => setSimulateRain(e.target.checked)} />
              Simulate heavy rain ({SIMULATED_RAIN} mm/h)
            </label>
          )}

          <TimeMenu time={time} onChange={setTime}>{tempChip}{clearButton}</TimeMenu>

          <div aria-live="polite" className="grid gap-3">
            {hint && <p className="text-muted">{hint}</p>}
            {loading && <p className="shiny font-semibold">Finding the safest route…</p>}
            {error && <p className="rounded-xl bg-risk/10 px-3 py-2 text-red-800" role="alert">{error}</p>}
            {/* Kept (faded) while a new route loads, so the panel doesn't shrink and jump to the top. */}
            {result && (
              <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: loading ? 0.45 : 1, y: 0 }}
                aria-busy={loading} className="grid gap-3 rounded-2xl border border-line p-4">
                {summer && result.conditions?.feels_like_c >= HEAT_CAUTION_C && (
                  <HeatWarning feels={result.conditions.feels_like_c} at={result.conditions.slot_time} />
                )}
                {!summer && result.conditions?.rain_soon && (
                  <p className="flex items-start gap-2 rounded-xl bg-rain-soft px-3 py-2 text-rain">
                    <Icon name="rainy" className="mt-0.5" />
                    <span>
                      Rain expected around <strong>{result.conditions.rain_soon.at}</strong>{" "}
                      ({result.conditions.rain_soon.mm_per_hour} mm/h).{" "}
                      {result.conditions.rain_soon.counted
                        ? "The safe route already avoids the streets it will flood."
                        : "Check again before you leave."}
                    </span>
                  </p>
                )}
                <p className="text-lg font-extrabold leading-snug">{comparison(result.stats, mode)}</p>
                <Stats title="Safe route" s={result.stats.safe} mode={mode} color="var(--color-safe)" />
                {!same && <Stats title="Direct route" s={result.stats.direct} mode={mode} color="var(--color-risk)" />}
                {/* Simulated rain is the same at every hour, so there's no best time to find. */}
                {!best && !(simulateRain && !summer) && (
                  <button type="button" className={`${linkBtn} justify-self-start ${summer ? "text-sun-deep" : "text-rain"}`}
                    onClick={findBestTime}>Best time to leave?</button>
                )}
                {best && (
                  <p className={`rounded-xl px-3 py-2 ${summer ? "bg-sun-soft text-sun-deep" : "bg-rain-soft text-rain"}`}>
                    Best in the next 3 h: leave at <strong>{best.best.time}</strong>{" "}
                    {summer
                      ? `(${best.best.shaded_pct}% shaded${best.best.temperature_c != null ? `, ${Math.round(best.best.temperature_c)}°C` : ""}).`
                      : `(${best.best.risk_streets} flood-risk street${best.best.risk_streets === 1 ? "" : "s"}, ${best.best.rain_mm_per_hour} mm/h rain).`}{" "}
                    {best.best.time !== best.options[0].time && (
                      <button type="button" className={linkBtn} onClick={() => setTime(best.best.time)}>Use this time</button>
                    )}
                  </p>
                )}
              </motion.section>
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
