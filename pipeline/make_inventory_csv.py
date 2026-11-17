"""xlsx (Bina envanteri) + Wikipedia list coordinates → data/facade_inventory.csv"""
import json, sys, csv, openpyxl
xl, coords, out = sys.argv[1:4]
C = json.load(open(coords))
K = {1:'Commerzbank Tower',2:'Messeturm',3:'Four 1',4:'Four 2',5:'Four 3',6:'Four 4',7:'Westendstraße 1',8:'Main Tower',9:'Tower 185',
10:'One',11:'Trianon',12:'Omniturm',13:'EZB',14:'Grand Tower',15:'Opernturm',16:'Taunusturm',17:'Silberturm',18:'Westend Gate',19:'Deutsche Bank I',
20:'Deutsche Bank II',21:'Marienturm',22:'Skyper',23:'Eurotower',24:'City-Haus I',25:'Frankfurter Büro Center',26:'Neuer Henninger-Turm',27:'One Forty West',
28:'Gallileo',29:'Nextower',30:('Nextower',99),31:'Kastor',32:'Pollux',33:'Garden Tower',34:'Messe Torhaus',35:'Japan Center',36:'Park Tower',37:'Westhafen Tower',
38:'Eurotheum',39:'IBC',40:'WinX',41:'Maintor Panorama',42:'Global Tower',44:'Eden',45:'WestendDuo',46:'160 Park View',47:'Commerzbank Trading Center',
48:'Union Investment',49:'Main Plaza',50:'Bürohaus Alte Oper',51:'Rhein-Main-Center',52:'Central Parx',53:'Main Forum',54:'Taunusanlage 11',55:'K26',56:'Turm Center',
57:'Finanz-Informatik',58:'Cielo',59:'Hochhaus am Turm',60:'Blue Horizon',61:'Taunusanlage 8',62:'Romeo & Julia',63:'InterContinental',65:'Skylight',66:'KfW-Hochhaus',
69:'Praedium',70:'FAZ-Tower',71:'NM-1',72:'The Spin',73:'Europa-Allee-Tower',74:'City Gate',75:'Senckenberg-Turm',76:'Leonardo Royal',77:'Arabella Center',
78:'Radisson Blu',80:'Campus Tower',81:'American Express',82:'St Martin Tower',83:'Alpha Rotex',84:'Ehem. DB-Hauptverwaltung',85:'Taunusturm Residential',86:'Main Triangel'}
ws = openpyxl.load_workbook(xl)['Bina envanteri']
W = {'A1':1.0,'A2':0.75,'B':0.45,'C':0.15,'U':0.5}
rows = []
for r in ws.iter_rows(min_row=2, values_only=True):
    i, name, h = r[0], r[1], r[2]
    if i not in K: continue
    k = K[i]; hh = h
    if isinstance(k, tuple): k, hh = k
    lat, lon, hw = C[k]
    cls = r[18]
    rows.append(dict(id=i, name=name, h=hh, lat=lat, lon=lon, cls=cls, w=W[cls], facade=r[12] or '', look=r[14] or '',
                     geom=r[15] or '', conf=r[8], evidence=r[20] or '', src=r[22] or ''))
# English labels for the web (the inventory itself is in Turkish)
import os
tp = os.path.join(os.path.dirname(coords), "translations_en.json")
if os.path.exists(tp):
    TR = json.load(open(tp))
    for row in rows:
        for k in ("name", "facade", "look", "geom", "conf", "evidence"):
            v = row[k]
            if v in TR.get(k, {}):
                row[k] = TR[k][v]
            elif v and k != "name" and any(ch in str(v) for ch in "çğıöşüÇĞİÖŞÜ"):
                raise SystemExit(f"no English label for {k}: {v}")
with open(out, 'w', newline='') as f:
    wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
print(len(rows), 'rows')
