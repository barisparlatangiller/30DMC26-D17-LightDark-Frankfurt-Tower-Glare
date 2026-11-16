# Frankfurt Light & Dark · Shade and glare of the towers

**#30DayMapChallenge 2026 · Day 17 · Light & dark · Frankfurt**

🌍 **Live map:** https://barisparlatangiller.github.io/30DMC26-D17-LightDark-Frankfurt-Tower-Glare/ · all 30 maps: https://barisparlatangiller.github.io/

Frankfurt's towers cast shade (the **dark** side, from [Day 5](https://github.com/barisparlatangiller/30DMC26-D05-Sight-Frankfurt-HighRise-Shadows)).
Their glass façades also throw sunlight back onto streets and roofs (the **light** side, new here).
The map shows both, every hour on the 21st of each month, on the real rooftops of Hessen's LoD2 3D building model.

## Method

1. **Shadows (Day 5, unchanged).** Every LoD2 building part ≥ 30 m casts a shadow onto every roof (LoD2 roof planes)
   and the ground; `pipeline/shadows.py`.
2. **Façade inventory.** Every tower of 58 m and more (81 towers, Wikipedia list) was classed from its German Wikipedia
   article text and lead photo: **A1** full mirror-like glass (weight 1.0) · **A2** full lighter glass / double skin (0.75) ·
   **B** mixed, window bands, metal or stone frames (0.45) · **C** mostly stone, brick or matt metal (0.15) · **U** not
   verified (separate layer). `data/frankfurt_facade_inventory_v2.xlsx` → `data/facade_inventory.csv`
   (`pipeline/make_inventory_csv.py`, coordinates from the Wikipedia list).
3. **Matching.** Inventory → LoD2 buildings by OpenStreetMap name, else by coordinate (≤ 60 m) and height (gap < 30 %);
   `pipeline/match_facades.py`.
4. **Reflections ("reverse shadows").** A vertical glass wall is a mirror: sunlight arriving at altitude α leaves at the
   same α, going down, mirrored across the wall (`r = d − 2(d·n)n`). For every façade sample (1.5 m) a surface point at
   distance s along r is lit when `T(s) = z(s) + s·tan α` lies between the lowest sunlit façade height and the façade top
   and exceeds every earlier `T` (nothing hit first). The sunlit height comes from the same test towards the sun.
   Both use the 2 m surface of LoD2 roofs and ground, so towers, low buildings and terrain block; `pipeline/reflections.py`.
5. **Day totals.** Hours of reflected sun from A1/A2/B façades, 30-minute steps, 4 m grid.

## Limits

Façades are flat vertical mirrors with one relative weight per tower (not measured reflectance; real glass reflects
more at grazing angles). Curved towers follow their LoD2 outline. Light hitting a wall is drawn at the roof edge.
Clear sky. Towers newer than the LoD2 model (Four, ONE, The Spin, Eden, FAZ-Tower …) are missing. Buildings of
30–58 m have no façade class yet. The result shows **where reflected sunlight can land**, not measured glare or heat.

## Build

```bash
pip install -r requirements.txt   # + tippecanoe, ffmpeg
python pipeline/fetch_lod2.py && python pipeline/lod2_to_buildings.py && python pipeline/fetch_osm_names.py
python pipeline/build_casters.py && python pipeline/match_facades.py
python pipeline/shadows.py && python pipeline/reflections.py
python pipeline/build_web.py && python pipeline/video.py
```

The GitHub Action runs all of it and deploys `docs/` to Pages; result files (GeoJSON, rasters, video, logs) go to the
`data` branch.

## Data & licences

3D-Gebäudemodelle LoD2 © HVBG Hessen, dl-de/zero-2-0 · Wikipedia (heights, coordinates, façade descriptions), CC BY-SA 4.0 ·
names © OpenStreetMap contributors, ODbL · sun positions: pvlib (NREL SPA).

Barış Parlatangiller · built with AI assistance (Claude, Anthropic) · code MIT (see LICENSE)
