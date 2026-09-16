/* GSAP-driven motion helpers shared by every dashboard page.
   Everything degrades gracefully: with prefers-reduced-motion, or if GSAP
   failed to load, each helper just renders the final state instantly. */
window.Motion = (() => {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const hasGsap = typeof window.gsap !== "undefined";
  const animate = hasGsap && !reduced;
  const EASE = "power3.out";

  if (!animate) document.documentElement.classList.remove("motion");

  /* Cards stagger in on page load (anything tagged data-reveal). */
  function reveal(scope = document) {
    const items = [...scope.querySelectorAll("[data-reveal]")].filter((el) => !el.dataset.revealed);
    items.forEach((el) => { el.dataset.revealed = "1"; });
    if (!items.length) return;
    if (!animate) { items.forEach((el) => { el.style.opacity = "1"; el.style.animation = "none"; }); return; }
    gsap.fromTo(items,
      { opacity: 0, y: 14 },
      { opacity: 1, y: 0, duration: 0.7, ease: EASE, stagger: 0.06, overwrite: true,
        onStart() { items.forEach((el) => { el.style.animation = "none"; }); },
        clearProps: "transform" });
  }

  /* Number rolls up from its previous value. */
  function countUp(el, value, options = {}) {
    const format = options.format || ((v) => Math.round(v).toLocaleString());
    const from = Number(el.dataset.countValue || 0);
    el.dataset.countValue = String(value);
    if (!animate || from === value) { el.textContent = format(value); return; }
    const state = { v: from };
    gsap.to(state, {
      v: value, duration: options.duration || 1, ease: "power2.out", overwrite: true,
      onUpdate: () => { el.textContent = format(state.v); },
    });
  }

  /* Catmull-Rom → cubic bezier so sparklines and area charts read as smooth curves. */
  function smoothPath(points) {
    if (points.length < 2) return "";
    let d = `M${points[0][0].toFixed(1)},${points[0][1].toFixed(1)}`;
    for (let i = 0; i < points.length - 1; i += 1) {
      const p0 = points[i - 1] || points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] || p2;
      const c1x = p1[0] + (p2[0] - p0[0]) / 6;
      const c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6;
      const c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
    }
    return d;
  }

  function gradientDefs(id, color) {
    return `<defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity="0.32"></stop>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"></stop>
    </linearGradient></defs>`;
  }

  /* Full-bleed KPI sparkline: line draws itself, fill fades in behind it. */
  function sparkline(svg, values, options = {}) {
    if (!values || values.length < 2) { svg.innerHTML = ""; return; }
    const rect = svg.getBoundingClientRect();
    const W = Math.max(rect.width, 80);
    const H = Math.max(rect.height, 32);
    const pad = 3;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("preserveAspectRatio", "none");
    const max = Math.max(...values, 1);
    const stepX = W / (values.length - 1);
    const points = values.map((v, i) => [i * stepX, H - pad - (v / max) * (H - pad * 2)]);
    const line = smoothPath(points);
    const gradId = `${svg.id || "spark"}-grad`;
    const color = options.color || getComputedStyle(svg).getPropertyValue("--kpi-color").trim() || "currentColor";
    svg.innerHTML = `${gradientDefs(gradId, color)}
      <path class="spark-fill" d="${line} L${W},${H} L0,${H} Z" style="fill:url(#${gradId})"></path>
      <path class="spark-line" d="${line}"></path>`;
    const lineEl = svg.querySelector(".spark-line");
    const fillEl = svg.querySelector(".spark-fill");
    if (!animate) return;
    const length = lineEl.getTotalLength();
    gsap.set(lineEl, { strokeDasharray: length, strokeDashoffset: length });
    gsap.set(fillEl, { opacity: 0 });
    gsap.to(lineEl, { strokeDashoffset: 0, duration: 1.3, ease: "power2.inOut", delay: options.delay || 0.2 });
    gsap.to(fillEl, { opacity: 1, duration: 0.9, delay: (options.delay || 0.2) + 0.5 });
  }

  function escapeText(value) {
    return String(value == null ? "" : value).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  }

  const polar = (cx, cy, r, a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const f2 = (n) => n.toFixed(2);

  /* Annular sector with rounded corners. Angles in radians, increasing
     clockwise (SVG y-down), r0 inner radius, r1 outer radius. */
  function sectorPath(cx, cy, r0, r1, a0, a1, corner) {
    const span = a1 - a0;
    if (span <= 0.0005) return "";
    const c = Math.max(0, Math.min(corner, (r1 - r0) / 2, (span * r0) / 2.2));
    const dO = c / r1;
    const dI = c / r0;
    const large = span - 2 * dO > Math.PI ? 1 : 0;
    const P = (r, a) => polar(cx, cy, r, a).map(f2).join(",");
    return [
      `M${P(r1, a0 + dO)}`,
      `A${f2(r1)},${f2(r1)} 0 ${large} 1 ${P(r1, a1 - dO)}`,
      `A${f2(c)},${f2(c)} 0 0 1 ${P(r1 - c, a1)}`,
      `L${P(r0 + c, a1)}`,
      `A${f2(c)},${f2(c)} 0 0 1 ${P(r0, a1 - dI)}`,
      `A${f2(r0)},${f2(r0)} 0 ${large} 0 ${P(r0, a0 + dI)}`,
      `A${f2(c)},${f2(c)} 0 0 1 ${P(r0 + c, a0)}`,
      `L${P(r1 - c, a0)}`,
      `A${f2(c)},${f2(c)} 0 0 1 ${P(r1, a0 + dO)}`,
      "Z",
    ].join(" ");
  }

  /* Stacked half-radial chart (shadcn "Radial Chart - Stacked"): sections
     stack clockwise from the left across a 180° arc, each with 5px corner
     rounding and a 2px gap, the total sits at the base of the arc, and the
     whole stack sweeps in on load. `segments` = [{label, value, color}]. */
  function radial(svg, segments, options = {}) {
    const W = 240;
    const cx = 120;
    const cy = 118;
    const R = options.outer || 110;
    const r = options.inner || 80;
    const corner = options.corner ?? 5;
    const gap = 2 / ((R + r) / 2);
    const START = Math.PI;
    const total = segments.reduce((sum, s) => sum + s.value, 0);
    svg.setAttribute("viewBox", `0 0 ${W} ${cy + 24}`);
    svg.innerHTML = `
      <path class="radial-track" d="${sectorPath(cx, cy, r, R, START, 2 * Math.PI, corner)}"></path>
      <g class="radial-arcs">${segments.map((s, i) =>
        `<path data-index="${i}" fill="${s.color}" d=""><title>${escapeText(s.label)}: ${escapeText(s.value)}</title></path>`).join("")}</g>
      <text x="${cx}" y="${cy - 14}" text-anchor="middle" class="radial-total" data-role="total">${total.toLocaleString()}</text>
      <text x="${cx}" y="${cy + 8}" text-anchor="middle" class="radial-label">${escapeText(options.label || "")}</text>`;
    if (!total) return;

    const paths = [...svg.querySelectorAll(".radial-arcs path")];
    let acc = 0;
    const bounds = segments.map((s, i) => {
      const a0 = START + (acc / total) * Math.PI + (i > 0 ? gap / 2 : 0);
      acc += s.value;
      const a1 = START + (acc / total) * Math.PI - (i < segments.length - 1 ? gap / 2 : 0);
      return [a0, a1];
    });
    const draw = (t) => {
      const reached = START + Math.PI * t;
      bounds.forEach(([a0, a1], i) => {
        paths[i].setAttribute("d", a0 >= reached ? "" : sectorPath(cx, cy, r, R, a0, Math.min(a1, reached), corner));
      });
    };
    if (!animate) { draw(1); return; }
    const state = { t: 0 };
    gsap.to(state, { t: 1, duration: 1.2, ease: "power2.out", delay: options.delay || 0.15, onUpdate: () => draw(state.t) });
    gsap.fromTo(svg, { scale: 0.92, opacity: 0, transformOrigin: "50% 100%" }, { scale: 1, opacity: 1, duration: 0.7, ease: EASE });
  }

  /* Vertical bars grow from the baseline; call again with new values to tween. */
  function growBars(svg, options = {}) {
    const rects = [...svg.querySelectorAll("rect[data-y]")];
    if (!rects.length) return;
    if (!animate) {
      rects.forEach((rect) => { rect.setAttribute("y", rect.dataset.y); rect.setAttribute("height", rect.dataset.h); });
      return;
    }
    rects.forEach((rect, index) => {
      gsap.to(rect, {
        attr: { y: Number(rect.dataset.y), height: Number(rect.dataset.h) },
        duration: options.duration || 0.8, ease: EASE, delay: (options.stagger ?? 0.03) * index, overwrite: true,
      });
    });
  }

  /* Tween a numeric array in place (used to morph the area chart between series). */
  function tweenArray(current, target, onUpdate, options = {}) {
    if (!animate) { target.forEach((v, i) => { current[i] = v; }); onUpdate(); return; }
    gsap.to(current, { endArray: target, duration: options.duration || 0.8, ease: "power2.inOut", onUpdate, overwrite: true });
  }

  /* Horizontal progress fills grow to their target width. */
  function fillBars(scope = document) {
    const fills = [...scope.querySelectorAll("[data-width]")];
    fills.forEach((el, index) => {
      const target = `${el.dataset.width}%`;
      if (!animate) { el.style.width = target; return; }
      gsap.fromTo(el, { width: el.style.width || "0%" }, { width: target, duration: 0.9, ease: EASE, delay: 0.1 + index * 0.08, overwrite: true });
    });
  }

  /* Rows fade/slide in when a list re-renders. */
  function rows(container) {
    const items = [...container.children];
    if (!animate || !items.length) return;
    gsap.fromTo(items, { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.4, ease: EASE, stagger: 0.025, clearProps: "all" });
  }

  function pulse(el) {
    if (!animate || !el) return;
    gsap.fromTo(el, { scale: 0.96 }, { scale: 1, duration: 0.5, ease: "elastic.out(1, 0.5)", clearProps: "transform" });
  }

  return { animate, reveal, countUp, sparkline, radial, growBars, tweenArray, fillBars, rows, pulse, smoothPath, gradientDefs };
})();

document.addEventListener("DOMContentLoaded", () => window.Motion.reveal());
