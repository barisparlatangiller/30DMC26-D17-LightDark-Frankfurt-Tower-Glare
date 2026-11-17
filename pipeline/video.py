"""
Day 17 time-lapse for LinkedIn (top view, the Day 5 frame and palette): 21 June every 3 minutes. The towers' shadows
sweep over Frankfurt in blue while the sunlight their glass façades throw back lands in orange, and the hours of
reflected sun build up. Rendered straight from the shadow and reflection engines (no screen recording).

  python pipeline/video.py [--workers 4] [--step 3]
Output  build/video/day17_frankfurt_light_dark_21jun.mp4 (1080×1350, H.264, ~19 s) · build/video/cover.png ·
        build/video/still_HHMM.png (moments for a carousel)
"""
import argparse, json, math, os, subprocess, time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import geopandas as gpd
import shapely
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pyproj import Transformer
from rasterio import features
from rasterio.transform import Affine
from scipy.ndimage import zoom as ndzoom

import shadows as S
import reflections as R

W, H = 1080, 1350
MAP_Y, MAP_H = 214, 1000
CENTER = (8.6770, 50.1105)                   # Day 5 frame, widened east to include the ECB (the brightest mirror)
SPAN = 4200.0
FPS = 24
BG, BLD, TOWER, WATER, INK, INK2 = (246, 243, 238), (214, 209, 200), (120, 116, 110), (222, 229, 233), (43, 41, 37), (111, 106, 97)
GLASS = {4: (28, 92, 150), 3: (66, 132, 184), 2: (128, 160, 182), 1: (160, 150, 138), 9: (150, 146, 140)}
# one muted, earthy family: dusty blue (shade) · soft amber (reflected sun) · dusty plum (both), light → deep
DAY = {1: (np.array([150, 166, 196.]), np.array([70, 90, 136.])),     # only shade
       2: (np.array([236, 196, 150.]), np.array([196, 120, 62.])),    # only reflected sun
       3: (np.array([186, 160, 196.]), np.array([116, 86, 134.]))}    # both over the day
SHADE = np.array([52, 64, 108.])            # shadow now
HOT = np.array([232, 134, 56.])             # reflection now
ACCENT = (184, 98, 40)
B = Path("build"); OUT = B / "video"


def font(size, bold=False):
    for name in (["Inter:bold", "DejaVu Sans:bold"] if bold else ["Inter", "DejaVu Sans"]):
        try:
            f = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True, text=True).stdout.strip()
            if f:
                return ImageFont.truetype(f, size)
        except Exception:                                                # noqa: BLE001
            pass
    return ImageFont.load_default()


