"""
Sunlight thrown back by Frankfurt's glass towers ("reverse shadows").

A vertical glass façade is a mirror. Sunlight that falls on it at altitude α leaves it at the same altitude α,
going down, in the horizontal direction mirrored across the façade:  r = d − 2 (d·n) n   (d = sun ray, n = façade
normal). So a façade point at height z lights the surface where the descending ray meets it:

    surface point P at distance s from the façade along r receives light  ⇔  T(s) = z_P + s·tan α  lies between the
    lowest sunlit façade height and the façade top, and no surface before it was hit first:  T(s) > max T(s' < s)

The second condition is the same cumulative-maximum test as the shadow model (shadows.py), run outward from the
façade instead of away from the sun. A façade point is sunlit above  z_lit = max over s' towards the sun of
(z(s') − s'·tan α), from the same 2 m surface (LoD2 roof planes, roofs, ground). Towers, lower buildings and terrain
all block, in both directions.

Façades: the outer walls of every LoD2 tower part matched to the façade inventory (match_facades.py), sampled every
1.5 m, each with the relative reflection weight of its class (A1 1.0 · A2 0.75 · B 0.45 · C 0.15; U = unknown, kept
as a separate "uncertain" layer). The weight is a relative assumption, not a measured reflectance.

Days     the 21st of every month 2026, every 30 minutes while the sun is ≥ 5° high (as the shadow model)
Output   docs/data/glare/MM/HH.json (full hours; lev 1 C · 2 B · 3 A2 · 4 A1 · 9 unknown; k g ground | r roof, h)
         docs/data/glare/MM/index.json · build/glare_MM.npy (hours of reflected sun from A1/A2/B façades, 4 m)
         build/glare_tower_stats.json · stats.json["glare"]

  python pipeline/reflections.py [--months 6] [--step 30] [--workers 4]
"""
import argparse, json, math, os, time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import geopandas as gpd
import shapely
from rasterio import features
from rasterio.transform import Affine
from scipy.ndimage import grey_dilation

import shadows as S

G = S.G
SPACING = 1.5          # façade sample spacing (m)
S0 = 3.0               # first sample off the wall (keeps clear of the tower's own 2 m cells)
STEP = 2.0             # march step (m)
MAX_IN = 1500.0        # look this far towards the sun for obstacles
MAX_OUT = 1500.0       # longest reflected ray followed
LEV = {"C": 1, "B": 2, "A2": 3, "A1": 4, "U": 9}
CHUNK = 3000


