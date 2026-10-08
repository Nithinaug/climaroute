// One backend per city: VITE_API_URLS="https://bengaluru-api,https://delhi-api"
export const API_URLS = (import.meta.env.VITE_API_URLS ?? import.meta.env.VITE_API_URL ?? "").split(",");
let apiUrl = API_URLS[0];
export const setCityApi = (url) => {
  apiUrl = url;
};

async function request(path, options) {
  let res;
  try {
    res = await fetch(`${apiUrl}${path}`, options);
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(body.error?.message ?? "Something went wrong. Please try again.");
    err.code = body.error?.code ?? "INTERNAL";
    throw err;
  }
  return body;
}

export const getArea = (url) =>
  fetch(`${url}/area`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText))));

export const getReports = () => request("/reports");

export const postReport = (point) =>
  request("/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(point),
  });

export const getRoute = (params) =>
  request("/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });

export const searchPlaces = (text) => request(`/search?q=${encodeURIComponent(text)}`);

export const getPlaceName = ({ lat, lon }) => request(`/place?lat=${lat}&lon=${lon}`);

export const getBestTime = (params) =>
  request("/best-time", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
