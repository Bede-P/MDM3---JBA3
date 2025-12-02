"""
Generate interactive map of flood outlines for a recent time range based on Folium
"""

import json
import os
from datetime import datetime
from pathlib import Path

from pyproj import Transformer

def _parse_start_year(date_str: str):
    """Extract year from start_date attribute"""
    if not date_str:
        return None

    try:
        normalized = date_str.replace("T", " ").split(".")[0]
        return datetime.fromisoformat(normalized).year
    except Exception:
        try:
            return int(date_str[:4])
        except Exception:
            return None


def _filter_features_by_year_range(features, start_year: int, end_year: int):
    """Filter flood features for given year range and count events per year"""
    filtered = []
    counts = {}

    for feature in features:
        props = feature.get("properties", {})
        year = _parse_start_year(props.get("start_date", ""))

        if year is None:
            continue

        if start_year <= year <= end_year:
            props["start_year"] = year
            filtered.append(feature)
            counts[year] = counts.get(year, 0) + 1

    return filtered, counts


def _transform_geometry_coordinates(coords, transformer, bounds):
    """Recursively transform coordinates and update bounds"""
    if not coords:
        return coords

    if isinstance(coords[0], (int, float)):
        lon, lat = transformer.transform(coords[0], coords[1])
        bounds["min_lon"] = min(bounds["min_lon"], lon)
        bounds["max_lon"] = max(bounds["max_lon"], lon)
        bounds["min_lat"] = min(bounds["min_lat"], lat)
        bounds["max_lat"] = max(bounds["max_lat"], lat)
        return [lon, lat]

    return [
        _transform_geometry_coordinates(point, transformer, bounds)
        for point in coords
        if point
    ]


def _convert_features_to_wgs84(features, transformer):
    """Convert coordinates of all features to WGS84 and return bounds"""
    bounds = {
        "min_lon": float("inf"),
        "max_lon": float("-inf"),
        "min_lat": float("inf"),
        "max_lat": float("-inf"),
    }

    for feature in features:
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates")

        if not coords:
            continue

        geometry["coordinates"] = _transform_geometry_coordinates(
            coords, transformer, bounds
        )

    if bounds["min_lon"] == float("inf"):
        return None

    return bounds


def _estimate_zoom_level(bounds):
    """Estimate appropriate initial zoom level based on lat/lon range"""

    lon_span = bounds["max_lon"] - bounds["min_lon"]
    lat_span = bounds["max_lat"] - bounds["min_lat"]
    span = max(lon_span, lat_span)

    if span <= 0.5:
        return 11
    if span <= 1.5:
        return 10
    if span <= 3:
        return 9
    if span <= 6:
        return 8
    if span <= 12:
        return 7
    return 6


def create_recent_25_years_map(
    flood_file: str = "Recorded_Flood_Outlines.geojson",
    start_year: int = 2000,
    end_year: int = 2025,
    output_file: str = None,
):
    """Generate flood outline map for given year range"""
    try:
        import folium
        from folium import plugins
        from branca.colormap import LinearColormap
    except ImportError:
        print("[ERROR] Need to install folium and branca")
        print("Please run: pip install folium branca")
        return

    if output_file is None:
        output_file = f"flood_map_{start_year}_{end_year}.html"

    if not os.path.exists(flood_file):
        print(f"[ERROR] Cannot find file: {flood_file}")
        return

    print("Loading flood data...")
    with open(flood_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    filtered_features, counts = _filter_features_by_year_range(
        features, start_year, end_year
    )

    if not filtered_features:
        print(f"[ERROR] No flood events found in year range {start_year}~{end_year}")
        return

    print(f"[INFO] Filtered {len(filtered_features):,} outlines")
    years_summary = ", ".join(
        f"{year}:{counts[year]:,}" for year in sorted(counts)
    )
    print(f"[SUMMARY] Yearly counts: {years_summary}")

    transformer = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    bounds = _convert_features_to_wgs84(filtered_features, transformer)

    if not bounds:
        print("[ERROR] Cannot calculate transformed coordinate range")
        return

    center_lat = (bounds["min_lat"] + bounds["max_lat"]) / 2
    center_lon = (bounds["min_lon"] + bounds["max_lon"]) / 2
    zoom_start = _estimate_zoom_level(bounds)

    print(f"[MAP] Center: ({center_lat:.4f}, {center_lon:.4f}), Zoom: {zoom_start}")

    colormap = LinearColormap(
        colors=["#1f78b4", "#7fbfff", "#fef65b", "#feb24c", "#bd0026"],
        vmin=start_year,
        vmax=end_year,
        caption="Start Year",
    )

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom_start,
        tiles="CartoDB positron",
    )

    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="Dark Map").add_to(m)

    def style_function(feature):
        year = feature.get("properties", {}).get("start_year")

        color = colormap(year) if isinstance(year, int) else "#8c8c8c"
        return {
            "fillColor": color,
            "color": color,
            "weight": 0.5,
            "fillOpacity": 0.4,
            "opacity": 0.6,
        }

    tooltip = folium.GeoJsonTooltip(
        fields=["name", "start_date", "end_date", "flood_src", "flood_caus", "start_year"],
        aliases=["Name", "Start", "End", "Source", "Cause", "Start Year"],
        localize=True,
        sticky=False,
    )

    folium.GeoJson(
        {
            "type": "FeatureCollection",
            "features": filtered_features,
        },
        name=f"{start_year}-{end_year} Flood Outlines",
        style_function=style_function,
        tooltip=tooltip,
    ).add_to(m)

    colormap.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    plugins.Fullscreen(position="topright").add_to(m)
    plugins.MeasureControl(position="topright").add_to(m)

    print(f"[SAVE] Output file: {output_file}")
    m.save(output_file)
    print("[COMPLETE] Map generated successfully")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Create interactive map of recent flood outlines (2000-2025)"
    )
    parser.add_argument(
        "--flood-file",
        default="Recorded_Flood_Outlines.geojson",
        help="Source GeoJSON file path",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2000,
        help="Start year (default 2000)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2025,
        help="End year (default 2025)",
    )
    parser.add_argument(
        "--output",
        help="Output HTML filename (default flood_map_<start>_<end>.html)",
    )

    args = parser.parse_args()

    if args.start_year > args.end_year:
        parser.error("Start year must be less than or equal to end year")

    create_recent_25_years_map(
        flood_file=args.flood_file,
        start_year=args.start_year,
        end_year=args.end_year,
        output_file=args.output,
    )


if __name__ == "__main__":
    main()

