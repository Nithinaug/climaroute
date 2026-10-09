import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef, useState } from "react";
import { todayAt } from "./format.js";
import { applyNight, nightness, sunElevation } from "./nightMap.js";

// Let Vite bundle MapLibre's worker; its default path doesn't survive bundling.
setWorkerUrl(workerUrl);

const STYLE_URL =
  import.meta.env.VITE_MAP_STYLE_URL || "https://tiles.openfreemap.org/styles/liberty";
const EMPTY = { type: "FeatureCollection", features: [] };
const COLORS = { safe: "#16a34a", direct: "#dc2626", destination: "#1f2937", pin: "#dc2626" };

const merc = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

// The view maxBounds settles on: the whole map canvas inside the city's box. Landing exactly here
// means turning the lock on afterwards doesn't snap the zoom (and flash unloaded tiles).
function lockedCamera(map, [w, s, e, n]) {
  const { clientWidth, clientHeight } = map.getContainer();
  const dx = (e - w) / 360;
  const dy = (merc(n) - merc(s)) / (2 * Math.PI);
  const zoom = Math.log2(Math.max(clientWidth / dx, clientHeight / dy) / 512) + 0.001;
  const lat = ((2 * Math.atan(Math.exp((merc(n) + merc(s)) / 2)) - Math.PI / 2) * 180) / Math.PI;
  return { center: [(w + e) / 2, lat], zoom };
}

// Start downloading the vector tiles the flight will land on, so they're in the browser's cache
// (or close) by the time it gets there instead of popping in as blank land.
function prefetchTiles(map, [w, s, e, n], zoom) {
  const source = Object.keys(map.getStyle().sources).map((id) => map.getSource(id)).find((src) => src.type === "vector");
  const template = source?.tiles?.[0];
  if (!template) return;
  const tx = (lon, z) => Math.floor(((lon + 180) / 360) * 2 ** z);
  const ty = (lat, z) => Math.floor(((1 - merc(lat) / Math.PI) / 2) * 2 ** z);
  // MapLibre's vector tiles are 512 px, so a camera at zoom z draws tiles from z - 1.
  for (const z of [Math.floor(zoom) - 1, Math.floor(zoom)]) {
    for (let x = tx(w, z); x <= tx(e, z); x++) {
      for (let y = ty(n, z); y <= ty(s, z); y++) {
        fetch(template.replace("{z}", z).replace("{x}", x).replace("{y}", y)).catch(() => {});
      }
    }
  }
}

