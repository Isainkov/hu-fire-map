"""Assemble the static site.

usage: python build.py <ban.json> <out dir>
Inlines Leaflet's CSS into src/template.html and copies the OSM data, venues and ban file next to it.
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ban, out = sys.argv[1:3]
os.makedirs(out, exist_ok=True)

tpl = open(os.path.join(ROOT, "src", "template.html"), encoding="utf-8").read()
css = open(os.path.join(ROOT, "vendor", "leaflet.css"), encoding="utf-8").read()
page = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        + tpl.replace("/*LEAFLET_CSS*/", css) + "\n</html>\n")
open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(page)

for src, name in [(os.path.join(ROOT, "data", "osm", "data.json"), "data.json"),
                  (os.path.join(ROOT, "data", "osm", "forest.png"), "forest.png"),
                  (os.path.join(ROOT, "data", "venues.json"), "venues.json"),
                  (ban, "ban.json")]:
    shutil.copy(src, os.path.join(out, name))
print("built", out, sorted(os.listdir(out)))