def walls(f):
    """façade samples of the matched tower parts → dict of arrays (x, y, nx, ny, z0, top, w, lev, inv)"""
    out = {k: [] for k in ("x", "y", "nx", "ny", "z0", "top", "w", "lev", "inv")}
    for r in f.itertuples():
        polys = list(r.geometry.geoms) if r.geometry.geom_type == "MultiPolygon" else [r.geometry]
        for p in polys:
            p = shapely.geometry.polygon.orient(p, 1.0)                 # CCW: interior on the left
            xy = np.asarray(p.exterior.coords)
            for (x0, y0), (x1, y1) in zip(xy[:-1], xy[1:]):
                L = math.hypot(x1 - x0, y1 - y0)
                if L < 2.0:
                    continue
                n = max(1, int(L // SPACING))
                t = (np.arange(n) + 0.5) / n
                out["x"].append(x0 + t * (x1 - x0)); out["y"].append(y0 + t * (y1 - y0))
                nx, ny = (y1 - y0) / L, -(x1 - x0) / L                    # outward normal (right of a CCW edge)
                for k, v in (("nx", nx), ("ny", ny), ("z0", r.z0), ("top", r.top), ("w", r.w), ("lev", LEV[r.cls]), ("inv", r.inv)):
                    out[k].append(np.full(n, v, dtype="float64"))
    return {k: np.concatenate(v) for k, v in out.items()}


def window(f, res):
    """2 m window aligned to the global surface grid: the matched towers + the longest reflection"""
    g = G["grid"]
    x0, y0, x1, y1 = shapely.bounds(shapely.union_all(f.geometry.values).buffer(MAX_OUT))
    c0 = int(math.floor((x0 - g["x0"]) / res)); r0 = int(math.floor((g["y1"] - y1) / res))
    c0, r0 = max(0, c0), max(0, r0)
    c1 = min(G["ZS"].shape[1], int(math.ceil((x1 - g["x0"]) / res))); r1 = min(G["ZS"].shape[0], int(math.ceil((g["y1"] - y0) / res)))
    G["win"] = (r0, c0, r1 - r0, c1 - c0)
    return G["win"]


def glare_step(az, alt, res=2.0, stats=False):
    """one sun position → (known uint8 [weight × 100, max], unknown bool, per-tower lit m²) on the window grid"""
    Wl = G["walls"]
    r0, c0, wh, ww = G["win"]
    g = G["grid"]
    a = math.radians(az)
    sh = np.array([math.sin(a), math.cos(a)])                           # horizontal unit vector towards the sun
    tan = math.tan(math.radians(alt))
    dn = Wl["nx"] * sh[0] + Wl["ny"] * sh[1]
    lit = dn > 0.05                                                     # façade faces the sun
    idx = np.nonzero(lit)[0]
    known = np.zeros((wh, ww), dtype="uint8"); unk = np.zeros((wh, ww), dtype=bool)
    per = {}
    if not len(idx):
        return known, unk, per
    Lin = min(MAX_IN, (Wl["top"][idx].max() - 80) / tan)
    s_in = np.arange(S0, max(S0 + STEP, Lin), STEP)
    zmin_ground = 85.0
    Lout = min(MAX_OUT, (Wl["top"][idx].max() - zmin_ground) / tan)
    s_out = np.arange(S0, max(S0 + STEP, Lout), STEP)
    for k0 in range(0, len(idx), CHUNK):
        ii = idx[k0:k0 + CHUNK]
        x, y, nx, ny = Wl["x"][ii], Wl["y"][ii], Wl["nx"][ii], Wl["ny"][ii]
        # 1) lowest sunlit height of each façade sample (obstacles towards the sun)
        X = x[:, None] + s_in[None, :] * sh[0]; Y = y[:, None] + s_in[None, :] * sh[1]
        Z = S.sample(G["ZS"], X, Y, np.float32(-np.inf)).astype("float64")
        zlit = np.max(Z - s_in[None, :] * tan, axis=1)
        zlo = np.maximum(Wl["z0"][ii], zlit)
        ok = zlo < Wl["top"][ii] - 1.0
        if not ok.any():
            continue
        ii, x, y, nx, ny, zlo = ii[ok], x[ok], y[ok], nx[ok], ny[ok], zlo[ok]
        top = Wl["top"][ii]
        # 2) reflected direction and the march outward
        d = -sh
        dd = d[0] * nx + d[1] * ny
        rx, ry = d[0] - 2 * dd * nx, d[1] - 2 * dd * ny
        X = x[:, None] + s_out[None, :] * rx[:, None]; Y = y[:, None] + s_out[None, :] * ry[:, None]
        Z = S.sample(G["ZS"], X, Y, np.float32(np.inf)).astype("float64")
        T = Z + s_out[None, :] * tan
        M = np.maximum.accumulate(T, axis=1)
        Mprev = np.concatenate([np.full((len(ii), 1), -np.inf), M[:, :-1]], axis=1)
        hit = (T > Mprev + 0.05) & (T <= top[:, None]) & (T >= zlo[:, None]) & np.isfinite(T)
        if not hit.any():
            continue
        rr, cc = np.nonzero(hit)
        ix = ((X[rr, cc] - g["x0"]) / res).astype(np.int64) - c0
        iy = ((g["y1"] - Y[rr, cc]) / res).astype(np.int64) - r0
        inside = (ix >= 0) & (iy >= 0) & (ix < ww) & (iy < wh)
        rr, ix, iy = rr[inside], ix[inside], iy[inside]
        w = Wl["w"][ii][rr]; lev = Wl["lev"][ii][rr]
        kn = lev < 9
        np.maximum.at(known, (iy[kn], ix[kn]), np.round(w[kn] * 100).astype("uint8"))
        unk[iy[~kn], ix[~kn]] = True
        if stats:
            src = Wl["inv"][ii][rr]
            for t in np.unique(src[kn]):
                per[int(t)] = per.get(int(t), 0.0) + float((src[kn] == t).sum()) * res * res * 0.5
    # close the gaps between neighbouring rays
    known = np.where(known > 0, known, grey_dilation(known, size=3))
    unk = unk | (grey_dilation(unk.astype("uint8"), size=3) > 0)
    unk &= known == 0
    return known, unk, per


def polygons(known, unk, res):
    """window rasters → web features (lev, k, h) in EPSG:4326"""
    r0, c0, wh, ww = G["win"]
    g = G["grid"]
    lev = np.zeros(known.shape, dtype="int32")
    lev[(known > 0) & (known < 30)] = 1; lev[(known >= 30) & (known < 60)] = 2
    lev[(known >= 60) & (known < 90)] = 3; lev[known >= 90] = 4; lev[unk] = 9
    if not (lev > 0).any():
        return []
    rid = G["RID"][r0:r0 + wh, c0:c0 + ww]
    key = np.where(lev > 0, lev * 1_000_000 + (rid + 1), 0).astype("int32")
    tr = Affine(res, 0, g["x0"] + c0 * res, 0, -res, g["y1"] - r0 * res)
    geoms, keys = [], []
    for geom, v in features.shapes(key, mask=key > 0, transform=tr, connectivity=4):
        geoms.append(shapely.geometry.shape(geom)); keys.append(int(v))
    keys = np.array(keys)
    df = gpd.GeoDataFrame({"lev": keys // 1_000_000, "rid": keys % 1_000_000 - 1}, geometry=geoms, crs=25832)
    df["k"] = np.where(df.rid < 0, "g", "r")
    df["h"] = np.where(df.rid < 0, 0, np.round(G["rh"][np.maximum(df.rid.values, 0)]))
    df = df.dissolve(["lev", "k", "h"]).reset_index()
    df["geometry"] = shapely.make_valid(df.geometry.simplify(0.8).values)
    df = df[~df.geometry.is_empty]
    d4 = df.to_crs(4326)
    g4 = shapely.make_valid(shapely.transform(d4.geometry.values, lambda xy: np.round(xy, 5)))
    feats = []
    for row, geom in zip(df.itertuples(), g4):
        if geom is None or geom.is_empty:
            continue
        pr = {"lev": int(row.lev), "k": row.k}
        if row.k == "r":
            pr["h"] = float(row.h)
        feats.append({"type": "Feature", "properties": pr, "geometry": json.loads(shapely.to_geojson(geom))})
    return feats


def run(args):
    ti, az, alt, res, web = args
    known, unk, per = glare_step(az, alt, res, stats=True)
    r0, c0, wh, ww = G["win"]
    rid = G["RID"][r0:r0 + wh, c0:c0 + ww]
    strong = known >= 30                                                 # A1, A2, B
    cell = res * res
    ag = float((strong & (rid < 0)).sum() * cell); ar = float((strong & (rid >= 0)).sum() * cell)
    au = float(unk.sum() * cell); ac = float(((known > 0) & ~strong).sum() * cell)
    nb = int(len(np.unique(rid[strong & (rid >= 0)])))
    js = json.dumps({"type": "FeatureCollection", "features": polygons(known, unk, res)}, separators=(",", ":")) if web else None
    # 4 m day accumulation grid (hours of A1–B glare)
    s4 = strong[: wh // 2 * 2, : ww // 2 * 2].reshape(wh // 2, 2, ww // 2, 2).any(axis=(1, 3))
    return ti, js, ag, ar, ac, au, nb, per, np.packbits(s4)


def setup(B, res):
    f = gpd.read_parquet(B / "facades.parquet")
    c, r, reach = S.prepare(B, res)
    G["walls"] = walls(f)
    window(f, res)
    print(f"façade samples {len(G['walls']['x']):,} on {f.inv.nunique()} towers ({len(f)} parts) · window {G['win'][3]}×{G['win'][2]} cells", flush=True)
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", default="1,2,3,4,5,6,7,8,9,10,11,12")
    ap.add_argument("--step", type=int, default=30)
    ap.add_argument("--res", type=float, default=2.0)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--build", default="build")
    a = ap.parse_args()
    B = Path(a.build); web = Path("docs/data"); (web / "glare").mkdir(parents=True, exist_ok=True)
    setup(B, a.res)
    r0, c0, wh, ww = G["win"]
    g = G["grid"]
    stats = {"days": {}, "step_min": a.step, "res_m": a.res, "samples": int(len(G["walls"]["x"])),
             "window": [g["x0"] + c0 * a.res, g["y1"] - (r0 + wh) * a.res, g["x0"] + (c0 + ww) * a.res, g["y1"] - r0 * a.res]}
    tstats = {}
    for mo in [int(m) for m in a.months.split(",")]:
        steps = S.sun_times(mo, a.step)
        t0 = time.time()
        md = web / "glare" / f"{mo:02d}"; md.mkdir(parents=True, exist_ok=True)
        for fl in md.glob("*.json"):
            fl.unlink()
        acc = np.zeros((wh // 2, ww // 2), dtype="float32")
        rows = [None] * len(steps); hours = {}; per_m = {}
        jobs = [(i, az, alt, a.res, ts.minute == 0) for i, (ts, az, alt) in enumerate(steps)]
        with Pool(a.workers) as pool:
            for ti, js, ag, ar, ac, au, nb, per, pk in pool.imap_unordered(run, jobs, chunksize=1):
                ts, az, alt = steps[ti]
                acc += np.unpackbits(pk)[: acc.size].reshape(acc.shape) * (a.step / 60)
                rows[ti] = (round(ag / 1e4, 2), round(ar / 1e4, 2), round(ac / 1e4, 2), round(au / 1e4, 2), nb)
                for k, v in per.items():
                    per_m[k] = per_m.get(k, 0.0) + v * a.step / 60 / 1e4
                if js is not None:
                    (md / f"{ts.hour:02d}.json").write_text(js)
                    hours[ti] = {"t": ts.strftime("%H:%M"), "f": f"{ts.hour:02d}", "az": round(az, 1), "alt": round(alt, 1),
                                 "g": rows[ti][0], "r": rows[ti][1], "b": nb}
        hours = [hours[k] for k in sorted(hours)]
        (md / "index.json").write_text(json.dumps({"hours": hours}))
        np.save(B / f"glare_{mo:02d}.npy", acc)
        tstats[f"{mo:02d}"] = {k: round(v, 3) for k, v in per_m.items()}
        stats["days"][f"{mo:02d}"] = {
            "times": [ts.strftime("%H:%M") for ts, _, _ in steps],
            "ground_ha": [r[0] for r in rows], "roof_ha": [r[1] for r in rows], "weak_ha": [r[2] for r in rows],
            "unknown_ha": [r[3] for r in rows], "roofs_hit": [r[4] for r in rows],
            "km2_30min": round(float((acc >= 0.5).sum() * 16 / 1e6), 3), "km2_1h": round(float((acc >= 1).sum() * 16 / 1e6), 3),
            "km2_2h": round(float((acc >= 2).sum() * 16 / 1e6), 3), "max_h": round(float(acc.max()), 1),
            "peak": max(range(len(rows)), key=lambda i: rows[i][0] + rows[i][1]) if rows else None,
            "sec": round(time.time() - t0, 1)}
        print(f"glare month {mo:02d}: {len(steps)} steps, {time.time() - t0:.0f} s, ≥1 h: {stats['days'][f'{mo:02d}']['km2_1h']} km²", flush=True)
    np.save(B / "glare_meta.npy", np.array(stats["window"] + [4.0, ww // 2, wh // 2]))
    (B / "glare_tower_stats.json").write_text(json.dumps(tstats))
    p = web / "stats.json"
    s = json.loads(p.read_text()) if p.exists() else {}
    s["glare"] = stats
    p.write_text(json.dumps(s, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
