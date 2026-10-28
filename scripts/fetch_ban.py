"""Fetch today's fire-ban counties from the NÉBIH GeoServer and write ban.json for the page.

usage: python fetch_ban.py <out ban.json> [--raw <counties.geojson>] [--fallback <url of live ban.json>]

If NÉBIH is unreachable and --fallback is given, the currently published ban.json is reused
(marked stale) so a deploy never ships a page without ban data.
"""
import argparse
import datetime as dt
import json
import re
import sys
import urllib.request

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

WFS = ("https://tuzgyujtasitilalom.nebih.gov.hu/geoserver/nebih/ows?service=WFS&version=1.0.0&request=GetFeature"
       "&outputFormat=application/json&srsName=EPSG:4326&typeName=nebih:")
MONTHS = ["január", "február", "március", "április", "május", "június", "július", "augusztus",
          "szeptember", "október", "november", "december"]


def get_json(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "hu-fire-map (+https://github.com/Isainkov/hu-fire-map)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def rnd(geo):
    def r(c):
        return [r(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 4), round(c[1], 4)]
    geo = dict(geo)
    geo["coordinates"] = r(geo["coordinates"])
    return geo


def ban_date(label):
    # "2026. október 28." -> "2026-10-28"
    m = re.match(r"(\d{4})\.\s*(\S+)\s+(\d{1,2})", label or "")
    if not m or m.group(2).lower() not in MONTHS:
        return None
    return f"{m.group(1)}-{MONTHS.index(m.group(2).lower()) + 1:02d}-{int(m.group(3)):02d}"


def fresh(raw_path):
    counties = get_json(WFS + "NAPI_TUZTILALOM")
    title = get_json(WFS + "XE_TUZ_CIM")
    if raw_path:
        json.dump(counties, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False)
    feats = counties["features"]
    if len(feats) < 10:
        raise ValueError(f"NÉBIH returned only {len(feats)} counties")
    flags = {f["properties"]["NUTS3NAME"]: f["properties"]["NAPI_TUZVE"] == 1 for f in feats}
    banned = unary_union([shape(f["geometry"]) for f in feats if f["properties"]["NAPI_TUZVE"] == 1])
    label = title["features"][0]["properties"].get("ALCIM") if title["features"] else None
    return {
        "date": ban_date(label),
        "label": label,
        "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "stale": False,
        "counties": flags,
        "ban": rnd(mapping(banned.simplify(0.003, preserve_topology=True))) if not banned.is_empty else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--raw")
    ap.add_argument("--fallback")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        ban = fresh(a.raw)
    except Exception as e:
        print(f"NÉBIH fetch failed: {e}", file=sys.stderr)
        if not a.fallback:
            sys.exit(1)
        ban = get_json(a.fallback)
        ban["stale"] = True
        print("reusing published ban.json from", ban.get("fetched"), file=sys.stderr)
    json.dump(ban, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    on = sorted(k for k, v in ban["counties"].items() if v)
    print(f"ban {ban['label']} ({ban['date']}), stale={ban['stale']}: {len(on)} counties banned")


main()
