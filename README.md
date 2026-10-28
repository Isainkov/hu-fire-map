# Hungary Fire Pit Map

Where in Hungary you can light a fire today: fire pits and barbecues from OpenStreetMap, checked against the daily fire ban published by NÉBIH ([erdotuz.hu](https://erdotuz.hu)), plus places in Budapest that rent out grills. English, Hungarian and Ukrainian.

**Live:** https://isainkov.github.io/hu-fire-map/

## How it updates

| What | How often | Workflow |
| --- | --- | --- |
| Fire ban by county (NÉBIH GeoServer) | every 30 minutes | `deploy.yml` |
| Fire pits, roads, forests (Geofabrik OSM extract) | weekly, Monday 03:15 UTC | `osm.yml` |

NÉBIH's server doesn't allow cross-origin requests, so the browser can't read the ban directly. `deploy.yml` fetches it on a schedule and redeploys the static site. If NÉBIH is down, the last published `ban.json` is reused and the page says so.

## Data processing

- `scripts/extract.py` reads the Hungary `.osm.pbf` and writes fire pits (`leisure=firepit`, `amenity=bbq`), a light vector basemap and a forest mask (`data/osm/`).
- `scripts/roads.py` adds the straight-line distance to the nearest road open to cars and to the nearest parking. It also drops fire pits that sit in a private yard: tagged `access=private`, or inside residential land or within 20 m of a house with no sign of a public place nearby. Forest tracks don't count as roads because Hungarian law closes them to motor vehicles unless a sign says otherwise.
- `scripts/fetch_ban.py` writes `ban.json` (county flags and the banned area).
- `scripts/build.py` assembles `_site/`.
- `data/venues.json` holds the grill rentals, collected by hand from We Love Budapest articles (2016–2023). Prices are old.

Local build:

```bash
pip install osmium shapely pillow
curl -sSfLo hungary.osm.pbf https://download.geofabrik.de/europe/hungary-latest.osm.pbf
python scripts/fetch_ban.py ban.json --raw counties.geojson
python scripts/extract.py hungary.osm.pbf counties.geojson data/osm
python scripts/roads.py hungary.osm.pbf data/osm/data.json
python scripts/build.py ban.json _site
```

## Caveats

OSM points are mapped by volunteers and not verified: a fire pit may be gone. Even without a ban, Hungarian law allows fire in forests and within 200 m of them only at a built fire pit. Always check erdotuz.hu before you go.

Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL. Fire ban data: NÉBIH.
