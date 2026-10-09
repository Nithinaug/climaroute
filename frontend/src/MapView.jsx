import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef, useState } from "react";

// Let Vite bundle MapLibre's worker; its default path doesn't survive bundling.
setWorkerUrl(workerUrl);

const STYLE_URL =
  import.meta.env.VITE_MAP_STYLE_URL || "https://tiles.openfreemap.org/styles/liberty";
const INDIA = [80, 22];
const EMPTY = { type: "FeatureCollection", features: [] };
const COLORS = { safe: "#16a34a", direct: "#dc2626", origin: "#2563eb", destination: "#1f2937" };

const point = (p, role) =>
  p && { type: "Feature", geometry: { type: "Point", coordinates: [p.lon, p.lat] }, properties: { role } };

function addLayers(map) {
  for (const id of ["direct", "safe", "points", "water", "flood", "reports"].map((n) => `cr-${n}`)) {
    map.addSource(id, { type: "geojson", data: EMPTY });
  }
  map.addLayer({ id: "cr-flood", type: "circle", source: "cr-flood",
    paint: { "circle-radius": 14, "circle-color": "#3b82f6", "circle-opacity": 0.35 } });
  map.addLayer({ id: "cr-direct", type: "line", source: "cr-direct",
    layout: { "line-cap": "round" },
    paint: { "line-color": COLORS.direct, "line-width": 4 } });
  map.addLayer({ id: "cr-safe", type: "line", source: "cr-safe",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": COLORS.safe, "line-width": 6 } });
  map.addLayer({ id: "cr-water", type: "circle", source: "cr-water", minzoom: 14,
    paint: { "circle-radius": 5, "circle-color": "#0ea5e9", "circle-stroke-width": 1.5,
             "circle-stroke-color": "#fff" } });
  // Reports fade as they age.
  map.addLayer({ id: "cr-reports", type: "circle", source: "cr-reports",
    paint: { "circle-radius": 10, "circle-color": "#f59e0b",
             "circle-opacity": ["+", 0.35, ["*", 0.65, ["get", "strength"]]],
             "circle-stroke-width": 3, "circle-stroke-color": "#78350f" } });
  map.addLayer({ id: "cr-points", type: "circle", source: "cr-points",
    paint: { "circle-radius": 8, "circle-stroke-width": 2, "circle-stroke-color": "#fff",
             "circle-color": ["match", ["get", "role"], "origin", COLORS.origin, COLORS.destination] } });
}

export default function MapView({ area, origin, destination, result, mode, reports, onPick }) {
  const container = useRef(null);
  const mapRef = useRef(null);
  const pickRef = useRef(onPick);
  const shownRef = useRef(null);
  const [ready, setReady] = useState(false);
  pickRef.current = onPick;

  useEffect(() => {
    const map = new MapLibreMap({
      container: container.current,
      style: STYLE_URL,
      center: [77.62, 12.98],
      zoom: 11,
      attributionControl: { compact: true },
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      addLayers(map);
      setReady(true);
    });
    map.on("click", (e) => pickRef.current({ lat: e.lngLat.lat, lon: e.lngLat.lng }));
    mapRef.current = map;
    return () => map.remove();
  }, []);

  useEffect(() => {
    if (!ready || !area) return;
    const map = mapRef.current;
    map.getSource("cr-water").setData(area.water_points ?? EMPTY);
    map.getSource("cr-flood").setData(area.flood_spots ?? EMPTY);
    const desktop = window.matchMedia("(min-width: 768px)").matches;
    // Keep the area clear of the panel (left on desktop, bottom sheet on phones).
    const padding = desktop
      ? { top: 8, right: 56, bottom: 8, left: 416 }
      : { top: 8, right: 8, bottom: window.innerHeight * 0.55, left: 8 };
    // Only the city is ever on screen: the view can't show (or be clicked) outside its box.
    map.setMaxBounds(null);
    map.setMinZoom(null);
    const first = !shownRef.current;
    shownRef.current = area;
    if (first) {
      map.fitBounds(area.bbox, { padding, duration: 0 });
      map.setMaxBounds(area.bbox);
      return;
    }
    // Switching city: pull out to India on the globe, dive into the new city tilted, then level out.
    // Each step checks the city is still the chosen one, so a quick re-pick cancels the rest.
    map.stop();
    const live = () => shownRef.current === area;
    const step = (fn, opts) => {
      const done = map.once("moveend");
      map[fn]({ ...opts, padding });
      return done;
    };
    // Zoom measured while still zoomed in (on the zoomed-out globe it comes out short). The centre is
    // the box's own: the padding passed to each step already shifts it clear of the panel.
    const { zoom } = map.cameraForBounds(area.bbox, { padding });
    const center = [(area.bbox[0] + area.bbox[2]) / 2, (area.bbox[1] + area.bbox[3]) / 2];
    // Globe only for the trip: maxBounds (the city lock) only works on the flat map.
    map.setProjection({ type: "globe" });
    (async () => {
      await step("easeTo", { center: INDIA, zoom: desktop ? 3.6 : 2.8, pitch: 0, bearing: 0, duration: 1600 });
      if (!live()) return;
      await step("flyTo", { center, zoom, pitch: 55, bearing: -20, duration: 2600, curve: 1.2 });
      if (!live()) return;
      await step("easeTo", { pitch: 0, bearing: 0, duration: 1200 });
      if (!live()) return;
      map.setProjection({ type: "mercator" });
      map.setMaxBounds(area.bbox);
    })();
  }, [ready, area]);

  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current;
    map.setLayoutProperty("cr-water", "visibility", mode === "summer" ? "visible" : "none");
    map.setLayoutProperty("cr-flood", "visibility", mode === "monsoon" ? "visible" : "none");
  }, [ready, mode]);

  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current;
    const features = [point(origin, "origin"), point(destination, "destination")].filter(Boolean);
    map.getSource("cr-points").setData({ type: "FeatureCollection", features });
    map.getSource("cr-safe").setData(result?.safe_route ?? EMPTY);
    map.getSource("cr-direct").setData(result?.direct_route ?? EMPTY);
  }, [ready, origin, destination, result]);

  useEffect(() => {
    if (ready) mapRef.current.getSource("cr-reports").setData(reports ?? EMPTY);
  }, [ready, reports]);

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
