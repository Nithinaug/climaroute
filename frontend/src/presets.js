// One-tap demo trips inside the covered area.
export const PRESETS = [
  {
    label: "Afternoon walk, 5th → 4th Block",
    origin: { lat: 12.93, lon: 77.617 },
    destination: { lat: 12.942, lon: 77.632 },
    mode: "summer",
    transport: "walk",
    time: "16:00",
  },
  {
    label: "Heavy rain walk past Sony World",
    origin: { lat: 12.93, lon: 77.617 },
    destination: { lat: 12.942, lon: 77.632 },
    mode: "monsoon",
    transport: "walk",
    rainScenario: "heavy",
  },
  {
    label: "Heavy rain scooter ride",
    origin: { lat: 12.93, lon: 77.617 },
    destination: { lat: 12.942, lon: 77.632 },
    mode: "monsoon",
    transport: "two_wheeler",
    rainScenario: "heavy",
  },
];
