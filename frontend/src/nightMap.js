// Night view for the base map: each layer's day colours blended towards a night palette by how
// far the sun is below the horizon at the city for the departure time. Our route layers (cr-*) keep
// their colours, so they stand out more at night.

const RAD = Math.PI / 180;
const J2000_MS = 946728000000; // 2000-01-01 12:00 UTC

// Sun height above the horizon in degrees (low-precision almanac formula, well under 1°).
export function sunElevation(date, lat, lon) {
  const d = (date.getTime() - J2000_MS) / 86400000;
  const g = (357.529 + 0.98560028 * d) * RAD;
  const L = (280.459 + 0.98564736 * d + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * RAD;
  const e = (23.439 - 0.00000036 * d) * RAD;
  const dec = Math.asin(Math.sin(e) * Math.sin(L));
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L));
  const gmst = (18.697374558 + 24.06570982441908 * d) % 24;
  const ha = (gmst * 15 + lon) * RAD - ra;
  const elev = Math.sin(lat * RAD) * Math.sin(dec) + Math.cos(lat * RAD) * Math.cos(dec) * Math.cos(ha);
  return Math.asin(elev) / RAD;
}

// 0 = day, 1 = night; in between through sunset/sunrise (sun 6° above to 6° below the horizon).
export const nightness = (elevation) => Math.min(1, Math.max(0, (6 - elevation) / 12));

const ctx = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;

// Any CSS colour string -> [r, g, b, a] (0-255, a 0-1), or null if it isn't a colour.
function parse(str) {
  if (!ctx || typeof str !== "string") return null;
  ctx.fillStyle = "#010203";
  ctx.fillStyle = str;
  const v = ctx.fillStyle;
  if (v === "#010203" && str.toLowerCase() !== "#010203") return null;
  if (v[0] === "#") return [1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16)).concat(1);
  const m = v.match(/[\d.]+/g).map(Number);
  return [m[0], m[1], m[2], m[3] ?? 1];
}

// Night palette (after Google Maps' night mode): dark teal land, near-black water, grey roads
// that get lighter with importance, soft light labels.
const NIGHT = {
  land: "#1d3034", landuse: "#22363a", park: "#1f3a32", water: "#0b1416", building: "#273b3f",
  casing: "#16252a", minor: "#3a484c", mid: "#47575b", major: "#5f7073", runway: "#34444a",
  boundary: "#6b7b7b", place: "#d6dcd8", roadLabel: "#a9b4b2", waterLabel: "#6f8a96",
  poi: "#b8c2bf", halo: "#142225",
};

// Which night colour a base-map layer's property gets, from the layer's id (Liberty style).
function nightColour(id, prop) {
  if (prop === "text-halo-color" || prop === "icon-halo-color") return NIGHT.halo;
  if (prop === "text-color") {
    if (id.startsWith("label_")) return NIGHT.place;
    if (id.startsWith("highway") || id.startsWith("road_shield")) return NIGHT.roadLabel;
    if (id.startsWith("water")) return NIGHT.waterLabel;
    return NIGHT.poi;
  }
  if (prop === "icon-color") return null;
  if (id === "background") return NIGHT.land;
  if (/park|wood|grass|wetland|pitch|cemetery|track/.test(id) && !id.includes("service")) return NIGHT.park;
  if (id === "water" || id.startsWith("waterway")) return NIGHT.water;
  if (id.startsWith("building")) return NIGHT.building;
  if (id.startsWith("boundary")) return NIGHT.boundary;
  if (/runway|taxiway/.test(id)) return NIGHT.runway;
  if (/landuse|landcover|aeroway/.test(id)) return NIGHT.landuse;
  if (id.includes("casing")) return NIGHT.casing;
  if (/motorway|trunk_primary/.test(id)) return NIGHT.major;
  if (/secondary_tertiary/.test(id)) return NIGHT.mid;
  if (/road|tunnel|bridge/.test(id)) return NIGHT.minor;
  return NIGHT.landuse;
}

// Blend every colour inside a paint value (plain colour or zoom expression) towards `target`.
function recolour(value, target, t) {
  if (Array.isArray(value)) return value.map((v) => recolour(v, target, t));
  const c = parse(value);
  if (!c) return value;
  const mix = c.slice(0, 3).map((v, i) => Math.round(v + (target[i] - v) * t));
  return `rgba(${mix.join(",")},${c[3]})`;
}

const COLOUR_PROPS = [
  "background-color", "fill-color", "fill-outline-color", "line-color", "fill-extrusion-color",
  "circle-color", "circle-stroke-color", "text-color", "text-halo-color", "icon-color", "icon-halo-color",
];

// Day paint values, read once (before any recolouring) so night can always be undone exactly.
const originals = new WeakMap();

export function applyNight(map, t, duration) {
  if (!originals.has(map)) {
    const saved = [];
    for (const layer of map.getStyle().layers) {
      if (layer.id.startsWith("cr-")) continue;
      // Only this layer type's own properties: MapLibre throws on the others.
      const prefixes = layer.type === "symbol" ? ["text-", "icon-"] : [`${layer.type}-`];
      const own = [...COLOUR_PROPS, "raster-brightness-max"].filter((prop) =>
        prefixes.some((p) => prop.startsWith(p) && !prop.slice(p.length).startsWith("extrusion")),
      );
      for (const prop of own) {
        const unset = prop === "raster-brightness-max" ? 1 : undefined;
        const v = map.getPaintProperty(layer.id, prop) ?? unset;
        if (v !== undefined) saved.push([layer.id, prop, v]);
      }
    }
    originals.set(map, saved);
  }
  for (const [id, prop, day] of originals.get(map)) {
    map.setPaintProperty(id, `${prop}-transition`, { duration, delay: 0 });
    if (prop === "raster-brightness-max") {
      map.setPaintProperty(id, prop, day * (1 - 0.75 * t));
      continue;
    }
    const target = nightColour(id, prop);
    if (target) map.setPaintProperty(id, prop, recolour(day, parse(target), t));
  }
}
