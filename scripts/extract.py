"""Firepits + light basemap from a Hungary .pbf, classified against the NÉBIH daily fire-ban counties.

usage: python extract.py <hungary.osm.pbf> <NAPI_TUZTILALOM.json> <out_dir>
writes data.json (points, ban, basemap vectors) and forest.png (forest mask overlay)
"""
import base64
import io
import json
import math
import os
import sys
from collections import Counter

import osmium
from PIL import Image, ImageDraw
from shapely import wkb
from shapely.geometry import shape, Point, LineString, mapping, box
from shapely.ops import unary_union, linemerge
from shapely.prepared import prep

PBF, BAN, OUT = sys.argv[1:4]
BUDAPEST = (47.4979, 19.0402)
RADIUS_KM = 10000  # whole country
S, N, W, E = 45.68, 48.62, 16.05, 22.98
BBOX = box(W, S, E, N)

# forest raster in Web Mercator so Leaflet's ImageOverlay lines up exactly
IMG_W = 3600


def merc_y(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


Y0, Y1 = merc_y(N), merc_y(S)
IMG_H = round(IMG_W * (Y1 - Y0) / (math.radians(E) - math.radians(W)) * -1)


def px(lon, lat):
    return ((lon - W) / (E - W) * IMG_W, (merc_y(lat) - Y0) / (Y1 - Y0) * IMG_H)


def km(lat, lon):
    dlat = math.radians(lat - BUDAPEST[0])
    dlon = math.radians(lon - BUDAPEST[1])
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(BUDAPEST[0])) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def kind(tags):
    if tags.get("leisure") == "firepit":
        return "firepit"
    if tags.get("amenity") == "bbq":
        return "bbq"
    return None


KEEP = ("name", "access", "fuel", "covered", "description", "opening_hours", "fee", "operator")
RIVERS = {"Duna", "Tisza", "Zagyva", "Rába", "Sió", "Ipoly", "Dráva", "Sajó", "Hármas-Körös", "Kis-Duna", "Ráckevei-Duna", "Mosoni-Duna"}

forest = Image.new("L", (IMG_W, IMG_H), 0)
fdraw = ImageDraw.Draw(forest)
wkbf = osmium.geom.WKBFactory()


class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.items, self.towns, self.rivers, self.roads, self.lakes, self.counties = [], [], [], [], [], []

    def add(self, t, oid, lat, lon, tags):
        k = kind(tags)
        if not k or km(lat, lon) > RADIUS_KM:
            return
        self.items.append({"id": f"{t}/{oid}", "k": k, "lat": round(lat, 6), "lon": round(lon, 6),
                           "tags": {key: tags[key] for key in KEEP if key in tags}})

    def node(self, n):
        if kind(n.tags) and n.location.valid():
            self.add("node", n.id, n.location.lat, n.location.lon, n.tags)
        place = n.tags.get("place")
        if place in ("city", "town", "village") and "name" in n.tags and n.location.valid():
            lat, lon = n.location.lat, n.location.lon
            if S < lat < N and W < lon < E:
                try:
                    pop = int(n.tags.get("population", "0").replace(" ", ""))
                except ValueError:
                    pop = 0
                self.towns.append({"n": n.tags["name"], "lat": round(lat, 4), "lon": round(lon, 4), "p": pop, "c": place == "city", "v": place == "village"})

    def way(self, w):
        tags = w.tags
        if kind(tags):
            pts = [(nd.lat, nd.lon) for nd in w.nodes if nd.location.valid()]
            if pts:
                self.add("way", w.id, sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), tags)
        hw = tags.get("highway")
        river = tags.get("waterway") == "river" and tags.get("name") in RIVERS
        if hw in ("motorway", "trunk") or river:
            try:
                line = LineString([(nd.lon, nd.lat) for nd in w.nodes if nd.location.valid()])
            except Exception:
                return
            if line.is_empty or not line.intersects(BBOX):
                return
            (self.rivers if river else self.roads).append((hw or "river", line))

    def area(self, a):
        tags = a.tags
        is_forest = tags.get("landuse") == "forest" or tags.get("natural") == "wood"
        is_water = tags.get("natural") == "water" and tags.get("water") in (None, "lake", "reservoir", "oxbow")
        is_county = tags.get("boundary") == "administrative" and tags.get("admin_level") == "6" and not a.from_way()
        if not (is_forest or is_water or is_county):
            return
        try:
            geom = wkb.loads(wkbf.create_multipolygon(a), hex=True)
        except Exception:
            return
        if not geom.intersects(BBOX):
            return
        if is_forest:
            for poly in geom.geoms:
                fdraw.polygon([px(x, y) for x, y in poly.exterior.coords], fill=255)
                for hole in poly.interiors:
                    fdraw.polygon([px(x, y) for x, y in hole.coords], fill=0)
        elif is_water:
            if geom.area > 0.0008:  # ~ 6 km² and up: Balaton, Velencei-tó, Tisza-tó
                self.lakes.append(geom.simplify(0.002))
        else:
            self.counties.append((tags.get("name", ""), geom))


