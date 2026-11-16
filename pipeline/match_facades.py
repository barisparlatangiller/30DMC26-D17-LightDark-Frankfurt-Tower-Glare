"""
Join the façade inventory (data/facade_inventory.csv: 81 towers of 58 m and more, façade class A1/A2/B/C/U from
Wikipedia text + photo checks) to the LoD2 towers (build/casters.parquet).

For every inventory row: LoD2 buildings (ALKIS oid) within 90 m of the Wikipedia coordinate are candidates; the one
whose tallest part is closest to the published height wins (score = relative height gap + distance / 200 m), if
the gap is under 30 %. Tallest first, each building used once. All parts ≥ 30 m of a matched building take its class.

  python pipeline/match_facades.py
Output  build/facades.parquet (caster parts with cls, w, inv) · docs/data/glass.geojson · stats.json["facades"]
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

B, WEB = Path("build"), Path("docs/data")
# inventory id → OpenStreetMap building name(s) as joined to the LoD2 towers (more reliable than coordinates,
# which can be 50–90 m off in the Wikipedia list). Every LoD2 building carrying that name is matched.
OSM_NAMES = {1: ["Commerzbank Tower"], 7: ["Westend Tower", "Westend 1"], 9: ["Tower 185"], 13: ["Europäische Zentralbank"],
             11: ["Trianon"], 12: ["Omniturm"], 14: ["Grand Tower"], 16: ["TaunusTurm"], 15: ["OpernTurm"], 17: ["Silberturm"],
             18: ["WestendGate"], 22: ["Skyper"], 21: ["Marienturm"], 23: ["Eurotower"], 25: ["FBC Hochhaus"], 24: ["City Haus I"],
             26: ["Henninger Turm"], 32: ["Pollux"], 31: ["Kastor"], 33: ["Garden Tower"], 37: ["Westhafen Tower"], 39: ["IBC Tower"],
             40: ["Winx"], 35: ["Japan Center"], 42: ["Global Tower"], 38: ["Eurotheum"], 45: ["WestendDuo"], 47: ["Commerzbank DLZ 5"],
             50: ["Bürohaus an der Alten Oper"], 80: ["Campus Tower"], 55: ["K26"], 83: ["Alpha Rotex"], 62: ["Romeo & Julia"]}
MAX_D = 60.0


def main():
    c = gpd.read_parquet(B / "casters.parquet")
    inv = pd.read_csv("data/facade_inventory.csv")
    pts = gpd.GeoSeries(gpd.points_from_xy(inv.lon, inv.lat), crs=4326).to_crs(25832)
    g = c.dissolve("oid", aggfunc={"h": "max"}).reset_index()
    sidx = g.sindex
    used, rows, how = set(), [], {}
    pair = {}                                                            # oid → inventory id
    for k in inv.index:                                                  # 1) by OSM name
        names = OSM_NAMES.get(int(inv.id[k]))
        if not names:
            continue
        oids = [o for o in c[c.name.isin(names)].oid.unique() if o not in used]
        for o in oids:
            used.add(o); pair[o] = int(inv.id[k])
        if oids:
            hh = float(g[g.oid.isin(oids)].h.max())
            rows.append(dict(inv=int(inv.id[k]), name=inv["name"][k], cls=inv.cls[k], oid=";".join(oids), h_lod2=round(hh, 1),
                             gap=round(abs(hh - inv.h[k]) / inv.h[k] * 100, 1), dist=0.0, by="OSM name"))
    done = {r["inv"] for r in rows}
    for k in inv.sort_values("h", ascending=False).index:                # 2) by coordinate + height
        r, p = inv.loc[k], pts[k]
        if int(r.id) in done:
            continue
        cand = sidx.query(p.buffer(MAX_D), predicate="intersects")
        best = None
        for j in cand:
            if g.oid[j] in used:
                continue
            gap = abs(g.h[j] - r.h) / r.h
            d = g.geometry[j].distance(p)
            s = gap + d / 200
            if gap < 0.30 and (best is None or s < best[0]):
                best = (s, j, gap, d)
        if best is None:
            rows.append(dict(inv=int(r.id), name=r["name"], cls=r.cls, oid=None, h_lod2=None, gap=None, dist=None, by="not in LoD2"))
            continue
        _, j, gap, d = best
        used.add(g.oid[j]); pair[g.oid[j]] = int(r.id)
        rows.append(dict(inv=int(r.id), name=r["name"], cls=r.cls, oid=g.oid[j], h_lod2=round(float(g.h[j]), 1),
                         gap=round(gap * 100, 1), dist=round(d, 1), by="coordinate + height"))
    m = pd.DataFrame(rows)
    ok = m[m.oid.notna()]
    print(m.to_string())
    print(f"matched {len(ok)} of {len(m)} inventory towers to LoD2")
    inv_by = inv.set_index("id")
    f = c[c.oid.isin(pair)].copy(); f["inv"] = f.oid.map(pair)
    f["cls"] = f.inv.map(inv_by.cls); f["w"] = f.inv.map(inv_by.w); f["iname"] = f.inv.map(inv_by["name"])
    f.to_parquet(B / "facades.parquet")
    # web: matched towers with their façade class (dissolved per inventory row)
    d = f.dissolve("inv", aggfunc={"h": "max"}).reset_index()
    d = d.merge(inv[["id", "name", "cls", "w", "facade", "look", "geom", "conf", "evidence", "src"]], left_on="inv", right_on="id")
    d4 = d.to_crs(4326)
    feats = []
    for r in d4.itertuples():
        pr = {"i": int(r.inv), "n": r.name, "c": r.cls, "w": float(r.w), "h": round(float(r.h), 1),
              "f": r.facade if isinstance(r.facade, str) else "", "lk": r.look if isinstance(r.look, str) else "",
              "g": r.geom if isinstance(r.geom, str) else "", "cf": r.conf, "ev": r.evidence if isinstance(r.evidence, str) else "",
              "s": r.src if isinstance(r.src, str) else ""}
        feats.append({"type": "Feature", "properties": pr, "geometry": r.geometry.__geo_interface__})
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "glass.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")))
    st = {"inventory": int(len(inv)), "matched": int(len(ok)), "parts": int(len(f)),
          "by_class": {k: int(v) for k, v in ok.cls.value_counts().items()},
          "unmatched": m[m.oid.isna()].name.tolist(), "table": m.drop(columns="oid").to_dict("records"),
          "towers_without_inventory": int(c.oid.nunique() - len(pair))}
    p = WEB / "stats.json"
    s = json.loads(p.read_text()) if p.exists() else {}
    s["facades"] = st
    p.write_text(json.dumps(s, ensure_ascii=False, indent=1))
    print(json.dumps(st, ensure_ascii=False))


if __name__ == "__main__":
    main()
