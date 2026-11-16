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
CENTER = (8.6705, 50.1112)                   # Bankenviertel / Westend / Messe (as Day 5)
SPAN = 3600.0
FPS = 24
BG, BLD, TOWER, WATER, INK, INK2 = (246, 243, 238), (214, 209, 200), (120, 116, 110), (222, 229, 233), (43, 41, 37), (111, 106, 97)
GLASS = {4: (28, 92, 150), 3: (66, 132, 184), 2: (128, 160, 182), 1: (160, 150, 138), 9: (150, 146, 140)}
SHADE = np.array([30, 38, 92])
ORANGE = np.array([[255, 226, 170], [253, 186, 104], [246, 138, 44], [226, 92, 14], [176, 52, 6]], dtype=float)
HOT = np.array([255, 120, 10], dtype=float)
ACCENT = (214, 92, 12)
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
    try:
        d = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, timeout=180).json()
    except Exception as e:                                               # noqa: BLE001
        print("water not available:", e); return []
    polys = []
    for el in d["elements"]:
        rings = [el["geometry"]] if el["type"] == "way" and el.get("geometry") else \
                [m["geometry"] for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
        for rg in rings:
            if len(rg) >= 4:
                polys.append(shapely.Polygon([(p["lon"], p["lat"]) for p in rg]))
    return polys


def oranges(hours):
    """hours of reflected sun → RGB + alpha (0.1 h faint … 2 h deep)"""
    t = np.clip(hours / 2.0, 0, 1) * (len(ORANGE) - 1)
    i = np.clip(np.floor(t).astype(int), 0, len(ORANGE) - 2)
    f = (t - i)[..., None]
    rgb = ORANGE[i] * (1 - f) + ORANGE[i + 1] * f
    a = np.clip(hours / 0.4, 0, 1) * 0.8
    return rgb, a


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
    gd = st.get("glare", {}).get("days", {}).get("06", {})
    k1h, k30 = gd.get("km2_1h"), gd.get("km2_30min")
    fac = st.get("facades", {})
    F = {k: font(*v) for k, v in {"title": (40, True), "eyebrow": (23, True), "clock": (64, True), "small": (25, False),
                                  "label": (22, True), "big": (60, True), "foot": (21, False), "mid": (30, True)}.items()}

    def frame(acc, sh, gl, clock, alt, outro=0.0, cap=None):
        img = base.copy()
        rgb, al = oranges(acc)
        img = img * (1 - al[..., None]) + rgb * al[..., None]
        if sh is not None:
            img[sh] = img[sh] * 0.6 + SHADE * 0.4
        if gl is not None:
            gm = gl.astype("float32")
            glow = np.asarray(Image.fromarray((np.clip(gm, 0, 1) * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(3))).astype("float32") / 255
            a_ = np.clip(np.maximum(gm * 1.1, glow * 0.6), 0, 0.95)[..., None]
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
        d.text((48, 172), "21 June · shadows (blue) and sunlight reflected by glass façades (orange)", font=F["small"], fill=INK2)
        if clock and outro == 0:
            d.text((W - 48, 30), clock, font=F["clock"], fill=INK, anchor="ra")
            d.text((W - 48, 104), f"sun {alt:.0f}° high", font=F["small"], fill=INK2, anchor="ra")
        if cap:
            d.rounded_rectangle([48, MAP_Y + 24, 48 + d.textlength(cap, font=F["label"]) + 32, MAP_Y + 68], 12, fill=(253, 251, 247))
            d.text((64, MAP_Y + 34), cap, font=F["label"], fill=INK)
        ly = MAP_Y + MAP_H + 24
        for k in range(5):
            d.rectangle([48 + k * 62, ly, 48 + (k + 1) * 62 - 2, ly + 16], fill=tuple(int(v) for v in ORANGE[k]))
        for k, t in enumerate(["5 min", "30", "1 h", "1.5", "2 h+"]):
            d.text((48 + k * 62, ly + 22), t, font=F["foot"], fill=INK2)
        d.text((372, ly - 3), "hours of reflected sun, adding up", font=F["foot"], fill=INK2)
        d.rectangle([372, ly + 28, 390, ly + 44], fill=tuple(SHADE)); d.text((398, ly + 24), "shadow now", font=F["foot"], fill=INK2)
        d.rectangle([540, ly + 28, 558, ly + 44], fill=tuple(int(v) for v in HOT)); d.text((566, ly + 24), "reflection now", font=F["foot"], fill=INK2)
        d.rectangle([740, ly - 1, 758, ly + 15], fill=GLASS[4]); d.text((766, ly - 3), "glass tower", font=F["foot"], fill=INK2)
        d.rectangle([740, ly + 28, 758, ly + 44], fill=TOWER); d.text((766, ly + 24), "other tower ≥ 30 m", font=F["foot"], fill=INK2)
        d.text((48, H - 34), "LoD2 3D buildings © HVBG · façade classes from Wikipedia text + photos · B. Parlatangiller", font=F["foot"], fill=(150, 145, 136))
        if outro > 0:
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); o = ImageDraw.Draw(ov)
            k_ = min(1, outro); a_ = int(238 * k_)
            o.rounded_rectangle([64, MAP_Y + 250, W - 64, MAP_Y + 770], 28, fill=(253, 251, 247, a_))
            col = (190, 70, 8, int(255 * k_)); c2 = (43, 41, 37, int(255 * k_))
            o.text((W // 2, MAP_Y + 300), "One summer day", font=F["small"], fill=c2, anchor="ma")
            o.text((W // 2, MAP_Y + 350), f"{k1h * 100:,.0f} ha" if k1h else "", font=F["big"], fill=col, anchor="ma")
            o.text((W // 2, MAP_Y + 428), "of streets and roofs get 1 hour or more", font=F["small"], fill=c2, anchor="ma")
            o.text((W // 2, MAP_Y + 462), "of sunlight thrown back by glass towers", font=F["small"], fill=c2, anchor="ma")
            o.text((W // 2, MAP_Y + 520), f"{k30 * 100:,.0f} ha get at least 30 minutes" if k30 else "", font=F["label"], fill=c2, anchor="ma")
            o.text((W // 2, MAP_Y + 600), f"{fac.get('matched', '')} towers checked façade by façade", font=F["label"], fill=c2, anchor="ma")
            o.text((W // 2, MAP_Y + 650), "Interactive map: shade + reflections, every month", font=F["label"], fill=c2, anchor="ma")
            o.text((W // 2, MAP_Y + 690), "barisparlatangiller.github.io", font=F["label"], fill=(194, 87, 12, int(255 * k_)), anchor="ma")
            im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
        return im

    n = 0
    acc = np.zeros((MAP_H, W), dtype="float32"); zero = np.zeros_like(acc)
    save = lambda im: im.save(fr / f"f{n:04d}.jpg", quality=92)
    for k in range(int(FPS * 1.2)):
        save(frame(zero, None, None, steps[0][0].strftime("%H:%M"), steps[0][2])); n += 1
    stills = {"0800", "1300", "1830"}
    best, best_v = None, -1
    for i, (ts, az, alt) in enumerate(steps):
        gl = glare[i]
        if gl is not None:
            acc += (gl.astype("float32") >= 0.3) * (a.step / 60)
        im = frame(acc, shade[i], gl, ts.strftime("%H:%M"), alt)
        save(im); n += 1
        if ts.strftime("%H%M") in stills:
            im.save(OUT / f"still_{ts.strftime('%H%M')}.png")
        v = float((gl.astype("float32") >= 0.3).sum()) if gl is not None else 0
        if 16 <= ts.hour <= 19 and v > best_v:
            best, best_v = (acc.copy(), shade[i], gl, ts.strftime("%H:%M"), alt), v
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