ban = json.load(open(BAN, encoding="utf-8"))
ban_counties = [(f["properties"]["NUTS3NAME"], f["properties"]["NAPI_TUZVE"] == 1, shape(f["geometry"])) for f in ban["features"]]

h = H()
h.apply_file(PBF, locations=True, idx="flex_mem")

prepared = [(name, banned, prep(g)) for name, banned, g in ban_counties]
osm_counties = [(name, prep(g)) for name, g in h.counties]
for it in h.items:
    p = Point(it["lon"], it["lat"])
    hit = next(((name, banned) for name, banned, g in prepared if g.contains(p)), None)
    if hit is None:
        # counties missing from the NÉBIH layer have no ban today
        name = next((n for n, g in osm_counties if g.contains(p)), None)
        hit = ((name or "").replace(" vármegye", "").replace(" megye", "") or None, False)
    if hit[0] is None:
        # on a border line after simplification: take the nearest NÉBIH county
        name, banned, _ = min(ban_counties, key=lambda c: c[2].distance(p))
        hit = (name, banned)
    near = min(h.towns, key=lambda t: (t["lat"] - it["lat"]) ** 2 + ((t["lon"] - it["lon"]) * 0.68) ** 2)
    it["near"] = near["n"]
    it["county"], it["banned"] = hit
    it["km"] = round(km(it["lat"], it["lon"]), 1)


def rnd(geo):
    def r(c):
        return [r(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 4), round(c[1], 4)]
    geo = dict(geo)
    geo["coordinates"] = r(geo["coordinates"])
    return geo


banned_union = unary_union([g for _, b, g in ban_counties if b]).simplify(0.003, preserve_topology=True)
county_lines = linemerge(unary_union([g.boundary for _, g in h.counties]).intersection(BBOX)).simplify(0.004)
rivers = linemerge(unary_union([l for _, l in h.rivers])).intersection(BBOX).simplify(0.002)
roads = linemerge(unary_union([l for _, l in h.roads])).intersection(BBOX).simplify(0.003)
lakes = unary_union(h.lakes)

out = {
    "date": ban.get("timeStamp"),
    "bounds": [[S, W], [N, E]],
    "free_counties": sorted({n for n, b, _ in ban_counties if not b}),
    "ban": rnd(mapping(banned_union)),
    "county_lines": rnd(mapping(county_lines)),
    "rivers": rnd(mapping(rivers)),
    "roads": rnd(mapping(roads)),
    "lakes": rnd(mapping(lakes)),
    "towns": sorted(h.towns, key=lambda t: -t["p"]),
    "points": sorted(h.items, key=lambda i: i["km"]),
}
os.makedirs(OUT, exist_ok=True)
json.dump(out, open(os.path.join(OUT, "data.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

# 1-bit-ish mask: forest pixels opaque, rest transparent; colour is applied in the page
rgba = Image.new("LA", forest.size, 0)
rgba.putalpha(forest)
rgba.save(os.path.join(OUT, "forest.png"), optimize=True)

free = [i for i in h.items if not i["banned"]]
print(f"total {len(h.items)}, outside ban {len(free)}; towns {len(h.towns)}, counties {len(h.counties)}, lakes {len(h.lakes)}")
sys.stdout.reconfigure(encoding="utf-8")
print(Counter((i["county"], i["k"]) for i in free).most_common())
print("png", os.path.getsize(os.path.join(OUT, "forest.png")), "json", os.path.getsize(os.path.join(OUT, "data.json")))
