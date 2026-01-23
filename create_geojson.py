import requests
import json
import time

BASE_URL = "https://environment.data.gov.uk/flood-monitoring/id/floodAreas"

features = []
limit = 500
offset = 0

session = requests.Session()
session.headers.update({
    "Accept": "application/json",
    "User-Agent": "FloodAreaGeoJSONBuilder/1.0"
})

while True:
    print(f"Fetching offset {offset}...")

    r = session.get(
        BASE_URL,
        params={"_limit": limit, "_offset": offset},
        timeout=30
    )

    if r.status_code != 200:
        print(f"Stopped: HTTP {r.status_code}")
        break

    try:
        data = r.json()
    except ValueError:
        print("Stopped: response was not JSON")
        break

    items = data.get("items", [])
    if not items:
        print("No more items.")
        break

    for item in items:
        poly_url = item.get("polygon")
        if not poly_url:
            continue

        poly_resp = session.get(poly_url, timeout=30)
        if poly_resp.status_code != 200:
            continue

        try:
            geometry = poly_resp.json()
        except ValueError:
            continue

        features.append({
            "type": "Feature",
            "properties": {
                "floodAreaID": item.get("notation"),
                "floodAreaName": item.get("label"),
                "eaAreaName": item.get("eaAreaName"),
                "county": item.get("county"),
                "riverOrSea": item.get("riverOrSea"),
            },
            "geometry": geometry
        })

        # be polite to the API
        time.sleep(0.05)

    offset += limit

geojson = {
    "type": "FeatureCollection",
    "features": features
}

with open("Historic_Flood_Warnings/flood_areas.geojson", "w") as f:
    json.dump(geojson, f)

print(f"Saved {len(features)} flood area polygons")


import geopandas as gpd
import pandas as pd

# load polygons
polys = gpd.read_file("Historic_Flood_Warnings/flood_areas.geojson")

# load historic data
df = pd.read_excel("Historic_Flood_Warnings/202510 Historic Flood Warnings – EA.ods", engine="odf")
df["CODE"] = df["CODE"].astype(str).str.strip()

# frequency by historic code
freq = df.groupby("CODE").size().reset_index(name="frequency")

# join: historic CODE → current floodAreaID
joined = polys.merge(
    freq,
    left_on="floodAreaID",
    right_on="CODE",
    how="inner"
)

print(f"{len(joined)} polygons matched to historic records")
