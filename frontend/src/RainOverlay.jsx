import { useEffect, useRef } from "react";

// Rain falling over the map, as heavy as the rain the route was planned for: none when dry,
// a light drizzle at a few mm/h, a dense slanted downpour at 50 mm/h. Taps go through to the map.
// Not drawn for people who ask for reduced motion.
export default function RainOverlay({ mmPerHour }) {
  const canvas = useRef(null);

  useEffect(() => {
    const el = canvas.current;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!el || !mmPerHour || still) return;
    const ctx = el.getContext("2d");
    const heavy = Math.min(1, mmPerHour / 50); // 0..1
    const count = Math.round(60 + 340 * heavy);
    const slant = 0.15 + 0.25 * heavy; // sideways drift per unit fall
    let drops = [];
    let frame;

    const resize = () => {
      el.width = el.clientWidth * devicePixelRatio;
      el.height = el.clientHeight * devicePixelRatio;
      drops = Array.from({ length: count }, () => ({
        x: Math.random() * el.width * 1.3,
        y: Math.random() * el.height,
        len: (8 + Math.random() * 14) * devicePixelRatio * (0.6 + heavy),
        speed: (9 + Math.random() * 8) * devicePixelRatio * (0.7 + heavy * 0.6),
      }));
    };
    const draw = () => {
      ctx.clearRect(0, 0, el.width, el.height);
      ctx.strokeStyle = `rgba(174, 194, 224, ${0.25 + 0.3 * heavy})`;
      ctx.lineWidth = devicePixelRatio;
      ctx.beginPath();
      for (const d of drops) {
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x - d.len * slant, d.y + d.len);
        d.y += d.speed;
        d.x -= d.speed * slant;
        if (d.y > el.height || d.x < 0) {
          d.y = -d.len;
          d.x = Math.random() * el.width * 1.3;
        }
      }
      ctx.stroke();
      frame = requestAnimationFrame(draw);
    };

    resize();
    draw();
    window.addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      ctx.clearRect(0, 0, el.width, el.height);
    };
  }, [mmPerHour]);

  return <canvas ref={canvas} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" />;
}
