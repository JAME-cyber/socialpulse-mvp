#!/usr/bin/env python3
"""Quick test: Overpass API for Annemasse area businesses"""
import urllib.request, urllib.parse, json

overpass_url = 'https://overpass-api.de/api/interpreter'

query = """
[out:json][timeout:30];
(
  node["amenity"="restaurant"](46.17,6.20,46.22,6.26);
  node["shop"="bakery"](46.17,6.20,46.22,6.26);
  node["amenity"="cafe"](46.17,6.20,46.22,6.26);
  node["craft"="hairdresser"](46.17,6.20,46.22,6.26);
  node["office"="accountant"](46.17,6.20,46.22,6.26);
  node["office"="lawyer"](46.17,6.20,46.22,6.26);
  node["shop"="florist"](46.17,6.20,46.22,6.26);
  node["shop"="car_repair"](46.17,6.20,46.22,6.26);
  node["healthcare"="physiotherapist"](46.17,6.20,46.22,6.26);
  way["amenity"="restaurant"](46.17,6.20,46.22,6.26);
  way["shop"="bakery"](46.17,6.20,46.22,6.26);
  way["shop"="florist"](46.17,6.20,46.22,6.26);
);
out body center;
"""

data = urllib.parse.urlencode({'data': query}).encode()
req = urllib.request.Request(overpass_url, data=data)

with urllib.request.urlopen(req, timeout=60) as resp:
    result = json.loads(resp.read().decode())

elements = result.get('elements', [])
print(f'Total POI trouvés: {len(elements)}')

with_website = [e for e in elements if 'tags' in e and e['tags'].get('website')]
without_website = [e for e in elements if 'tags' in e and not e['tags'].get('website') and e['tags'].get('name')]

print(f'Avec site web: {len(with_website)}')
print(f'SANS site web: {len(without_website)} ← TOP LEADS')
print()

for e in without_website[:15]:
    tags = e.get('tags', {})
    typ = tags.get('amenity', tags.get('shop', tags.get('office', tags.get('craft', tags.get('healthcare', '?')))))
    print(f'  📍 {tags.get("name", "?")} ({typ})  lat={e.get("lat", 0):.4f}, lon={e.get("lon", 0):.4f}')