function addLayers(map) {
  for (const id of ["direct", "safe", "water"].map((n) => `cr-${n}`)) {
    map.addSource(id, { type: "geojson", data: EMPTY });
  }
  map.addLayer({ id: "cr-direct", type: "line", source: "cr-direct",
    layout: { "line-cap": "round" },
    // Under the wider green line: shared streets show green, red only where the direct route differs.
    paint: { "line-color": COLORS.direct, "line-width": 4 } });
  map.addLayer({ id: "cr-safe", type: "line", source: "cr-safe",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": COLORS.safe, "line-width": 6 } });
  map.addLayer({ id: "cr-water", type: "circle", source: "cr-water", minzoom: 14,
    paint: { "circle-radius": 5, "circle-color": "#0ea5e9", "circle-stroke-width": 1.5,
             "circle-stroke-color": "#fff" } });
}

export default function MapView({ area, origin, destination, result, loading, mode, departure, onPick }) {
  const container = useRef(null);
  const mapRef = useRef(null);
  const pickRef = useRef(onPick);
  const shownRef = useRef(null);
  const zoomedToRoute = useRef(false);
  const pinRef = useRef(null);
  const startRef = useRef(null);
  const [ready, setReady] = useState(false);
  pickRef.current = onPick;

  useEffect(() => {
    const map = new MapLibreMap({
      container: container.current,
      style: STYLE_URL,
      center: [77.62, 12.98],
      zoom: 11,
      attributionControl: { compact: true },
      maxTileCacheSize: 2000, // keep tiles from earlier flights so going back needs no downloads
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      addLayers(map);
      setReady(true);
    });
    map.on("click", (e) => pickRef.current({ lat: e.lngLat.lat, lon: e.lngLat.lng }));
    mapRef.current = map;
    pinRef.current = new Marker({ color: COLORS.pin });
    const start = document.createElement("div");
    start.className = "start-marker";
    startRef.current = new Marker({ element: start });
    return () => map.remove();
  }, []);

  useEffect(() => {
    if (!ready || !area) return;
    const map = mapRef.current;
    map.getSource("cr-water").setData(area.water_points ?? EMPTY);
    // Only the city is ever on screen: the view can't show (or be clicked) outside its box.
    map.setMaxBounds(null);
    map.setMinZoom(null);
    const first = !shownRef.current;
    shownRef.current = area;
    zoomedToRoute.current = false; // the new city gets its own camera below
    const camera = lockedCamera(map, area.bbox);
    if (first) {
      map.jumpTo(camera);
      map.setMaxBounds(area.bbox);
      return;
    }
    // Switching city: fly straight there, then lock the view once it lands
    // (not if another city was picked mid-flight).
    prefetchTiles(map, area.bbox, camera.zoom);
    map.flyTo({ ...camera, speed: 0.8 });
    map.once("moveend", () => shownRef.current === area && !map.isMoving() && map.setMaxBounds(area.bbox));
  }, [ready, area]);

  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current;
    map.setLayoutProperty("cr-water", "visibility", mode === "summer" ? "visible" : "none");
  }, [ready, mode]);

  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current;
    if (origin) startRef.current.setLngLat([origin.lon, origin.lat]).addTo(map);
    else startRef.current.remove();
    if (destination) pinRef.current.setLngLat([destination.lon, destination.lat]).addTo(map);
    else pinRef.current.remove();
  }, [ready, origin, destination]);

  // Route changes cross-fade: the old lines dim while a new route loads, then the new ones fade in
  // (instead of popping in) when it arrives.
  const ROUTE_LAYERS = ["cr-safe", "cr-direct"];
  const fade = (map, opacity, duration) =>
    ROUTE_LAYERS.forEach((id) => {
      map.setPaintProperty(id, "line-opacity-transition", { duration, delay: 0 });
      map.setPaintProperty(id, "line-opacity", opacity);
    });
  useEffect(() => {
    if (ready && loading) fade(mapRef.current, 0.3, 250);
  }, [ready, loading]);
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current;
    fade(map, 0, 0);
    map.getSource("cr-safe").setData(result?.safe_route ?? EMPTY);
    map.getSource("cr-direct").setData(result?.direct_route ?? EMPTY);
    const id = requestAnimationFrame(() => fade(map, 1, 500));
    return () => cancelAnimationFrame(id);
  }, [ready, result]);

  // Zoom to a new trip so the two lines are big enough to tell apart. Only when the start or end
  // changed: a refreshed or re-moded route for the same trip leaves the view where the user put it.
  const fittedTrip = useRef("");
  useEffect(() => {
    if (!ready || !result || !origin || !destination) return;
    const trip = [origin.lat, origin.lon, destination.lat, destination.lon].join();
    if (trip === fittedTrip.current) return;
    fittedTrip.current = trip;
    const xs = [], ys = [];
    const walk = (c) => (typeof c[0] === "number" ? (xs.push(c[0]), ys.push(c[1])) : c.forEach(walk));
    for (const r of [result.safe_route, result.direct_route]) {
      for (const f of r?.features ?? (r ? [r] : [])) walk(f.geometry.coordinates);
    }
    if (!xs.length) return;
    zoomedToRoute.current = true;
    const desktop = window.matchMedia("(min-width: 768px)").matches;
    mapRef.current.fitBounds(
      [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)],
      { padding: desktop ? { top: 60, right: 80, bottom: 60, left: 460 }
                         : { top: 40, right: 40, bottom: window.innerHeight * 0.55 + 20, left: 40 },
        maxZoom: 16, duration: 800 },
    );
  }, [ready, result]);

  // Day, dusk or night map for the departure time ("" = now; rechecked every 5 minutes).
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setClock(Date.now()), 5 * 60 * 1000);
    return () => clearInterval(id);
  }, []);
  const lastNight = useRef(null);
  useEffect(() => {
    if (!ready || !area) return;
    const when = departure ? new Date(todayAt(departure)) : new Date(clock);
    // Rounded so tiny sun moves don't restyle the map every few minutes.
    const t = Math.round(nightness(sunElevation(when, area.center.lat, area.center.lon)) * 10) / 10;
    if (t === lastNight.current) return;
    applyNight(mapRef.current, t, lastNight.current === null ? 0 : 1500);
    lastNight.current = t;
  }, [ready, area, departure, clock]);

  // Cleared (no start or end): zoom back out from the last route to the whole city.
  useEffect(() => {
    if (!ready || !area || origin || destination || !zoomedToRoute.current) return;
    zoomedToRoute.current = false;
    fittedTrip.current = "";
    mapRef.current.easeTo({ ...lockedCamera(mapRef.current, area.bbox), duration: 800 });
  }, [ready, area, origin, destination]);

  return (
    <div
      ref={container}
      // Inline: MapLibre's unlayered CSS sets position: relative and beats Tailwind's layered utilities.
      style={{ position: "absolute", inset: 0 }}
      role="application"
      aria-label="Map. Tap to set the start, then the destination."
    />
  );
}
