const API_URL = import.meta.env.VITE_API_URL ?? "";

async function request(path, options) {
  let res;
  try {
    res = await fetch(`${API_URL}${path}`, options);
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

export const getArea = () => request("/area");

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
