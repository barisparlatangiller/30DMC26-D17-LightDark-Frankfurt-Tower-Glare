/* Light & Dark · Frankfurt's towers — #30DayMapChallenge 2026 · Day 17 (builds on Day 5 · Shadows) */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const fmt = (v, d = 0) => v == null || Number.isNaN(v) ? "–" : Number(v).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const dark = document.documentElement.dataset.theme === "dark";
  const C = { tower: dark ? "#6e6a64" : "#8a857d", bld: dark ? "#3b3936" : "#e7e2da", shade: dark ? "rgba(52,78,190,0.5)" : "rgba(28,32,70,0.42)",
              roofShade: dark ? "#2a3c8f" : "#26306e", roof: "#3b4cca" };
  const GLASS = { 4: "#1c5c96", 3: "#4284b8", 2: "#8aa7bc", 1: "#a39888", 9: "#9a958d" };
  const GLASSN = { 4: "A1 · full glass, mirror-like", 3: "A2 · full glass, lighter", 2: "B · mixed (bands, frames)", 1: "C · mostly stone / metal", 9: "U · not verified" };
  const CL2L = { A1: 4, A2: 3, B: 2, C: 1, U: 9 };
  const GLARE = dark ? { 1: "#7a4a22", 2: "#d9741c", 3: "#f59a33", 4: "#ffc255", 9: "#8f8579" } : { 1: "#f6d3a4", 2: "#f5a04a", 3: "#ec7a1c", 4: "#d4520a", 9: "#c8bcae" };
  const LOSS = ["#d0e2f2", "#96c0e4", "#5492cd", "#265ea6", "#102c68"];
  const GH = ["#fdd6a0", "#fbb060", "#f58228", "#de580e", "#aa3205"];

  const st = { m: 6, t: 0, mode: "both", view: "3d", sel: null };
  let map, S, T, GL, IDX = {}, GIDX = {}, playing = null, LI = null, GI = null, popup;

  const j = (u) => fetch(u, { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); });
  const mm = (m) => String(m).padStart(2, "0");
  Promise.all([j("data/stats.json"), j("data/towers.geojson"), j("data/glass.geojson"), j("data/sunloss/index.json").catch(() => null), j("data/glarehours/index.json").catch(() => null)])
    .then(([s, t, g, li, gi]) => { S = s; T = t; GL = g; LI = li; GI = gi; initPanel(); initMap(); })
    .catch((e) => { $("#loading").textContent = "Could not load the data: " + e.message; });

  const index = (m) => Promise.all([
    IDX[m] ? IDX[m] : j(`data/shadows/${mm(m)}/index.json`).then((x) => (IDX[m] = x)),
    GIDX[m] ? GIDX[m] : j(`data/glare/${mm(m)}/index.json`).then((x) => (GIDX[m] = x)).catch(() => (GIDX[m] = { hours: [] }))]);
  const showShade = () => st.mode === "both" || st.mode === "dark";
  const showGlare = () => st.mode === "both" || st.mode === "light";

  // ---------------------------------------------------------------- vector layers per month
  function monthSources(m) {
    if (!map || !map.getLayer("b3")) return;
    for (const id of ["shg", "shr", "shr2", "glg", "glu", "glr", "glr2"]) if (map.getLayer(id)) map.removeLayer(id);
    for (const id of ["sh", "gl"]) if (map.getSource(id)) map.removeSource(id);
    const v = S.build || 1;
    map.addSource("sh", { type: "vector", url: "pmtiles://" + new URL(`data/shadows/${mm(m)}.pmtiles?v=${v}`, location.href).href, minzoom: 13, maxzoom: 16 });
    map.addSource("gl", { type: "vector", url: "pmtiles://" + new URL(`data/glare/${mm(m)}.pmtiles?v=${v}`, location.href).href, minzoom: 13, maxzoom: 16 });
    map.addLayer({ id: "shg", type: "fill", source: "sh", "source-layer": "s", filter: hourFilter("g"), paint: { "fill-color": C.shade, "fill-antialias": false } }, "b3");
    const gcol = ["match", ["get", "lev"], 1, GLARE[1], 2, GLARE[2], 3, GLARE[3], 4, GLARE[4], GLARE[9]];
    map.addLayer({ id: "glg", type: "fill", source: "gl", "source-layer": "r", filter: ghourFilter("g", false),
      paint: { "fill-color": gcol, "fill-opacity": ["match", ["get", "lev"], 1, 0.55, 2, 0.75, 3, 0.85, 0.92], "fill-antialias": false } }, "b3");
    map.addLayer({ id: "glu", type: "fill", source: "gl", "source-layer": "r", filter: ghourFilter("g", true),
      paint: { "fill-color": GLARE[9], "fill-opacity": 0.45, "fill-antialias": false } }, "b3");
    map.addLayer({ id: "shr", type: "fill-extrusion", source: "sh", "source-layer": "s", filter: hourFilter("r"),
      paint: { "fill-extrusion-color": C.roofShade, "fill-extrusion-base": ["get", "h"], "fill-extrusion-height": ["+", ["get", "h"], 0.5], "fill-extrusion-opacity": 0.75 } });
    map.addLayer({ id: "shr2", type: "fill", source: "sh", "source-layer": "s", filter: hourFilter("r"), layout: { visibility: "none" }, paint: { "fill-color": C.roof, "fill-opacity": 0.55 } });
    map.addLayer({ id: "glr", type: "fill-extrusion", source: "gl", "source-layer": "r", filter: ghourFilter("r", null),
      paint: { "fill-extrusion-color": gcol, "fill-extrusion-base": ["+", ["get", "h"], 0.5], "fill-extrusion-height": ["+", ["get", "h"], 1.2], "fill-extrusion-opacity": 0.9 } });
    map.addLayer({ id: "glr2", type: "fill", source: "gl", "source-layer": "r", filter: ghourFilter("r", null), layout: { visibility: "none" }, paint: { "fill-color": gcol, "fill-opacity": 0.85 } });
    for (const id of ["gx3", "gxl", "gxf", "twl", "twf"]) if (map.getLayer(id)) map.moveLayer(id);
    applyView(true);
  }
  function hourFilter(k) {
    const h = curHour();
    return ["all", ["==", ["get", "k"], k], ["==", ["get", "hr"], h ? +h.f : -1]];
  }
  function ghourFilter(k, unk) {
    const h = curHour();
    const f = ["all", ["==", ["get", "k"], k], ["==", ["get", "hr"], h ? +h.f : -1]];
    if (unk === true) f.push(["==", ["get", "lev"], 9]);
    if (unk === false) f.push(["<", ["get", "lev"], 9]);
    return f;
  }
  const curHour = () => IDX[st.m] && IDX[st.m].hours[st.t];
  const gHour = () => { const h = curHour(); return h && (GIDX[st.m]?.hours || []).find((x) => x.f === h.f); };

  // ---------------------------------------------------------------- map
  function initMap() {
    const protocol = new pmtiles.Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
    map = new maplibregl.Map({
      container: "map", hash: true, maxPitch: 75, attributionControl: false,
      center: [8.6715, 50.1112], zoom: 14.7, pitch: 58, bearing: -25,
      style: `https://basemaps.cartocdn.com/gl/${dark ? "dark-matter" : "positron"}-gl-style/style.json`
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "3D buildings © HVBG Hessen (dl-de/zero-2-0) · names © OpenStreetMap contributors · façade classes: own inventory from Wikipedia (CC BY-SA)" }));
    popup = new maplibregl.Popup({ closeButton: true, maxWidth: "340px", offset: 8 });
    let ready = false;
    const setup = () => {
      if (ready || !(map.style && map.style._loaded)) return;
      ready = true;
      const first = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
      if (LI) {
        map.addSource("loss", { type: "image", url: `data/sunloss/${mm(st.m)}.png`, coordinates: LI.corners });
        map.addLayer({ id: "loss", type: "raster", source: "loss", layout: { visibility: "none" }, paint: { "raster-opacity": 0.9, "raster-fade-duration": 0, "raster-resampling": "nearest" } }, first);
      }
      if (GI) {
        map.addSource("gh", { type: "image", url: `data/glarehours/${mm(st.m)}.png`, coordinates: GI.corners });
        map.addLayer({ id: "gh", type: "raster", source: "gh", layout: { visibility: "none" }, paint: { "raster-opacity": 0.95, "raster-fade-duration": 0, "raster-resampling": "nearest" } }, first);
      }
      map.addSource("b", { type: "vector", url: "pmtiles://" + new URL(`data/buildings.pmtiles?v=${S.build || 1}`, location.href).href });
      map.addLayer({ id: "b3", type: "fill-extrusion", source: "b", "source-layer": "b", minzoom: 12,
        paint: { "fill-extrusion-color": ["case", [">", ["coalesce", ["get", "g"], 0], 0], ["match", ["get", "g"], 4, GLASS[4], 3, GLASS[3], 2, GLASS[2], 1, GLASS[1], GLASS[9]],
                                          ["==", ["get", "t"], 1], C.tower, C.bld],
                 "fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 0, "fill-extrusion-opacity": 0.93, "fill-extrusion-vertical-gradient": true } });
      map.addSource("gx", { type: "geojson", data: GL, promoteId: "i" });
      map.addLayer({ id: "gxf", type: "fill", source: "gx", paint: { "fill-color": ["match", ["get", "c"], "A1", GLASS[4], "A2", GLASS[3], "B", GLASS[2], "C", GLASS[1], GLASS[9]], "fill-opacity": 0 } });
      map.addLayer({ id: "gxl", type: "line", source: "gx", paint: { "line-color": dark ? "#ffd27a" : "#1f1d1a", "line-width": ["case", ["boolean", ["feature-state", "sel"], false], 3, 0] } });
      map.addSource("tw", { type: "geojson", data: T, promoteId: "i" });
      map.addLayer({ id: "twl", type: "line", source: "tw", paint: { "line-color": dark ? "#fff" : "#1f1d1a", "line-width": ["case", ["boolean", ["feature-state", "sel"], false], 3, 0], "line-opacity": 0.9 } });
      map.addLayer({ id: "twf", type: "fill", source: "tw", paint: { "fill-color": "#000", "fill-opacity": 0 } });
      map.on("click", (e) => {
        const g = map.queryRenderedFeatures(e.point, { layers: ["gxf"] });
        if (g.length) return selectGlass(g[0].properties.i, e.lngLat);
        const t = map.queryRenderedFeatures(e.point, { layers: ["twf"] });
        if (t.length) selectTower(t[0].properties.i, e.lngLat);
      });
      for (const id of ["twf", "gxf"]) {
        map.on("mouseenter", id, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", id, () => { map.getCanvas().style.cursor = ""; });
      }
      $("#loading").classList.add("done");
      try { if (!localStorage.getItem("d17intro")) $("#intro").hidden = false; } catch (e) { $("#intro").hidden = false; }
      applyView(); loadMonth(st.m, true);
    };
    map.on("load", setup);
    map.on("styledata", () => setTimeout(setup, 0));
    const poll = setInterval(() => { setup(); if (ready) clearInterval(poll); }, 300);
    window._map = map;
  }

  function vis(id, on) { if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none"); }
  function applyView(noEase) {
    if (!map || !map.getLayer("b3")) return;
    const is3 = st.view === "3d", mom = ["both", "dark", "light"].includes(st.mode);
    vis("b3", is3);
    vis("shg", mom && showShade()); vis("shr", mom && showShade() && is3); vis("shr2", mom && showShade() && !is3);
    vis("glg", mom && showGlare()); vis("glu", mom && showGlare() && $("#unkChk").checked); vis("glr", mom && showGlare() && is3); vis("glr2", mom && showGlare() && !is3);
    vis("loss", st.mode === "loss"); vis("gh", st.mode === "glare");
    map.setPaintProperty("gxf", "fill-opacity", is3 ? 0 : 0.9);
    map.setPaintProperty("twf", "fill-color", C.tower); map.setPaintProperty("twf", "fill-opacity", is3 ? 0 : 0.7);
    if (!noEase) map.easeTo({ pitch: is3 ? 58 : 0, duration: 600 });
  }

  // ---------------------------------------------------------------- time
  function loadMonth(m, keepNoon) {
    return index(m).then(([ix]) => {
      st.m = m;
      const n = ix.hours.length;
      if (keepNoon || st.t >= n) {
        const k = ix.hours.findIndex((x) => x.t >= "18:00");
        st.t = Math.max(0, k >= 0 ? k : Math.floor(n / 2));
      }
      $("#time").max = n - 1;
      if (map && map.getSource("loss")) map.getSource("loss").updateImage({ url: `data/sunloss/${mm(m)}.png`, coordinates: LI.corners });
      if (map && map.getSource("gh")) map.getSource("gh").updateImage({ url: `data/glarehours/${mm(m)}.png`, coordinates: GI.corners });
      monthSources(m); showStep(); renderPanel();
    });
  }
  function showStep() {
    const ix = IDX[st.m]; if (!ix) return;
    if (map && map.getLayer("shg")) {
      map.setFilter("shg", hourFilter("g")); map.setFilter("shr", hourFilter("r")); map.setFilter("shr2", hourFilter("r"));
      map.setFilter("glg", ghourFilter("g", false)); map.setFilter("glu", ghourFilter("g", true));
      map.setFilter("glr", ghourFilter("r", null)); map.setFilter("glr2", ghourFilter("r", null));
    }
    const H = ix.hours[st.t] || { t: "–", az: 180, alt: 0 };
    $("#time").value = st.t; $("#timeO").textContent = H.t;
    const day = ["loss", "glare"].includes(st.mode);
    $("#clockDay").textContent = `21 ${MON[st.m - 1]}`; $("#clockTime").textContent = day ? "all day" : H.t;
    sunDial([H.az, H.alt]);
    const n = ix.hours.length;
    $("#ticks").innerHTML = [0, Math.floor((n - 1) / 2), n - 1].map((k) => `<span>${ix.hours[k].t}</span>`).join("");
    dayChart(); lede();
  }
  function sunDial([az, alt]) {
    const r = 15, len = r * Math.cos(alt * Math.PI / 180);
    const sx = 20 + Math.sin(az * Math.PI / 180) * len, sy = 20 - Math.cos(az * Math.PI / 180) * len;
    $("#sunDial").innerHTML = `<svg viewBox="0 0 40 40" width="40" height="40"><circle cx="20" cy="20" r="${r}" fill="none" stroke="var(--line)"/><text x="20" y="7" text-anchor="middle" font-size="6" fill="var(--ink-3)">N</text>
      <line x1="20" y1="20" x2="${20 - (sx - 20) * 0.9}" y2="${20 - (sy - 20) * 0.9}" stroke="var(--ink-2)" stroke-width="2" stroke-linecap="round"/>
      <circle cx="${sx}" cy="${sy}" r="4" fill="#f5b014"/></svg><span class="mono">${fmt(alt, 0)}°</span>`;
  }
  function play() {
    $("#playBtn").classList.add("on"); $("#playBtn").textContent = "❚❚ Pause";
    playing = setInterval(() => { const n = IDX[st.m].hours.length; st.t = (st.t + 1) % n; showStep(); }, 800);
  }
  function stop() { if (!playing) return; clearInterval(playing); playing = null; $("#playBtn").classList.remove("on"); $("#playBtn").textContent = "▶ Play the day"; }

  // ---------------------------------------------------------------- panel
  function initPanel() {
    $("#monthSeg").innerHTML = MON.map((x, i) => `<button data-m="${i + 1}">${x}</button>`).join("");
    $$("#monthSeg button").forEach((b) => b.onclick = () => { stop(); loadMonth(+b.dataset.m, false); });
    $("#time").oninput = (e) => { stop(); st.t = +e.target.value; showStep(); };
    $$("#modeSeg button, #daySeg button").forEach((b) => b.onclick = () => { st.mode = b.dataset.m; stop(); applyView(); renderPanel(); showStep(); });
    $$("#viewSeg button").forEach((b) => b.onclick = () => { st.view = b.dataset.v; $$("#viewSeg button").forEach((x) => x.classList.toggle("on", x === b)); applyView(); });
    $("#unkChk").onchange = () => applyView(true);
    $("#themeBtn").textContent = dark ? "☀ Light map" : "☾ Dark map";
    $("#themeBtn").onclick = () => { const u = new URL(location.href); u.searchParams.set("theme", dark ? "light" : "dark"); location.href = u.toString(); };
    $("#playBtn").onclick = () => playing ? stop() : (["loss", "glare"].includes(st.mode) && (st.mode = "both", applyView(), renderPanel()), play());
    $("#introGo").onclick = () => { $("#intro").hidden = true; try { localStorage.setItem("d17intro", "1"); } catch (e) { /* ignore */ } };
    $("#dayChart").onclick = (e) => {
      const ix = IDX[st.m]; if (!ix) return;
      const d = S.shadows.days[mm(st.m)];
      const r = e.currentTarget.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * 330;
      const k = Math.max(0, Math.min(d.times.length - 1, Math.round((x - 42) / (258 / Math.max(1, d.times.length - 1)))));
      const tt = d.times[k].slice(0, 2);
      let best = 0; ix.hours.forEach((h, i) => { if (Math.abs(+h.f - +tt) < Math.abs(+ix.hours[best].f - +tt)) best = i; });
      st.t = best; stop();
      if (["loss", "glare"].includes(st.mode)) { st.mode = "both"; applyView(); renderPanel(); }
      showStep();
    };
    const c = S.casters || {}, f = S.facades || {};
    $("#dq").innerHTML = `${fmt(c.parts)} LoD2 building parts of ${fmt(c.buildings)} buildings are 30 m or taller and cast the shadows. `
      + `For reflections, ${fmt(f.inventory)} towers of 58 m and more were classed façade by façade (Wikipedia text and photos); ${fmt(f.matched)} of them are in the LoD2 model (${fmt(f.parts)} parts). `
      + (f.unmatched && f.unmatched.length ? `Not yet in LoD2 (mostly new towers): ${esc(f.unmatched.join(", "))}. ` : "")
      + `The other ~${fmt(f.towers_without_inventory)} buildings of 30–58 m have no façade class yet and reflect nothing in this model.`;
    $("#downloads").innerHTML = `<span>Download:</span><a href="data/glass.geojson">glass towers (GeoJSON)</a><a href="data/towers.geojson">all towers</a><a href="data/stats.json">stats.json</a><a href="https://github.com/barisparlatangiller/30DMC26-D17-LightDark-Frankfurt-Tower-Glare/raw/main/data/frankfurt_facade_inventory_v2.xlsx">façade inventory (xlsx)</a>`;
    renderPanel();
  }
  function renderPanel() {
    $$("#monthSeg button").forEach((b) => b.classList.toggle("on", +b.dataset.m === st.m));
    $$("#modeSeg button, #daySeg button").forEach((b) => b.classList.toggle("on", b.dataset.m === st.mode));
    $("#timeBlock").style.display = ["loss", "glare"].includes(st.mode) ? "none" : "";
    $("#unkRow").style.display = showGlare() ? "" : "none";
    const d = (S.shadows && S.shadows.days || {})[mm(st.m)];
    $("#dayHint").textContent = d ? `Sun above 5° from ${d.first} to ${d.last}, highest at ${fmt(d.max_alt)}°. Map in hourly steps; day totals from 30-minute steps.` : "";
    $("#rankMonth").textContent = `21 ${MON[st.m - 1]}`;
    const shadowRank = ["dark", "loss"].includes(st.mode);
    $("#rankTitle").textContent = shadowRank ? "Biggest shadow casters" : "Brightest mirrors";
    $("#rankHint").textContent = shadowRank ? "Shaded area × time over the whole day (hectare-hours), ground and roofs together."
      : "Area lit by each tower's reflected sunlight × time over the whole day (hectare-hours), weighted by the façade class.";
    let top = [];
    if (shadowRank) {
      const rows = T.features.map((f) => { const v = (f.properties.m || {})[mm(st.m)] || [0, 0, 0]; return { p: f.properties, v: v[0] + v[1], k: `${fmt(f.properties.h)} m · ${fmt(v[2])} roofs shaded`, col: "var(--shade)", src: "tw" }; })
        .filter((x) => x.v > 0).sort((a, b) => b.v - a.v);
      const seen = new Set();
      for (const r of rows) { const key = r.p.n || r.p.i; if (seen.has(key)) continue; seen.add(key); top.push(r); if (top.length === 10) break; }
    } else {
      top = GL.features.map((f) => ({ p: f.properties, v: (f.properties.m || {})[mm(st.m)] || 0, k: `${esc(f.properties.c)} · ${fmt(f.properties.h)} m`, col: GLASS[CL2L[f.properties.c]], src: "gx" }))
        .filter((x) => x.v > 0).sort((a, b) => b.v - a.v).slice(0, 10);
    }
    const mx = top[0]?.v || 1;
    $("#rank").innerHTML = top.map((r, i) => `<li data-i="${r.p.i}" data-s="${r.src}"><span class="n">${i + 1}</span><span>${esc(r.p.n || "Unnamed building")}<small>${r.k}</small></span>
      <span class="bar" style="width:${Math.max(4, 70 * r.v / mx)}px;background:${r.col}"></span><span class="v">${fmt(r.v, r.v < 10 ? 1 : 0)}</span></li>`).join("");
    $$("#rank li").forEach((li) => li.onclick = () => {
      const src = li.dataset.s === "gx" ? GL : T;
      const f = src.features.find((x) => x.properties.i === +li.dataset.i); if (!f) return;
      const c = centroid(f.geometry); map.flyTo({ center: c, zoom: 16, pitch: st.view === "3d" ? 60 : 0, duration: 900 });
      (li.dataset.s === "gx" ? selectGlass : selectTower)(+li.dataset.i, { lng: c[0], lat: c[1] });
    });
    legend();
  }
  function centroid(g) {
    const ring = (g.type === "Polygon" ? g.coordinates : g.coordinates[0])[0];
    return [ring.reduce((a, p) => a + p[0], 0) / ring.length, ring.reduce((a, p) => a + p[1], 0) / ring.length];
  }
  function lede() {
    const ix = IDX[st.m]; const d = (S.shadows && S.shadows.days || {})[mm(st.m)]; const g = (S.glare && S.glare.days || {})[mm(st.m)];
    if (!ix || !d) { $("#lede").innerHTML = "&nbsp;"; return; }
    const M = `21 ${MON[st.m - 1]}`;
    if (st.mode === "loss") {
      const l = (S.sunloss || {})[mm(st.m)];
      $("#lede").innerHTML = `<b>${M}, whole day:</b> the towers take at least one hour of direct sun from <b>${fmt(l ? l.km2[1] : d.loss_km2_1h, 2)} km²</b> of streets and roofs.`;
      return;
    }
    if (st.mode === "glare") {
      $("#lede").innerHTML = g ? `<b>${M}, whole day:</b> glass towers throw sunlight onto <b>${fmt(g.km2_30min * 100)} ha</b> of streets and roofs for 30 minutes or more, and onto <b>${fmt(g.km2_1h * 100)} ha</b> for an hour or more.` : "";
      return;
    }
    const H = ix.hours[st.t]; if (!H) return;
    const G = gHour();
    const sh = `shade <b>${fmt(H.g)} ha</b> of ground and <b>${fmt(H.r)} ha</b> of rooftops`;
    const gl = G ? `throw sunlight onto <b>${fmt(G.g, 1)} ha</b> of ground and <b>${fmt(G.r, 1)} ha</b> of roofs (${fmt(G.b)} buildings)` : "throw no sunlight now";
    if (st.mode === "dark") $("#lede").innerHTML = `<b>${M}, ${H.t}</b> · sun ${fmt(H.alt)}° high: Frankfurt's towers ${sh}.`;
    else if (st.mode === "light") $("#lede").innerHTML = `<b>${M}, ${H.t}</b> · sun ${fmt(H.alt)}° high: glass towers ${gl}.`;
    else $("#lede").innerHTML = `<b>${M}, ${H.t}</b> · sun ${fmt(H.alt)}° high: the towers ${sh}, while glass façades ${gl}.`;
  }
  function dayChart() {
    const ix = IDX[st.m]; const d = (S.shadows && S.shadows.days || {})[mm(st.m)]; const g = (S.glare && S.glare.days || {})[mm(st.m)];
    if (!ix || !d) return;
    const n = d.times.length, x0 = 42, x1 = 300, y0 = 12, y1 = 112;
    const tot = d.ground_ha.map((v, i) => v + (d.roof_ha[i] || 0));
    const all = Object.values(S.shadows.days).flatMap((x) => x.ground_ha.map((v, i) => v + (x.roof_ha[i] || 0))).sort((a, b) => a - b);
    const mx = (all[Math.floor(all.length * 0.9)] || 1) * 1.1, X = (i) => x0 + (n > 1 ? i * (x1 - x0) / (n - 1) : 0), Y = (v) => Math.max(y0, y1 - (y1 - y0) * v / mx);
    let s = `<line x1="${x0}" x2="${x1}" y1="${y1}" y2="${y1}" stroke="var(--line)"/>`;
    s += `<path d="M${X(0)},${y1} ${tot.map((v, i) => `L${X(i)},${Y(v)}`).join(" ")} L${X(n - 1)},${y1}Z" fill="var(--shade)" opacity=".7"/>`;
    if (g) {
      const gt = g.ground_ha.map((v, i) => v + (g.roof_ha[i] || 0));
      const gm = Math.max(...Object.values(S.glare.days).flatMap((x) => x.ground_ha.map((v, i) => v + (x.roof_ha[i] || 0)))) * 1.1 || 1;
      const Xg = (i) => x0 + (gt.length > 1 ? i * (x1 - x0) / (gt.length - 1) : 0), Yg = (v) => y1 - (y1 - y0) * v / gm;
      s += `<path d="${gt.map((v, i) => `${i ? "L" : "M"}${Xg(i)},${Yg(v)}`).join(" ")}" fill="none" stroke="var(--glare)" stroke-width="2.4"/>`;
      s += `<text x="${x1 + 26}" y="${y0 + 3}" text-anchor="end" fill="var(--glare)">${fmt(gm)} ha</text>`;
    }
    s += `<text x="${x0 - 4}" y="${y0 + 3}" text-anchor="end">${fmt(mx)} ha</text><text x="${x0 - 4}" y="${y1}" text-anchor="end">0</text>`;
    [0, Math.floor((n - 1) / 2), n - 1].forEach((k) => { s += `<text x="${X(k)}" y="${y1 + 13}" text-anchor="middle">${d.times[k]}</text>`; });
    const H = ix.hours[st.t], k = H ? d.times.indexOf(H.t) : -1;
    if (!["loss", "glare"].includes(st.mode) && k >= 0) s += `<line x1="${X(k)}" x2="${X(k)}" y1="${y0 - 4}" y2="${y1}" stroke="var(--ink)" stroke-width="1.4"/><circle cx="${X(k)}" cy="${y0 - 4}" r="3" fill="#f5b014"/>`;
    s += `<text x="${x0}" y="136">shade: left scale · reflected sun: right scale</text>`;
    $("#dayChart").innerHTML = s;
  }

  function clearSel() {
    if (st.sel) map.setFeatureState({ source: st.sel[0], id: st.sel[1] }, { sel: false });
  }
  function selectTower(i, ll) {
    const f = T.features.find((x) => x.properties.i === +i); if (!f) return;
    const p = f.properties;
    clearSel(); st.sel = ["tw", p.i]; map.setFeatureState({ source: "tw", id: p.i }, { sel: true });
    const v = (p.m || {})[mm(st.m)] || [0, 0, 0];
    popup.setLngLat(ll).setHTML(`<div class="pop"><b>${esc(p.n || "Unnamed building")}</b><small>${esc([p.a, p.use].filter(Boolean).join(" · "))}</small>
      <table class="ptab"><tr><td>measured height</td><td>${fmt(p.h, 1)} m</td></tr>${p.lv ? `<tr><td>storeys (OSM)</td><td>${p.lv}</td></tr>` : ""}
      ${p.arch ? `<tr><td>architect</td><td>${esc(p.arch)}</td></tr>` : ""}${p.year ? `<tr><td>built</td><td>${esc(p.year)}</td></tr>` : ""}<tr><td>façade class</td><td>none yet (not in the 58 m+ inventory)</td></tr></table>
      <div class="verdict"><b>21 ${MON[st.m - 1]}:</b> shades ${fmt(v[0], 1)} ha·h of ground and ${fmt(v[1], 1)} ha·h of roofs, on ${fmt(v[2])} other buildings.</div>
      ${p.osm ? `<small><a href="https://www.openstreetmap.org/${esc(p.osm)}" target="_blank" rel="noopener">OpenStreetMap ↗</a></small>` : ""}</div>`).addTo(map);
  }
  function selectGlass(i, ll) {
    const f = GL.features.find((x) => x.properties.i === +i); if (!f) return;
    const p = f.properties;
    clearSel(); st.sel = ["gx", p.i]; map.setFeatureState({ source: "gx", id: p.i }, { sel: true });
    const v = (p.m || {})[mm(st.m)] || 0;
    const L = CL2L[p.c];
    popup.setLngLat(ll).setHTML(`<div class="pop"><b>${esc(p.n)}</b><small><i class="cls" style="background:${GLASS[L]}"></i>${esc(GLASSN[L])}</small>
      <table class="ptab"><tr><td>height (LoD2)</td><td>${fmt(p.h, 1)} m</td></tr>${p.f ? `<tr><td>façade</td><td>${esc(p.f)}</td></tr>` : ""}
      ${p.lk ? `<tr><td>glass look</td><td>${esc(p.lk)}</td></tr>` : ""}${p.g ? `<tr><td>shape</td><td>${esc(p.g)}</td></tr>` : ""}
      <tr><td>reflection weight</td><td>${fmt(p.w, 2)}</td></tr><tr><td>evidence</td><td>${esc(p.ev || "–")} · confidence ${esc(p.cf || "–")}</td></tr></table>
      <div class="verdict"><b>21 ${MON[st.m - 1]}:</b> its reflected sunlight lands on ${fmt(v, 2)} ha·h of streets and roofs over the day.</div>
      ${p.s ? `<small><a href="${esc(p.s)}" target="_blank" rel="noopener">Wikipedia (de) ↗</a></small>` : ""}</div>`).addTo(map);
  }

  function legend() {
    const L = $("#legend"), M = `21 ${MON[st.m - 1]}`;
    if (st.mode === "loss") {
      const b = LI ? LI.bins : [0.5, 1, 2, 3, 5];
      L.innerHTML = `<div class="lg-title">Direct sun lost to the towers · ${M}</div><div class="lg-sub">hours over the whole day, ground and roofs</div>
        <div class="vsteps">${LOSS.map((c) => `<i style="background:${c}"></i>`).join("")}</div>
        <div class="vticks">${b.map((x, k) => `<span>${x}${k === b.length - 1 ? "+ h" : ""}</span>`).join("")}</div>`;
      return;
    }
    if (st.mode === "glare") {
      const b = GI ? GI.bins : [0.5, 1, 1.5, 2, 3];
      L.innerHTML = `<div class="lg-title">Hours of reflected sun · ${M}</div><div class="lg-sub">sunlight thrown back by A1, A2 and B glass façades, whole day</div>
        <div class="vsteps">${GH.map((c) => `<i style="background:${c}"></i>`).join("")}</div>
        <div class="vticks">${b.map((x, k) => `<span>${x < 1 ? x * 60 + " min" : x + (k === b.length - 1 ? "+ h" : " h")}</span>`).join("")}</div>`;
      return;
    }
    const sh = showShade() ? `<div class="lg-row"><i class="sq" style="background:${C.shade}"></i>shadow (dark)</div>` : "";
    const gl = showGlare() ? `<div class="lg-row"><i class="sq" style="background:${GLARE[4]}"></i>reflected sun from A1 glass <small>strongest</small></div>
      <div class="lg-row"><i class="sq" style="background:${GLARE[3]}"></i>… from A2 · <i class="sq inl" style="background:${GLARE[2]}"></i> B · <i class="sq inl" style="background:${GLARE[1]}"></i> C</div>` : "";
    L.innerHTML = `<div class="lg-title">${st.mode === "dark" ? "Dark: the towers' shadows" : st.mode === "light" ? "Light: sunlight thrown back by glass" : "Light & dark"}</div><div class="lg-sub">${M}, local time · towers coloured by façade</div>
      ${sh}${gl}
      <div class="lg-row"><i class="sq" style="background:${GLASS[4]}"></i>glass tower <small>A1 → C lighter</small></div>
      <div class="lg-row"><i class="sq" style="background:${C.tower}"></i>other building ≥ 30 m <small>no façade class</small></div>`;
  }
})();