def water(bounds4326):
    w, s_, e, n = bounds4326
    q = f'[out:json][timeout:120];(way["natural"="water"]({s_},{w},{n},{e});relation["natural"="water"]({s_},{w},{n},{e});way["waterway"="riverbank"]({s_},{w},{n},{e}););out geom;'
    d = None
    for url in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                "https://overpass.private.coffee/api/interpreter", "https://overpass-api.de/api/interpreter"]:
        try:
            d = requests.post(url, data={"data": q}, timeout=180, headers={"User-Agent": "30DMC26-D17 (github.com/barisparlatangiller)"}).json()
            break
        except Exception as e:                                           # noqa: BLE001
            print("water: retry after", url, e); time.sleep(10)
    if d is None:
        print("water not available"); return []
    polys = []
    for el in d["elements"]:
        rings = [el["geometry"]] if el["type"] == "way" and el.get("geometry") else \
                [m["geometry"] for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
        for rg in rings:
            if len(rg) >= 4:
                polys.append(shapely.Polygon([(p["lon"], p["lat"]) for p in rg]))
    return polys


MIN_H = 0.25                                # 15 min of shade / reflected sun before a place counts


def daymix(sh_h, gl_h):
    """hours in shade + hours of reflected sun so far → category colour (shade / sun / both) and alpha"""
    s, g = sh_h >= MIN_H, gl_h >= MIN_H
    cat = np.where(s & g, 3, np.where(g, 2, np.where(s, 1, 0)))
    tot = np.clip((sh_h * s + gl_h * g) / 4.0, 0, 1)[..., None]
    rgb = np.zeros(sh_h.shape + (3,))
    for k, (lo, hi) in DAY.items():
        m = cat == k
        rgb[m] = lo * (1 - tot[m]) + hi * tot[m]
    a = np.where(cat > 0, 0.30 + 0.32 * tot[..., 0], 0.0)
    return rgb, a, cat


G_FR = {}


def step_job(args):
    """one time step → (index, shadow WKB, glare known uint8 window crop resampled to the frame)"""
    ti, az, alt = args
    _, u, _, _, _, _ = S.run_step((ti, az, alt, 2.0, False))
    known, unk, _ = R.glare_step(az, alt, 2.0)
    r0, c0 = G_FR["off"]
    crop = known[r0:r0 + G_FR["h2"], c0:c0 + G_FR["w2"]]
    return ti, u, crop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--step", type=int, default=3)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fr = OUT / "frames"; fr.mkdir(exist_ok=True)
    for f in fr.glob("*.jpg"):
        f.unlink()

    to25 = Transformer.from_crs(4326, 25832, always_xy=True)
    cx, cy = to25.transform(*CENTER)
    px = SPAN / W
    x0, y1 = cx - SPAN / 2, cy + MAP_H * px / 2
    tr = Affine(px, 0, x0, 0, -px, y1)
    area = shapely.box(x0, y1 - MAP_H * px, x0 + SPAN, y1)
    f = R.setup(B, 2.0)                                                  # loads every tower (shadows) + façades (glare)
    c = gpd.read_parquet(B / "casters.parquet")
    r = gpd.read_parquet(B / "receivers.parquet")
    # frame window inside the glare window (2 m cells)
    g = S.G["grid"]; r0w, c0w, whw, www = S.G["win"]
    fc0 = int((x0 - g["x0"]) / 2) - c0w; fr0 = int((g["y1"] - y1) / 2) - r0w
    G_FR.update(off=(fr0, fc0), w2=int(SPAN / 2), h2=int(MAP_H * px / 2))
    assert fr0 >= 0 and fc0 >= 0, "frame outside the glare window"

    base = np.zeros((MAP_H, W, 3), dtype=float); base[:] = BG
    to4 = Transformer.from_crs(25832, 4326, always_xy=True)
    bw = to4.transform(area.bounds[0], area.bounds[1]) + to4.transform(area.bounds[2], area.bounds[3])
    wp = [shapely.transform(p, lambda xy: np.c_[to25.transform(xy[:, 0], xy[:, 1])]) for p in water((bw[0], bw[1], bw[2], bw[3]))]
    if wp:
        m = features.rasterize(wp, out_shape=(MAP_H, W), transform=tr, dtype="uint8").astype(bool)
        base[m] = WATER
    rr = r[r.intersects(area)]
    m = features.rasterize(rr.geometry.values, out_shape=(MAP_H, W), transform=tr, dtype="uint8").astype(bool)
    base[m] = BLD
    tow = features.rasterize(c[c.intersects(area)].geometry.values, out_shape=(MAP_H, W), transform=tr, dtype="uint8").astype(bool)
    fa = f[f.intersects(area)]
    levmap = {"A1": 4, "A2": 3, "B": 2, "C": 1, "U": 9}
    glass = features.rasterize(zip(fa.geometry.values, [levmap[k] for k in fa.cls]), out_shape=(MAP_H, W), transform=tr,
                               fill=0, dtype="uint8") if len(fa) else np.zeros((MAP_H, W), "uint8")

    steps = S.sun_times(6, a.step)
    shade = [None] * len(steps); glare = [None] * len(steps)
    t0 = time.time()
    with Pool(a.workers) as pool:
        for ti, u, crop in pool.imap_unordered(step_job, [(i, az, alt) for i, (_, az, alt) in enumerate(steps)], chunksize=1):
            if u is not None:
                gg = shapely.intersection(shapely.from_wkb(u), area.buffer(50))
                shade[ti] = features.rasterize([(gg, 1)], out_shape=(MAP_H, W), transform=tr, dtype="uint8").astype(bool) if not gg.is_empty else None
            k = crop.astype("float32") / 100.0
            k = ndzoom(k, (MAP_H / k.shape[0], W / k.shape[1]), order=1)[:MAP_H, :W]
            glare[ti] = np.clip(k, 0, 1).astype("float16")
    print(f"{len(steps)} steps in {time.time() - t0:.0f} s", flush=True)

    st = json.loads(Path("docs/data/stats.json").read_text())
    cb = st.get("combo", {}).get("06", {})
    fac = st.get("facades", {})
    F = {k: font(*v) for k, v in {"title": (40, True), "eyebrow": (23, True), "clock": (64, True), "small": (25, False),
                                  "label": (22, True), "big": (60, True), "foot": (21, False), "mid": (30, True)}.items()}

    def frame(acc, sh, gl, clock, alt, outro=0.0, cap=None):
        img = base.copy()
        rgb, al, _ = daymix(*acc)
        img = img * (1 - al[..., None]) + rgb * al[..., None]
        if sh is not None:
            img[sh] = img[sh] * 0.62 + SHADE * 0.38
        if gl is not None:
            gm = gl.astype("float32")
            glow = np.asarray(Image.fromarray((np.clip(gm, 0, 1) * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(2.5))).astype("float32") / 255
            a_ = np.clip(np.maximum(gm * 0.95, glow * 0.45), 0, 0.85)[..., None]
            img = img * (1 - a_) + HOT * a_
        img[tow] = TOWER
        for lv, col in GLASS.items():
            img[glass == lv] = col
        im = Image.new("RGB", (W, H), BG)
        im.paste(Image.fromarray(np.clip(img, 0, 255).astype("uint8")), (0, MAP_Y))
        d = ImageDraw.Draw(im)
        d.text((48, 34), "#30DAYMAPCHALLENGE · DAY 17 · LIGHT & DARK · FRANKFURT", font=F["eyebrow"], fill=ACCENT)
        d.text((48, 72), "Towers cast shade.", font=F["title"], fill=INK)
        d.text((48, 120), "Glass towers also throw the sun back.", font=F["title"], fill=ACCENT)
        d.text((48, 172), "21 June · shadows (blue) and sunlight reflected by glass façades (amber)", font=F["small"], fill=INK2)
        if clock and outro == 0:
            d.text((W - 48, 30), clock, font=F["clock"], fill=INK, anchor="ra")
            d.text((W - 48, 104), f"sun {alt:.0f}° high", font=F["small"], fill=INK2, anchor="ra")
        if cap:
            d.rounded_rectangle([48, MAP_Y + 24, 48 + d.textlength(cap, font=F["label"]) + 32, MAP_Y + 68], 12, fill=(253, 251, 247))
            d.text((64, MAP_Y + 34), cap, font=F["label"], fill=INK)
        ly = MAP_Y + MAP_H + 24
        sw = lambda x, y, c: d.rounded_rectangle([x, y, x + 20, y + 16], 4, fill=tuple(int(v) for v in c))
        d.text((48, ly - 4), "so far today:", font=F["foot"], fill=INK2)
        for k, (t, x) in enumerate([("shade", 190), ("reflected sun", 300), ("both", 482)], start=1):
            sw(x, ly, DAY[k][1] * 0.6 + DAY[k][0] * 0.4); d.text((x + 28, ly - 4), t, font=F["foot"], fill=INK2)
        d.text((48, ly + 26), "right now:", font=F["foot"], fill=INK2)
        sw(190, ly + 30, SHADE); d.text((218, ly + 26), "shadow", font=F["foot"], fill=INK2)
        sw(300, ly + 30, HOT); d.text((328, ly + 26), "reflection", font=F["foot"], fill=INK2)
        sw(740, ly, GLASS[4]); d.text((768, ly - 4), "glass tower", font=F["foot"], fill=INK2)
        sw(740, ly + 30, TOWER); d.text((768, ly + 26), "other tower ≥ 30 m", font=F["foot"], fill=INK2)
        d.text((48, H - 34), "LoD2 3D buildings © HVBG · façade classes from Wikipedia text + photos · B. Parlatangiller", font=F["foot"], fill=(150, 145, 136))
        if outro > 0:
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); o = ImageDraw.Draw(ov)
            k_ = min(1, outro); a_ = int(238 * k_)
            o.rounded_rectangle([64, MAP_Y + 210, W - 64, MAP_Y + 800], 28, fill=(253, 251, 247, a_))
            c2 = (43, 41, 37, int(255 * k_)); c3 = (111, 106, 97, int(255 * k_))
            o.text((W // 2, MAP_Y + 250), "One summer day in Frankfurt · 30 minutes or more", font=F["small"], fill=c3, anchor="ma")
            rows = [(3, cb.get("both_ha"), "lose the sun to one tower", "and get it back from a glass one"),
                    (1, cb.get("shade_only_ha"), "only lose sun", "to the towers' shadows"),
                    (2, cb.get("sun_only_ha"), "only get extra sun", "reflected by glass façades")]
            for k, (cat, v, l1, l2) in enumerate(rows):
                y = MAP_Y + 300 + k * 120
                c = tuple(int(x) for x in DAY[cat][1]) + (int(255 * k_),)
                o.rounded_rectangle([120, y + 8, 146, y + 60], 6, fill=c)
                o.text((166, y), f"{v:,.0f} ha" if v is not None else "–", font=F["big"], fill=c)
                o.text((470, y + 6), l1, font=F["label"], fill=c2)
                o.text((470, y + 36), l2, font=F["small"], fill=c3)
            o.text((W // 2, MAP_Y + 680), f"{fac.get('inventory', 81)} towers ≥ 58 m checked façade by façade", font=F["label"], fill=c2, anchor="ma")
            o.text((W // 2, MAP_Y + 720), "Tap any street on the map: when is it in shade, when does it glow?", font=F["label"], fill=c2, anchor="ma")
            o.text((W // 2, MAP_Y + 756), "barisparlatangiller.github.io", font=F["label"], fill=ACCENT + (int(255 * k_),), anchor="ma")
            im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
        return im

    n = 0
    sh_h = np.zeros((MAP_H, W), dtype="float32"); gl_h = np.zeros_like(sh_h)
    zero = (np.zeros_like(sh_h), np.zeros_like(sh_h))
    save = lambda im: im.save(fr / f"f{n:04d}.jpg", quality=92)
    for k in range(int(FPS * 1.2)):
        save(frame(zero, None, None, steps[0][0].strftime("%H:%M"), steps[0][2])); n += 1
    stills = {"0800", "1300", "1830"}
    best, best_v = None, -1
    for i, (ts, az, alt) in enumerate(steps):
        gl = glare[i]
        if gl is not None:
            gl_h += (gl.astype("float32") >= 0.3) * (a.step / 60)
        if shade[i] is not None:
            sh_h += shade[i] * (a.step / 60)
        acc = (sh_h, gl_h)
        im = frame(acc, shade[i], gl, ts.strftime("%H:%M"), alt)
        save(im); n += 1
        if ts.strftime("%H%M") in stills:
            im.save(OUT / f"still_{ts.strftime('%H%M')}.png")
        v = float((gl.astype("float32") >= 0.3).sum()) if gl is not None else 0
        if ts.strftime("%H:%M") >= "18:15" and ts.strftime("%H:%M") <= "18:45" and v > best_v:
            best, best_v = ((sh_h.copy(), gl_h.copy()), shade[i], gl, ts.strftime("%H:%M"), alt), v
    for k in range(int(FPS * 1.0)):                                     # hold the full day without the moment
        save(frame(acc, None, None, "whole day", steps[-1][2])); n += 1
    for k in range(int(FPS * 4.0)):
        save(frame(acc, None, None, "whole day", steps[-1][2], outro=min(1, k / (FPS * 0.6)))); n += 1
    frame(acc, None, None, "whole day", steps[-1][2], outro=1).save(OUT / "outro.png")
    if best:
        frame(*best).save(OUT / "cover.png")                             # golden hour: shade + glare + the day so far
    out = OUT / "day17_frankfurt_light_dark_21jun.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(fr / "f%04d.jpg"),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-profile:v", "main", "-pix_fmt", "yuv420p",
                    "-color_range", "tv", "-tag:v", "avc1", "-movflags", "+faststart", str(out)], check=True)
    print(f"video: {n} frames, {n / FPS:.1f} s, {out.stat().st_size / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
