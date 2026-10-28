"""Enrich data.json points: car access (nearest legal road, nearest parking) and whether the spot sits in someone's yard.

usage: python roads.py <hungary.osm.pbf> <data.json>
"""
import json
import math
import sys
from collections import Counter

import osmium
from shapely import STRtree, wkb
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Point

PBF, DATA = sys.argv[1:3]
data = json.load(open(DATA, encoding="utf-8"))
points = data["points"]

# local equirectangular metres (error < 1% over Hungary for distances of a few km)
KX = 111320 * math.cos(math.radians(47.2))
KY = 110574


def xy(lon, lat):
    return lon * KX, lat * KY


def to_m(geom):
    return affine_transform(geom, [KX, 0, 0, KY, 0, 0])


CELL = 0.02  # ~1.5-2 km grid; keep only features near some firepit
cells = set()
for p in points:
    cx, cy = int(p["lon"] // CELL), int(p["lat"] // CELL)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            cells.add((cx + dx, cy + dy))


def near(lon, lat):
    return (int(lon // CELL), int(lat // CELL)) in cells


ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street",
         "service", "road", "primary_link", "secondary_link", "tertiary_link", "trunk_link"}
CLOSED = {"no", "private", "forestry", "agricultural", "delivery", "permit", "military", "emergency", "official"}
OPEN = {"yes", "permissive", "destination", "designated", "customers"}

HOME_LANDUSE = {"residential", "farmyard", "allotments", "garages"}
PUBLIC_LEISURE = {"park", "recreation_ground", "nature_reserve", "picnic_site", "common", "playground", "camp_site"}
PUBLIC_TOURISM = {"picnic_site", "camp_site", "viewpoint", "attraction"}
PUBLIC_NODES = {("tourism", "picnic_site"), ("leisure", "picnic_table"), ("amenity", "shelter"), ("tourism", "viewpoint"),
                ("information", "guidepost"), ("tourism", "information"), ("amenity", "bench")}
NOT_HOME_BUILDINGS = {"shelter", "roof", "hut", "cabin", "toilets", "kiosk", "chapel", "church", "ruins"}


def car_ok(tags):
    hw = tags.get("highway")
    mv = tags.get("motor_vehicle") or tags.get("motorcar") or tags.get("vehicle")
    acc = tags.get("access")
    if hw == "track":
        # Hungarian forest tracks are closed to cars unless explicitly opened
        return (mv or acc) in OPEN
    if hw not in ROADS:
        return False
    if mv in CLOSED or (mv is None and acc in CLOSED):
        return False
    if hw == "service" and tags.get("service") == "driveway" and acc != "yes":
        return False
    return True


wkbf = osmium.geom.WKBFactory()


class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.lines, self.parks = [], []
        self.home, self.public, self.buildings, self.public_nodes = [], [], [], []

    def node(self, n):
        if not n.location.valid() or not near(n.location.lon, n.location.lat):
            return
        tags = n.tags
        if tags.get("amenity") == "parking" and tags.get("access") not in CLOSED:
            self.parks.append(Point(xy(n.location.lon, n.location.lat)))
        if any(tags.get(k) == v for k, v in PUBLIC_NODES):
            self.public_nodes.append(Point(xy(n.location.lon, n.location.lat)))

    def way(self, w):
        tags = w.tags
        if not car_ok(tags):
            return
        coords = [(nd.lon, nd.lat) for nd in w.nodes if nd.location.valid()]
        if len(coords) < 2 or not any(near(x, y) for x, y in coords):
            return
        self.lines.append(LineString([xy(x, y) for x, y in coords]))

    def area(self, a):
        tags = a.tags
        b = tags.get("building")
        home = tags.get("landuse") in HOME_LANDUSE or (tags.get("leisure") == "garden" and tags.get("garden:type") == "residential")
        public = (tags.get("leisure") in PUBLIC_LEISURE or tags.get("tourism") in PUBLIC_TOURISM
                  or tags.get("landuse") in ("forest", "recreation_ground", "cemetery") or tags.get("natural") in ("wood", "scrub", "grassland"))
        park = tags.get("amenity") == "parking" and tags.get("access") not in CLOSED
        building = b is not None and b not in NOT_HOME_BUILDINGS and tags.get("amenity") != "shelter"
        if not (home or public or park or building):
            return
        try:
            geom = wkb.loads(wkbf.create_multipolygon(a), hex=True)
        except Exception:
            return
        c = geom.representative_point()
        if not near(c.x, c.y):
            return
        g = to_m(geom)
        if park:
            self.parks.append(g.centroid)
        if building:
            self.buildings.append(g)
        if home:
            self.home.append(g)
        if public:
            self.public.append(g)


h = H()
h.apply_file(PBF, locations=True, idx="flex_mem")

road_tree = STRtree(h.lines)
park_tree = STRtree(h.parks)
bld_tree = STRtree(h.buildings)
home_tree = STRtree(h.home)
pub_tree = STRtree(h.public)
pubn_tree = STRtree(h.public_nodes)


def within(tree, geoms, pt, dist=0):
    idx = tree.query(pt.buffer(dist) if dist else pt, predicate="intersects")
    return len(idx) > 0


reasons = Counter()
for p in points:
    pt = Point(xy(p["lon"], p["lat"]))
    i = road_tree.nearest(pt)
    p["road"] = round(pt.distance(h.lines[i])) if i is not None else None
    j = park_tree.nearest(pt)
    p["park"] = round(pt.distance(h.parks[j])) if j is not None else None

    t = p["tags"]
    acc = t.get("access")
    in_home = within(home_tree, h.home, pt)
    by_house = within(bld_tree, h.buildings, pt, 20)
    public = (acc in ("yes", "permissive", "designated", "public") or bool(t.get("name")) or bool(t.get("description"))
              or within(pub_tree, h.public, pt) or within(pubn_tree, h.public_nodes, pt, 50))
    if acc in ("private", "no"):
        p["private"], why = True, "tagged"
    elif acc == "customers":
        p["private"], why = False, "guests"
        p["guests"] = True
    elif (in_home or by_house) and not public:
        p["private"], why = True, "yard" if in_home else "house"
    else:
        p["private"], why = False, "public" if public else "unknown"
    reasons[why] += 1

free = [p for p in points if not p["banned"] and not p["private"]]
# fire pits in someone's yard are never published
data["points"] = [p for p in points if not p["private"]]
json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("reasons", dict(reasons))
print("not banned & not private:", len(free), "of", len(points))
for lim in (30, 100, 300):
    print(f"<= {lim} m road: {sum(1 for p in free if p['road'] is not None and p['road'] <= lim)}")
print("roads", len(h.lines), "parkings", len(h.parks), "buildings", len(h.buildings), "home", len(h.home), "public", len(h.public), "pubnodes", len(h.public_nodes))
