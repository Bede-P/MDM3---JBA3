import json
import os
from datetime import datetime
from shapely.geometry import box, LineString, Point, Polygon, MultiPolygon
from shapely.ops import unary_union
from pyproj import Transformer
import geopandas as gpd
from pathlib import Path
import requests
import matplotlib.pyplot as plt
import numpy as np


def get_calderdale_boundary():
    """
    Get Calderdale administrative boundary from OpenStreetMap
    
    Returns:
    - GeoDataFrame with Calderdale boundary in EPSG:27700
    """
    print("\n" + "="*60)
    print("FETCHING CALDERDALE ADMINISTRATIVE BOUNDARY")
    print("="*60)
    
    # Try to use OSMnx first (more reliable)
    try:
        import osmnx as ox
        print("[METHOD 1] Using OSMnx to fetch boundary...")
        
        # Get Calderdale boundary from OSM
        calderdale = ox.geocode_to_gdf("Calderdale, England, UK")
        
        # Convert to EPSG:27700
        calderdale_27700 = calderdale.to_crs(epsg=27700)
        
        print(f"[SUCCESS] Boundary fetched via OSMnx")
        print(f"  Geometry type: {calderdale_27700.geometry.iloc[0].geom_type}")
        print(f"  Bounds: {calderdale_27700.total_bounds}")
        
        return calderdale_27700
        
    except ImportError:
        print("[INFO] OSMnx not installed, trying alternative method...")
    except Exception as e:
        print(f"[WARNING] OSMnx method failed: {e}")
    
    # Fallback: Use Overpass API directly
    try:
        print("[METHOD 2] Using Overpass API directly...")
        
        overpass_url = "http://overpass-api.de/api/interpreter"
        
        # Overpass query for Calderdale administrative boundary
        overpass_query = """
        [out:json][timeout:25];
        (
          relation["name"="Calderdale"]["admin_level"="8"]["boundary"="administrative"];
        );
        out geom;
        """
        
        response = requests.post(overpass_url, data={'data': overpass_query}, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('elements'):
                # Convert Overpass response to GeoDataFrame
                element = data['elements'][0]
                
                # Extract coordinates from ways/nodes
                if 'members' in element:
                    coords = []
                    for member in element['members']:
                        if member['type'] == 'way' and 'geometry' in member:
                            way_coords = [(node['lon'], node['lat']) for node in member['geometry']]
                            coords.extend(way_coords)
                    
                    if coords:
                        from shapely.geometry import Polygon
                        boundary_geom = Polygon(coords)
                        
                        # Create GeoDataFrame in WGS84 first
                        gdf = gpd.GeoDataFrame([{'name': 'Calderdale'}], 
                                               geometry=[boundary_geom], 
                                               crs='EPSG:4326')
                        
                        # Convert to EPSG:27700
                        gdf_27700 = gdf.to_crs(epsg=27700)
                        
                        print(f"[SUCCESS] Boundary fetched via Overpass API")
                        print(f"  Geometry type: {gdf_27700.geometry.iloc[0].geom_type}")
                        print(f"  Bounds: {gdf_27700.total_bounds}")
                        
                        return gdf_27700
        
        print(f"[WARNING] Overpass API returned status {response.status_code}")
        
    except Exception as e:
        print(f"[WARNING] Overpass API method failed: {e}")
    
    # Final fallback: Use approximate rectangular boundary
    print("[METHOD 3] Using fallback rectangular boundary...")
    print("[WARNING] Could not fetch true administrative boundary")
    print("          Using rectangular approximation instead")
    
    # Create rectangular boundary (original method)
    min_lon, max_lon = -2.25, -1.75
    min_lat, max_lat = 53.55, 53.85
    
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
    min_x, min_y = transformer.transform(min_lon, min_lat)
    max_x, max_y = transformer.transform(max_lon, max_lat)
    
    bbox_geom = box(min_x, min_y, max_x, max_y)
    gdf = gpd.GeoDataFrame([{'name': 'Calderdale (approx)'}], 
                           geometry=[bbox_geom], 
                           crs='EPSG:27700')
    
    print(f"  Using rectangular bounds: {gdf.total_bounds}")
    
    return gdf


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


def _calculate_flood_duration(start_date_str: str, end_date_str: str):
    """Calculate flood duration in days from start_date to end_date"""
    try:
        if not start_date_str or not end_date_str:
            return None
        
        # Normalize date strings - handle both ISO format and slash format
        start_normalized = start_date_str.replace("T", " ").replace("/", "-").split(".")[0].split("+")[0].split("Z")[0]
        end_normalized = end_date_str.replace("T", " ").replace("/", "-").split(".")[0].split("+")[0].split("Z")[0]
        
        # Parse dates - try ISO format first, then try strptime for other formats
        try:
            start_date = datetime.fromisoformat(start_normalized)
            end_date = datetime.fromisoformat(end_normalized)
        except ValueError:
            # Try parsing with strptime for formats like "2000-06-03 00:00:00"
            try:
                start_date = datetime.strptime(start_normalized, "%Y-%m-%d %H:%M:%S")
                end_date = datetime.strptime(end_normalized, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                # Try just date format
                start_date = datetime.strptime(start_normalized.split()[0], "%Y-%m-%d")
                end_date = datetime.strptime(end_normalized.split()[0], "%Y-%m-%d")
        
        # Calculate duration in days (add 1 to include both start and end days)
        duration = (end_date - start_date).days + 1
        return duration if duration > 0 else 1  # At least 1 day
    except Exception as e:
        return None


def _format_date(date_str: str):
    """Format date string for display"""
    try:
        if not date_str:
            return "Unknown"
        
        # Normalize date string - handle both ISO format and slash format
        normalized = date_str.replace("T", " ").replace("/", "-").split(".")[0].split("+")[0].split("Z")[0]
        
        # Parse date - try ISO format first, then strptime
        try:
            date = datetime.fromisoformat(normalized)
        except ValueError:
            try:
                date = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                date = datetime.strptime(normalized.split()[0], "%Y-%m-%d")
        
        return date.strftime("%Y-%m-%d")
    except Exception:
        return date_str if date_str else "Unknown"

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


def calculate_simple_flood_coverage(
    road_line, 
    all_floods_union,
    start_year=2000,
    end_year=2025
):
    """
    Simplified flood coverage check - only determines if road is affected by floods
    
    Parameters:
    - road_line: Road geometry (LineString)
    - all_floods_union: Union of all flood geometries
    - start_year: Start year (for reference)
    - end_year: End year (for reference)
    
    Returns:
    - is_flooded: Boolean indicating if road intersects with any flood
    - status: "Flooded" or "No Flood"
    - details: Basic statistics
    """
    
    # Check if road intersects with any flood area
    try:
        is_flooded = road_line.intersects(all_floods_union)
        
        if is_flooded:
            # Calculate coverage percentage for information
            intersection = road_line.intersection(all_floods_union)
            intersection_length = intersection.length if intersection else 0
            road_length = road_line.length
            
            if road_length > 0:
                coverage_ratio = intersection_length / road_length
            else:
                coverage_ratio = 0
        
            status = "Flooded"
            details = {
                'is_flooded': True,
                'coverage_ratio': round(coverage_ratio * 100, 2)
            }
        else:
            status = "No Flood"
            details = {
                'is_flooded': False,
                'coverage_ratio': 0
            }
    except Exception as e:
        # If any error, assume no flood
        is_flooded = False
        status = "No Flood"
        details = {
            'is_flooded': False,
            'coverage_ratio': 0,
            'error': str(e)
        }
    
    return is_flooded, status, details


def load_roads_with_simple_flood_check(
    road_geojson_dir: str,
    calderdale_gdf: gpd.GeoDataFrame,
    calderdale_bbox,
    calderdale_boundary,
    start_year: int,
    end_year: int
):
    """
    Load roads in Calderdale area and check simple flood coverage (flooded vs not flooded)
    
    Parameters:
    - road_geojson_dir: Directory containing road GeoJSON files
    - calderdale_gdf: GeoDataFrame with flood data for Calderdale (in EPSG:27700)
    - calderdale_bbox: Bounding box for initial filtering (performance)
    - calderdale_boundary: True administrative boundary geometry for precise filtering
    - start_year: Start year of analysis
    - end_year: End year of analysis
    
    Returns:
    - List of road features with flood status in WGS84 coordinates
    """
    road_dir = Path(road_geojson_dir) / 'RoadLink'
    
    if not road_dir.exists():
        print(f"[WARNING] Road network directory does not exist: {road_dir}")
        return []
    
    print(f"\n{'='*60}")
    print("SIMPLE ROAD FLOOD COVERAGE CHECK")
    print(f"{'='*60}")
    print(f"Analysis period: {start_year}-{end_year} ({end_year-start_year+1} years)")
    
    # === PRE-COMPUTE COMBINED FLOOD UNION ===
    print("\n[OPTIMIZATION] Pre-computing combined flood union...")
    all_flood_polygons = []
    
    for idx, row in calderdale_gdf.iterrows():
                geom = row.geometry
                if geom and geom.is_valid:
                    if geom.geom_type == 'Polygon':
                        all_flood_polygons.append(geom)
                    elif geom.geom_type == 'MultiPolygon':
                        geoms_list = list(geom.geoms)
                        all_flood_polygons.extend(geoms_list)
            
    if not all_flood_polygons:
        print("[WARNING] No flood data found")
        return []
    
    # Pre-compute total flood union (for quick intersection check)
    all_floods_union = unary_union(all_flood_polygons)
    print(f"  Combined {len(all_flood_polygons):,} flood polygons into single union")
    print(f"  Total flood outlines: {len(calderdale_gdf):,}")
    
    # Load and filter roads
    print(f"\nLoading roads from: {road_dir}")
    road_files = sorted(list(road_dir.glob('*.geojson')))
    
    if not road_files:
        print("[WARNING] No road GeoJSON files found")
        return []
    
    print(f"Found {len(road_files)} road files")
    
    transformer_to_wgs84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    
    all_road_features = []
    total_roads_processed = 0
    roads_flooded = 0
    
    # Get bounding box bounds for filtering
    bbox_bounds = calderdale_bbox.bounds  # (minx, miny, maxx, maxy)
    
    print(f"\n[PROCESSING] Checking roads in {len(road_files)} files...")
    for file_idx, road_file in enumerate(road_files, 1):
        try:
            # Load road GeoJSON
            road_gdf = gpd.read_file(road_file)
            
            # Set CRS to EPSG:27700 if not set
            if road_gdf.crs is None:
                road_gdf.set_crs(epsg=27700, inplace=True)
            elif road_gdf.crs.to_string() != "EPSG:27700":
                road_gdf = road_gdf.to_crs(epsg=27700)
            
            # Step 1: Quick filter using bounding box (performance optimization)
            roads_in_bbox = road_gdf[road_gdf.geometry.intersects(calderdale_bbox)]
            
            if len(roads_in_bbox) == 0:
                continue
            
            # Step 2: Precise filter using true administrative boundary
            roads_in_boundary = roads_in_bbox[roads_in_bbox.geometry.intersects(calderdale_boundary)]
            
            if len(roads_in_boundary) == 0:
                continue
            
            file_roads_flooded = 0
            file_roads_checked = 0
            
            for idx, row in roads_in_boundary.iterrows():
                total_roads_processed += 1
                file_roads_checked += 1
                
                geom = row.geometry
                if geom is None or not geom.is_valid:
                    continue
                
                # Convert to LineString if needed
                if geom.geom_type == 'LineString':
                    road_line = geom
                elif geom.geom_type == 'MultiLineString':
                    # Use the longest segment
                    road_line = max(geom.geoms, key=lambda x: x.length)
                else:
                    continue
                
                # Simple flood coverage check
                is_flooded, flood_status, flood_details = calculate_simple_flood_coverage(
                        road_line=road_line,
                        all_floods_union=all_floods_union,
                        start_year=start_year,
                        end_year=end_year
                    )
                
                # Track flooded roads
                if is_flooded:
                    roads_flooded += 1
                    file_roads_flooded += 1
                
                # Transform coordinates to WGS84 for ALL roads (continuous network)
                if geom.geom_type == 'LineString':
                    transformed_coords = []
                    for coord in geom.coords:
                        x, y = coord[0], coord[1]  # Handle both 2D and 3D coords
                        lon, lat = transformer_to_wgs84.transform(x, y)
                        transformed_coords.append([lon, lat])
                    transformed_geom = {
                        'type': 'LineString',
                        'coordinates': transformed_coords
                    }
                else:  # MultiLineString
                    transformed_lines = []
                    for line in geom.geoms:
                        line_coords = []
                        for coord in line.coords:
                            x, y = coord[0], coord[1]  # Handle both 2D and 3D coords
                            lon, lat = transformer_to_wgs84.transform(x, y)
                            line_coords.append([lon, lat])
                        transformed_lines.append(line_coords)
                    transformed_geom = {
                        'type': 'MultiLineString',
                        'coordinates': transformed_lines
                    }
                
                # Create feature for ALL roads (with and without flooding)
                properties = row.to_dict()
                # Remove geometry from properties if present
                properties.pop('geometry', None)
                
                # Add flood status information
                properties.update({
                    'is_flooded': is_flooded,
                    'flood_status': flood_status,
                    'flood_details': flood_details
                })
                
                feature = {
                    'type': 'Feature',
                    'geometry': transformed_geom,
                    'properties': properties
                }
                
                # Add all roads to display continuous network
                all_road_features.append(feature)
            
            # Progress update
            print(f"  [{file_idx}/{len(road_files)}] {road_file.stem}: "
                  f"{file_roads_checked} checked, {file_roads_flooded} flooded")
            
            # Limit to avoid excessive file size
            if len(all_road_features) >= 50000:
                print(f"\n[INFO] Reached limit of 50,000 roads, stopping load")
                break
                
        except Exception as e:
            import traceback
            print(f"  [{file_idx}/{len(road_files)}] {road_file.stem}: Error - {e}")
            if file_idx <= 30:  # Show detailed error for first few files
                traceback.print_exc()
    
    print(f"\n{'='*60}")
    print(f"[COMPLETE] Road Flood Coverage Check")
    print(f"{'='*60}")
    print(f"Total roads processed: {total_roads_processed:,}")
    print(f"Roads flooded: {roads_flooded:,}")
    print(f"Roads not flooded: {total_roads_processed - roads_flooded:,}")
    print(f"Roads included in map: {len(all_road_features):,}")
    
    return all_road_features


def create_calderdale_flood_map(
    flood_file: str = "Recorded_Flood_Outlines.geojson",
    start_year: int = 2000,
    end_year: int = 2025,
    output_file: str = None,
    road_geojson_dir: str = None,
    include_roads: bool = False,
    specific_year: int = None,
):
    """
    Generate flood outline map for Calderdale area in given year range
    
    Parameters:
    - flood_file: Path to flood GeoJSON file
    - start_year: Start year of analysis period
    - end_year: End year of analysis period
    - output_file: Output HTML filename
    - road_geojson_dir: Directory containing road GeoJSON files
    - include_roads: Whether to include road risk assessment
    - specific_year: If set, only show floods for this specific year
    """
    try:
        import folium
        from folium import plugins
        from branca.colormap import LinearColormap
    except ImportError:
        print("[ERROR] Need to install folium and branca")
        print("Please run: pip install folium branca")
        return

    if output_file is None:
        if specific_year:
            output_file = f"Calderdale_{specific_year}.html"
        else:
            output_file = f"calderdale_flood_map_{start_year}_{end_year}.html"

    if not os.path.exists(flood_file):
        print(f"[ERROR] Cannot find file: {flood_file}")
        return

    print("=" * 60)
    print("Calderdale Flood Map (2000-2025)")
    print("=" * 60)

    # ----- 1. Get Calderdale TRUE administrative boundary -----
    calderdale_boundary_gdf = get_calderdale_boundary()
    
    if calderdale_boundary_gdf is None or len(calderdale_boundary_gdf) == 0:
        print("[ERROR] Could not obtain Calderdale boundary")
        return
    
    # Get the boundary geometry
    calderdale_boundary = calderdale_boundary_gdf.geometry.iloc[0]
    
    # Get bounding box for initial filtering (more efficient)
    bounds_27700 = calderdale_boundary_gdf.total_bounds  # (minx, miny, maxx, maxy)
    min_x, min_y, max_x, max_y = bounds_27700
    
    print(f"\nCalderdale boundary info (EPSG:27700):")
    print(f"  Geometry type: {calderdale_boundary.geom_type}")
    print(f"  Bounds: X[{min_x:.1f}, {max_x:.1f}], Y[{min_y:.1f}, {max_y:.1f}]")
    
    # Create bbox for quick filtering
    calderdale_bbox = box(min_x, min_y, max_x, max_y)

    # ----- 3. Load flood data as GeoDataFrame -----
    print("Loading flood data...")
    flood_gdf = gpd.read_file(flood_file)
    # Set CRS to EPSG:27700 (British National Grid) if not already set
    if flood_gdf.crs is None:
        flood_gdf.set_crs(epsg=27700, inplace=True)
    elif flood_gdf.crs.to_string() != "EPSG:27700":
        flood_gdf = flood_gdf.to_crs(epsg=27700)
    
    print(f"[INFO] Loaded {len(flood_gdf):,} total flood outlines")

    # ----- 4. Filter by year range -----
    flood_gdf["start_year"] = flood_gdf["start_date"].apply(_parse_start_year)
    
    if specific_year:
        print(f"Filtering for specific year: {specific_year}")
        filtered_gdf = flood_gdf[flood_gdf["start_year"] == specific_year]
        if len(filtered_gdf) == 0:
            print(f"[ERROR] No flood events found in year {specific_year}")
            return
        print(f"[INFO] Found {len(filtered_gdf):,} outlines for year {specific_year}")
    else:
        print(f"Filtering by year range ({start_year}-{end_year})...")
    filtered_gdf = flood_gdf[
        (flood_gdf["start_year"] >= start_year) & 
        (flood_gdf["start_year"] <= end_year) &
        (flood_gdf["start_year"].notna())
    ]

    if len(filtered_gdf) == 0:
        print(f"[ERROR] No flood events found in year range {start_year}~{end_year}")
        return

    # Count by year
    counts = filtered_gdf["start_year"].value_counts().to_dict()
    print(f"[INFO] Filtered {len(filtered_gdf):,} outlines by year")
    years_summary = ", ".join(
        f"{year}:{counts[year]:,}" for year in sorted(counts)
    )
    print(f"[SUMMARY] Yearly counts: {years_summary}")

    # ----- 5. Clip to Calderdale TRUE administrative boundary -----
    print("Clipping to Calderdale administrative boundary...")
    
    # Use the actual boundary geometry for clipping (not just bbox)
    # This ensures only data within the true administrative boundary is included
    calderdale_gdf = gpd.clip(filtered_gdf, calderdale_boundary_gdf)

    if len(calderdale_gdf) == 0:
        print("[ERROR] No flood events found in Calderdale area")
        return

    print(f"[INFO] Clipped to {len(calderdale_gdf):,} outlines in Calderdale area")
    print(f"[INFO] Geometries clipped to TRUE administrative boundary (precise coverage)")

    # ----- 6. Transform coordinates to WGS84 -----
    print("Transforming coordinates to WGS84...")
    calderdale_wgs84 = calderdale_gdf.to_crs(epsg=4326)
    calderdale_boundary_wgs84 = calderdale_boundary_gdf.to_crs(epsg=4326)
    
    # Calculate map center from actual boundary centroid
    boundary_wgs84_geom = calderdale_boundary_wgs84.geometry.iloc[0]
    centroid = boundary_wgs84_geom.centroid
    center_lon, center_lat = centroid.x, centroid.y
    
    # Get bounds for zoom calculation
    bounds_wgs84 = calderdale_boundary_wgs84.total_bounds  # (minx, miny, maxx, maxy)
    min_lon, min_lat, max_lon, max_lat = bounds_wgs84
    
    # Calculate appropriate zoom level based on boundary extent
    lon_span = max_lon - min_lon
    lat_span = max_lat - min_lat
    span = max(lon_span, lat_span)
    
    if span <= 0.3:
        zoom_start = 11
    elif span <= 0.5:
        zoom_start = 10
    else:
        zoom_start = 9

    print(f"[MAP] Center: ({center_lat:.4f}, {center_lon:.4f}), Zoom: {zoom_start}")
    print(f"[MAP] Bounds: Lon[{min_lon:.4f}, {max_lon:.4f}], Lat[{min_lat:.4f}, {max_lat:.4f}]")
    
    # Define Calderdale bounds in WGS84 for map limits (from actual boundary)
    calderdale_bounds_wgs84 = [
        [min_lat, min_lon],  # Southwest corner
        [max_lat, max_lon],  # Northeast corner
    ]
    
    # Convert GeoDataFrame back to GeoJSON format for Folium
    calderdale_features = json.loads(calderdale_wgs84.to_json())
    calderdale_features = calderdale_features.get("features", [])
    
    # ----- 6.5. Load and check road flood coverage (if requested) -----
    road_features = []
    if include_roads and road_geojson_dir:
        road_features = load_roads_with_simple_flood_check(
            road_geojson_dir=road_geojson_dir,
            calderdale_gdf=calderdale_gdf,
            calderdale_bbox=calderdale_bbox,
            calderdale_boundary=calderdale_boundary,
            start_year=start_year,
            end_year=end_year
        )
    elif include_roads and not road_geojson_dir:
        print("\n[WARNING] Road flood check requested but no road directory provided")
    else:
        print("\n[INFO] Skipping road flood check")

    # ----- 7. Create color map for years -----
    colormap = LinearColormap(
        colors=["#1f78b4", "#7fbfff", "#fef65b", "#feb24c", "#bd0026"],
        vmin=start_year,
        vmax=end_year,
        caption="Start Year",
    )

    # ----- 8. Create Folium map with bounds restriction -----
    print("Creating Folium map...")
    # Set maximum bounds to Calderdale area (prevents panning outside region)
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom_start,
        tiles="CartoDB positron",
        max_bounds=calderdale_bounds_wgs84,  # Restrict map panning to Calderdale area
    )

    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="Dark Map").add_to(m)
    
    # ----- 8.5. Add Calderdale administrative boundary outline -----
    print("Adding Calderdale administrative boundary to map...")
    boundary_geojson = json.loads(calderdale_boundary_wgs84.to_json())
    
    # Create boundary style - prominent outline
    def boundary_style(feature):
        return {
            'fillColor': 'none',
            'color': '#FF1493',  # Deep pink color (like Google Maps)
            'weight': 3,
            'opacity': 0.9,
            'fillOpacity': 0,
            'dashArray': '10, 5'  # Dashed line
        }
    
    boundary_layer = folium.FeatureGroup(name='Calderdale Boundary', show=True)
    folium.GeoJson(
        boundary_geojson,
        style_function=boundary_style,
        tooltip=folium.Tooltip('Calderdale Administrative Boundary')
    ).add_to(boundary_layer)
    boundary_layer.add_to(m)

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
            "features": calderdale_features,
        },
        name=f"Calderdale Flood Outlines ({start_year}-{end_year})",
        style_function=style_function,
        tooltip=tooltip,
    ).add_to(m)

    # ----- 9. Add road flood coverage layer (if available) -----
    if road_features:
        print(f"\nAdding road flood coverage layer to map...")
        print(f"  Total roads loaded: {len(road_features):,}")
        
        # Count roads by flood status
        flood_stats = {}
        roads_flooded_count = 0
        for feature in road_features:
            flood_status = feature.get('properties', {}).get('flood_status', 'Unknown')
            flood_stats[flood_status] = flood_stats.get(flood_status, 0) + 1
            if flood_status == 'Flooded':
                roads_flooded_count += 1
        
        print(f"  Roads flooded: {roads_flooded_count:,}")
        print(f"  Roads not flooded: {len(road_features) - roads_flooded_count:,}")
        print(f"  Flood status distribution:")
        for status in ['Flooded', 'No Flood']:
            count = flood_stats.get(status, 0)
            if count > 0:
                pct = count / len(road_features) * 100
                print(f"    {status}: {count:,} roads ({pct:.1f}%)")
        
        # Define simple flood status colors and styles
        def get_flood_color(flood_status):
            color_map = {
                'Flooded': '#FF0000',      # Red for flooded roads
                'No Flood': '#00FF00'      # Green for non-flooded roads
            }
            return color_map.get(flood_status, '#808080')
        
        def get_flood_weight(flood_status):
            weight_map = {
                'Flooded': 3,      # Thicker line for flooded roads
                'No Flood': 2      # Normal line for non-flooded roads
            }
            return weight_map.get(flood_status, 2)
        
        def road_style(feature):
            props = feature.get('properties', {})
            flood_status = props.get('flood_status', 'Unknown')
            
            return {
                'color': get_flood_color(flood_status),
                'weight': get_flood_weight(flood_status),
                'opacity': 0.8
            }
        
        # Create road GeoJSON
        road_geojson = {
            'type': 'FeatureCollection',
            'features': road_features
        }
        
        # Create road layer with simple tooltip
        road_layer = folium.FeatureGroup(name='Road Flood Coverage', show=True)
        
        # Flatten flood_details for tooltip display
        for feature in road_features:
            props = feature.get('properties', {})
            details = props.get('flood_details', {})
            props['coverage_pct'] = details.get('coverage_ratio', 0)
        
        folium.GeoJson(
            road_geojson,
            style_function=road_style,
            tooltip=folium.GeoJsonTooltip(
                fields=[
                    'flood_status', 
                    'coverage_pct'
                ],
                aliases=[
                    'Flood Status:',
                    'Coverage (%):'
                ],
                localize=True
            )
        ).add_to(road_layer)
        road_layer.add_to(m)

    colormap.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    plugins.Fullscreen(position="topright").add_to(m)
    plugins.MeasureControl(position="topright").add_to(m)
    
    # ----- 10. Add title and legend -----
    if road_features:
        # Calculate unique years with floods for display
        years_with_floods = len(calderdale_gdf['start_year'].unique())
        
        # Create simple title with flood status statistics
        flood_counts = {}
        for feature in road_features:
            flood_status = feature.get('properties', {}).get('flood_status', 'Unknown')
            flood_counts[flood_status] = flood_counts.get(flood_status, 0) + 1
        
        legend_items = []
        legend_colors = {
            'Flooded': '#FF0000',
            'No Flood': '#00FF00'
        }
        
        for status in ['Flooded', 'No Flood']:
            count = flood_counts.get(status, 0)
            if count > 0:
                color = legend_colors.get(status, '#808080')
                legend_items.append(f'''
                    <div style="margin: 3px 0;">
                        <span style="display: inline-block; width: 30px; height: 3px; 
                                     background-color: {color}; vertical-align: middle;"></span>
                        <span style="margin-left: 5px; font-size: 11px;">{status} ({count:,})</span>
                    </div>
                ''')
        
        legend_html = ''.join(legend_items)
        
        title_html = f'''
        <div style="position: fixed; 
                    top: 10px; 
                    left: 50px; 
                    width: auto;
                    max-width: 400px;
                    background-color: white;
                    border: 2px solid grey;
                    z-index: 9999;
                    font-size: 14px;
                    padding: 10px;
                    border-radius: 5px;
                    box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
            <div style="font-weight: bold; font-size: 16px; margin-bottom: 8px;">
                Calderdale Flood & Road Coverage ({specific_year if specific_year else f"{start_year}-{end_year}"})
            </div>
            <div style="font-size: 11px; color: #555; margin-bottom: 8px;">
                Flood Outlines: {len(calderdale_features):,} | {'Year: ' + str(specific_year) if specific_year else f'Analysis Period: {end_year-start_year+1} years'}
            </div>
            <div style="font-size: 11px; color: #555; margin-bottom: 8px;">
                Total Roads: {len(road_features):,} | {('Year with Floods: ' + str(specific_year)) if specific_year else f'Years with Floods: {years_with_floods}'}
            </div>
            <div style="border-top: 1px solid #ddd; padding-top: 8px;">
                <div style="font-weight: bold; font-size: 12px; margin-bottom: 5px;">
                    Road Flood Coverage:
                </div>
                {legend_html}
            </div>
            <div style="margin-top: 8px; font-size: 10px; color: #888; border-top: 1px solid #eee; padding-top: 5px;">
                * Red: Roads covered by historical flood areas (2000-2025)<br/>
                * Green: Roads not affected by floods
            </div>
        </div>
        '''
    else:
        title_html = f'''
        <div style="position: fixed; 
                    top: 10px; 
                    left: 50px; 
                    width: auto;
                    background-color: white;
                    border: 2px solid grey;
                    z-index: 9999;
                    font-size: 14px;
                    padding: 10px;
                    border-radius: 5px;
                    box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
            <div style="font-weight: bold; font-size: 16px; margin-bottom: 8px;">
                Calderdale Flood Outlines ({specific_year if specific_year else f"{start_year}-{end_year}"})
            </div>
            <div style="font-size: 11px; color: #555;">
                Flood Outlines: {len(calderdale_features):,} | {'Year: ' + str(specific_year) if specific_year else f'Analysis Period: {end_year-start_year+1} years'}
            </div>
        </div>
        '''
    
    m.get_root().html.add_child(folium.Element(title_html))

    print(f"\n[SAVE] Output file: {output_file}")
    m.save(output_file)
    
    file_size = os.path.getsize(output_file) / (1024 * 1024)
    
    print("\n" + "=" * 60)
    print("[COMPLETE] Map Generated Successfully!")
    print("=" * 60)
    print(f"  Output file: {output_file}")
    print(f"  File size: {file_size:.2f} MB")
    print(f"  Flood outlines: {len(calderdale_features):,}")
    if road_features:
        print(f"  Total roads: {len(road_features):,}")
        
        # Count flooded vs non-flooded
        flooded_count = sum(1 for f in road_features if f.get('properties', {}).get('is_flooded', False))
        print(f"  Roads flooded: {flooded_count:,}")
        print(f"  Roads not flooded: {len(road_features) - flooded_count:,}")
        print(f"\n  Simple Flood Coverage Check:")
        print(f"    - Red: Roads intersecting with historical flood areas")
        print(f"    - Green: Roads not affected by floods")
    print("=" * 60)


def create_interactive_yearly_map(
    flood_file: str,
    start_year: int,
    end_year: int,
    road_geojson_dir: str = None,
    include_roads: bool = False,
    output_file: str = "Calderdale_Interactive.html"
):
    """Create a single interactive HTML map with year selector"""
    
    try:
        import folium
        from folium import plugins
    except ImportError:
        print("[ERROR] Need to install folium")
        return
    
    print("="*60)
    print("CREATING INTERACTIVE YEARLY MAP")
    print("="*60)
    
    # Get Calderdale boundary
    calderdale_boundary_gdf = get_calderdale_boundary()
    if calderdale_boundary_gdf is None:
        print("[ERROR] Could not fetch Calderdale boundary")
        return
    
    calderdale_boundary = calderdale_boundary_gdf.geometry.iloc[0]
    bounds_27700 = calderdale_boundary_gdf.total_bounds
    min_x, min_y, max_x, max_y = bounds_27700
    calderdale_bbox = box(min_x, min_y, max_x, max_y)
    
    # Load flood data
    print("\nLoading flood data...")
    flood_gdf = gpd.read_file(flood_file)
    if flood_gdf.crs is None:
        flood_gdf.set_crs(epsg=27700, inplace=True)
    elif flood_gdf.crs.to_string() != "EPSG:27700":
        flood_gdf = flood_gdf.to_crs(epsg=27700)
    
    flood_gdf["start_year"] = flood_gdf["start_date"].apply(_parse_start_year)
    
    # Filter and clip
    filtered_gdf = flood_gdf[
        (flood_gdf["start_year"] >= start_year) & 
        (flood_gdf["start_year"] <= end_year) &
        (flood_gdf["start_year"].notna())
    ]
    calderdale_gdf = gpd.clip(filtered_gdf, calderdale_boundary_gdf)
    
    years_with_floods = sorted([int(y) for y in calderdale_gdf["start_year"].unique()])
    
    print(f"\nFound {len(years_with_floods)} years with floods:")
    for year in years_with_floods:
        count = len(calderdale_gdf[calderdale_gdf["start_year"] == year])
        print(f"  {year}: {count} flood outlines")
    
    # Transform to WGS84
    calderdale_wgs84 = calderdale_gdf.to_crs(epsg=4326)
    calderdale_boundary_wgs84 = calderdale_boundary_gdf.to_crs(epsg=4326)
    
    boundary_wgs84_geom = calderdale_boundary_wgs84.geometry.iloc[0]
    centroid = boundary_wgs84_geom.centroid
    center_lon, center_lat = centroid.x, centroid.y
    
    # Create map
    print("\nCreating map...")
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="CartoDB positron")
    
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="Dark Map").add_to(m)
    
    # Add boundary
    boundary_geojson = json.loads(calderdale_boundary_wgs84.to_json())
    folium.GeoJson(
        boundary_geojson,
        style_function=lambda x: {
            'fillColor': 'none', 'color': '#FF1493', 'weight': 3,
            'opacity': 0.9, 'fillOpacity': 0, 'dashArray': '10, 5'
        },
        name='Calderdale Boundary'
    ).add_to(m)
    
    # Load and add Voronoi cells
    voronoi_file = "voronoi_cells.geojson"
    voronoi_loaded = False
    voronoi_clipped = None
    if os.path.exists(voronoi_file):
        print("\nLoading Voronoi cells...")
        try:
            voronoi_gdf = gpd.read_file(voronoi_file)
            # Voronoi cells are already in WGS84 (CRS84), so we can use them directly
            if voronoi_gdf.crs is None:
                voronoi_gdf.set_crs(epsg=4326, inplace=True)
            
            # Clip Voronoi cells to Calderdale boundary
            voronoi_clipped = gpd.clip(voronoi_gdf, calderdale_boundary_wgs84)
            
            # Add cell IDs if they don't exist
            if 'cell_id' not in voronoi_clipped.columns:
                voronoi_clipped['cell_id'] = range(1, len(voronoi_clipped) + 1)
            
            voronoi_loaded = True
            print(f"  Found {len(voronoi_clipped)} Voronoi cells")
        except Exception as e:
            print(f"  [WARNING] Could not load Voronoi cells: {e}")
    else:
        print(f"\n[INFO] Voronoi cells file not found: {voronoi_file}")
    
    # Store flood layers to add after Voronoi cells (so they appear on top)
    flood_layers_data = []
    flood_stats = {}
    for year in years_with_floods:
        year_floods = calderdale_wgs84[calderdale_wgs84["start_year"] == year]
        year_features = json.loads(year_floods.to_json())
        
        flood_layers_data.append({
            'year': year,
            'features': year_features,
            'count': len(year_floods)
        })
        flood_stats[year] = len(year_floods)
    
    # Load roads if requested
    road_stats = {}
    if include_roads and road_geojson_dir:
        print("\nLoading roads...")
        
        # Pre-compute flood unions
        flood_unions = {}
        for year in years_with_floods:
            year_floods = calderdale_gdf[calderdale_gdf["start_year"] == year]
            geoms = []
            for idx, row in year_floods.iterrows():
                if row.geometry and row.geometry.is_valid:
                    if row.geometry.geom_type == 'Polygon':
                        geoms.append(row.geometry)
                    elif row.geometry.geom_type == 'MultiPolygon':
                        geoms.extend(list(row.geometry.geoms))
            if geoms:
                flood_unions[year] = unary_union(geoms)
        
        road_dir = Path(road_geojson_dir) / 'RoadLink'
        road_files = sorted(list(road_dir.glob('*.geojson')))
        
        transformer = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
        
        roads_data = []
        total = 0
        
        print(f"  Processing {len(road_files)} road files...")
        for file_idx, road_file in enumerate(road_files, 1):
            file_roads_count = 0
            try:
                road_gdf = gpd.read_file(road_file)
                if road_gdf.crs is None:
                    road_gdf.set_crs(epsg=27700, inplace=True)
                elif road_gdf.crs.to_string() != "EPSG:27700":
                    road_gdf = road_gdf.to_crs(epsg=27700)
                
                roads_in_boundary = road_gdf[road_gdf.geometry.intersects(calderdale_boundary)]
                
                for idx, row in roads_in_boundary.iterrows():
                    if row.geometry is None or not row.geometry.is_valid:
                        continue
                    
                    if row.geometry.geom_type == 'LineString':
                        road_line = row.geometry
                    elif row.geometry.geom_type == 'MultiLineString':
                        road_line = max(row.geometry.geoms, key=lambda x: x.length)
                    else:
                        continue
                    
                    coords = []
                    for coord in road_line.coords:
                        lon, lat = transformer.transform(coord[0], coord[1])
                        coords.append([lat, lon])
                    
                    flood_years = []
                    for year in years_with_floods:
                        if year in flood_unions and road_line.intersects(flood_unions[year]):
                            flood_years.append(year)
                    
                    # Get road class
                    road_class = row.get('class', 'Unknown') if 'class' in row else 'Unknown'
                    
                    roads_data.append({
                        'coords': coords, 
                        'flood_years': flood_years,
                        'road_class': road_class,
                        'geometry_27700': road_line  # Keep geometry in EPSG:27700 for length calculation
                    })
                    total += 1
                    file_roads_count += 1
                    
                    if total >= 30000:
                        break
                
                if total >= 30000:
                    print(f"  Reached limit of 30,000 roads")
                    break
                
                # Print progress for files that loaded roads
                if file_roads_count > 0:
                    print(f"  [{file_idx}/{len(road_files)}] {road_file.stem}: {file_roads_count} roads (total: {total})")
                    
            except Exception as e:
                print(f"  [WARNING] Error loading {road_file.stem}: {e}")
                continue
        
        print(f"  Loaded {total} roads")
        
        # Calculate road network length in each Voronoi cell (by road class)
        if voronoi_loaded and voronoi_clipped is not None:
            print("\nCalculating road network length by class in each Voronoi cell...")
            
            # Convert Voronoi cells to EPSG:27700 for accurate length calculation
            voronoi_27700 = voronoi_clipped.to_crs(epsg=27700)
            
            # Define road classes to track (with merged Minor Roads category)
            road_classes = ['Motorway', 'A Road', 'B Road', 'Minor Roads', 'Unknown']
            minor_roads_classes = ['Classified Unnumbered', 'Unclassified', 'Not Classified']
            
            # Initialize columns for each road class and total
            voronoi_27700['road_length_km'] = 0.0
            for road_class in road_classes:
                voronoi_27700[f'{road_class}_km'] = 0.0
                voronoi_27700[f'{road_class}_pct'] = 0.0
            
            for cell_idx, cell_row in voronoi_27700.iterrows():
                cell_geom = cell_row.geometry
                total_length_m = 0.0
                class_lengths = {rc: 0.0 for rc in road_classes}
                
                # Check each road
                for road in roads_data:
                    road_geom = road['geometry_27700']
                    road_class_original = road.get('road_class', 'Unknown')
                    
                    # Map to merged categories
                    if road_class_original in minor_roads_classes:
                        road_class = 'Minor Roads'
                    else:
                        road_class = road_class_original
                    
                    # Check if road intersects with this cell
                    if road_geom.intersects(cell_geom):
                        # Calculate the length of road within this cell
                        try:
                            intersection = road_geom.intersection(cell_geom)
                            length_m = 0.0
                            if intersection.geom_type == 'LineString':
                                length_m = intersection.length
                            elif intersection.geom_type == 'MultiLineString':
                                length_m = sum(line.length for line in intersection.geoms)
                            
                            total_length_m += length_m
                            if road_class in class_lengths:
                                class_lengths[road_class] += length_m
                            else:
                                class_lengths['Unknown'] += length_m
                        except Exception:
                            # If intersection fails, use full road length as approximation
                            length_m = road_geom.length
                            total_length_m += length_m
                            if road_class in class_lengths:
                                class_lengths[road_class] += length_m
                            else:
                                class_lengths['Unknown'] += length_m
                
                # Convert to kilometers and calculate percentages
                total_length_km = total_length_m / 1000.0
                voronoi_27700.at[cell_idx, 'road_length_km'] = round(total_length_km, 2)
                
                for road_class in road_classes:
                    length_km = class_lengths[road_class] / 1000.0
                    voronoi_27700.at[cell_idx, f'{road_class}_km'] = round(length_km, 2)
                    
                    # Calculate percentage
                    if total_length_km > 0:
                        pct = (length_km / total_length_km) * 100.0
                        voronoi_27700.at[cell_idx, f'{road_class}_pct'] = round(pct, 1)
                    else:
                        voronoi_27700.at[cell_idx, f'{road_class}_pct'] = 0.0
            
            # Copy the calculated values back to WGS84 version
            for col in voronoi_27700.columns:
                if col != 'geometry':
                    voronoi_clipped[col] = voronoi_27700[col].values
            
            print(f"  Calculated road lengths for {len(voronoi_clipped)} cells")
            print(f"  Total road network: {voronoi_clipped['road_length_km'].sum():.2f} km")
        
        # Define road class colors (for non-flooded roads)
        road_class_colors = {
            'Motorway': '#0000FF',           # Blue
            'A Road': '#00A000',             # Dark Green
            'B Road': '#FFA500',             # Orange
            'Minor Roads': '#808080',        # Gray (merged class)
            'Classified Unnumbered': '#808080',  # Merged into Minor Roads
            'Unclassified': '#808080',       # Merged into Minor Roads
            'Not Classified': '#808080',     # Merged into Minor Roads
            'Unknown': '#C0C0C0'             # Silver
        }
        
        # Add road layers
        for year in years_with_floods:
            flooded_count = 0
            not_flooded_count = 0
            
            # Flooded roads (always red, regardless of class)
            flooded_layer = folium.FeatureGroup(name=f'roads_flooded_{year}', show=(year == years_with_floods[0]))
            for road in roads_data:
                if year in road['flood_years']:
                    folium.PolyLine(road['coords'], color='#FF0000', weight=3, opacity=0.8).add_to(flooded_layer)
                    flooded_count += 1
            flooded_layer.add_to(m)
            
            # Non-flooded roads (colored by road class)
            not_flooded_layer = folium.FeatureGroup(name=f'roads_not_flooded_{year}', show=(year == years_with_floods[0]))
            for road in roads_data:
                if year not in road['flood_years']:
                    road_class = road.get('road_class', 'Unknown')
                    color = road_class_colors.get(road_class, '#C0C0C0')
                    weight = 3 if road_class in ['Motorway', 'A Road'] else 2
                    folium.PolyLine(road['coords'], color=color, weight=weight, opacity=0.7).add_to(not_flooded_layer)
                    not_flooded_count += 1
            not_flooded_layer.add_to(m)
            
            road_stats[year] = {'flooded': flooded_count, 'not_flooded': not_flooded_count}
    
    # Add Voronoi cells layer with road length information
    if voronoi_loaded and voronoi_clipped is not None:
        print("\nAdding Voronoi cells to map...")
        voronoi_geojson = json.loads(voronoi_clipped.to_json())
        
        # Build tooltip fields and aliases
        tooltip_fields = ['cell_id', 'road_length_km']
        tooltip_aliases = ['Cell ID:', 'Total Road (km):']
        
        # Add fields for each road class (only show if percentage > 0)
        road_classes = ['Motorway', 'A Road', 'B Road', 'Classified Unnumbered', 'Unclassified', 'Not Classified']
        for road_class in road_classes:
            pct_field = f'{road_class}_pct'
            km_field = f'{road_class}_km'
            if pct_field in voronoi_clipped.columns:
                tooltip_fields.append(pct_field)
                tooltip_aliases.append(f'{road_class} (%):')
        
        voronoi_layer = folium.FeatureGroup(name='Voronoi Cells', show=True)
        
        # Create custom popup HTML for each Voronoi cell
        for idx, row in voronoi_clipped.iterrows():
            cell_id = row['cell_id']
            total_km = row['road_length_km']
            
            # Build popup HTML with road classification details
            popup_html = f'''
            <div style="font-family: Arial; font-size: 12px; width: 280px; max-height: 400px; overflow-y: auto;">
                <h4 style="margin: 0 0 8px 0; color: #333; border-bottom: 2px solid #FF8C00;">
                    Voronoi Cell {cell_id}
                </h4>
                <div style="margin-bottom: 8px;">
                    <b style="color: #555;">Total Road Network:</b> 
                    <span style="color: #000; font-size: 13px; font-weight: bold;">{total_km} km</span>
                </div>
                <div style="border-top: 1px solid #ddd; padding-top: 8px;">
                    <b style="color: #555;">Road Classification:</b>
                    <table style="width: 100%; margin-top: 5px; font-size: 11px;">
            '''
            
            # Add each road class if it exists and has non-zero percentage
            road_classes_display = [
                ('Motorway', '#0000FF'),
                ('A Road', '#00A000'),
                ('B Road', '#FFA500'),
                ('Minor Roads', '#808080')
            ]
            
            for road_class, color in road_classes_display:
                pct_field = f'{road_class}_pct'
                km_field = f'{road_class}_km'
                if pct_field in row and row[pct_field] > 0:
                    pct = row[pct_field]
                    km = row[km_field]
                    popup_html += f'''
                        <tr>
                            <td style="padding: 2px 0;">
                                <span style="display: inline-block; width: 12px; height: 3px; 
                                             background-color: {color}; margin-right: 5px;"></span>
                                {road_class}
                            </td>
                            <td style="text-align: right; padding: 2px 0;">
                                {km:.2f} km
                            </td>
                            <td style="text-align: right; padding: 2px 0; font-weight: bold;">
                                {pct:.1f}%
                            </td>
                        </tr>
                    '''
            
            popup_html += '''
                    </table>
                </div>
            </div>
            '''
            
            # Add individual polygon with popup
            # Use fillOpacity 0 so clicks pass through to flood layers below
            # Border will still be visible but won't intercept clicks
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x: {
                    'fillColor': '#FFD700',
                    'color': '#FF8C00',
                    'weight': 1.5,
                    'opacity': 0.6,
                    'fillOpacity': 0.0  # Completely transparent - clicks pass through
                },
                popup=folium.Popup(popup_html, max_width=300)
            ).add_to(voronoi_layer)
        voronoi_layer.add_to(m)
        print(f"  Added {len(voronoi_clipped)} Voronoi cells with road classification data")
    
    # Add flood layers AFTER Voronoi cells so they appear on top and can be clicked
    print("\nAdding flood layers (on top of Voronoi cells)...")
    for flood_data in flood_layers_data:
        year = flood_data['year']
        year_features = flood_data['features']
        
        layer = folium.FeatureGroup(name=f'floods_{year}', show=(year == years_with_floods[0]))
        
        # Add each flood feature individually with its own popup
        for feature in year_features.get('features', []):
            props = feature.get('properties', {})
            name = props.get('name', 'Unknown Flood')
            start_date = props.get('start_date', '')
            end_date = props.get('end_date', '')
            
            # Format dates
            start_formatted = _format_date(start_date)
            end_formatted = _format_date(end_date)
            
            # Calculate duration (end_date - start_date in days)
            duration = _calculate_flood_duration(start_date, end_date)
            if duration is not None:
                duration_text = f"{duration} day{'s' if duration != 1 else ''}"
            else:
                duration_text = "Unknown"
            
            # Create HTML popup content
            popup_html = f"""
            <div style="font-family: Arial, sans-serif; min-width: 200px;">
                <h4 style="margin: 0 0 10px 0; color: #4169E1; border-bottom: 2px solid #4169E1; padding-bottom: 5px;">
                    {name}
                </h4>
                <div style="line-height: 1.6;">
                    <strong>Start Date:</strong> {start_formatted}<br/>
                    <strong>End Date:</strong> {end_formatted}<br/>
                    <strong>Duration:</strong> {duration_text}
                </div>
            </div>
            """
            
            # Add individual flood polygon with popup
            folium.GeoJson(
                feature,
                style_function=lambda x: {
                    "fillColor": "#4169E1", "color": "#4169E1",
                    "weight": 1, "fillOpacity": 0.5, "opacity": 0.8
                },
                popup=folium.Popup(popup_html, max_width=300)
            ).add_to(layer)
        
        layer.add_to(m)
    
    # Add schools layer
    schools_file = "schools-list-calderdale.csv"
    if os.path.exists(schools_file):
        print("\nAdding schools to map...")
        try:
            import pandas as pd
            schools_df = pd.read_csv(schools_file)
            
            # Define school colors by phase
            phase_colors = {
                'Primary': '#4169E1',           # Royal Blue
                'Secondary': '#DC143C',         # Crimson Red
                'All-through': '#9370DB',       # Medium Purple
                'Special primary': '#20B2AA',   # Light Sea Green
                'Special secondary': '#FF6347', # Tomato
                'Alternative provision': '#FFA500',  # Orange
                '16 plus': '#FFD700'            # Gold
            }
            
            # Filter to only Primary schools
            primary_schools = schools_df[schools_df['Phase'] == 'Primary'].copy()
            
            # Create school marker layer
            schools_layer = folium.FeatureGroup(name='Schools', show=True)
            
            school_count = 0
            for idx, row in primary_schools.iterrows():
                lat = row['Latitude']
                lon = row['Longitude']
                
                # Skip if coordinates are missing
                if pd.isna(lat) or pd.isna(lon):
                    continue
                
                school_name = row['Establishment']
                phase = row['Phase']
                status = row['Status']
                pupils = row['Number of pupils on roll']
                postcode = row['Postcode']
                website = row['Website'] if pd.notna(row['Website']) else 'N/A'
                
                # Get color by phase (should always be Primary = blue)
                color = phase_colors.get(phase, '#4169E1')  # Default to blue for Primary
                
                # Create popup HTML
                popup_html = f"""
                <div style="font-family: Arial; font-size: 12px; width: 220px;">
                    <h4 style="margin: 0 0 8px 0; color: #333;">{school_name}</h4>
                    <table style="width: 100%; font-size: 11px;">
                        <tr><td><b>Phase:</b></td><td>{phase}</td></tr>
                        <tr><td><b>Status:</b></td><td>{status}</td></tr>
                        <tr><td><b>Students:</b></td><td>{pupils}</td></tr>
                    </table>
                </div>
                """
                
                # Add marker (no tooltip, only popup on click)
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=6,
                    popup=folium.Popup(popup_html, max_width=300),
                    color=color,
                    fill=True,
                    fillColor=color,
                    fillOpacity=0.8,
                    weight=2
                ).add_to(schools_layer)
                
                school_count += 1
            
            schools_layer.add_to(m)
            print(f"  Added {school_count} schools to map")
            
        except Exception as e:
            print(f"  [WARNING] Could not load schools: {e}")
    else:
        print(f"\n[INFO] Schools file not found: {schools_file}")
    
    plugins.Fullscreen(position="topright").add_to(m)
    
    # Add simple year selector and map type selector
    year_selector = f'''
    <script>
    var roadStats = {json.dumps(road_stats)};
    
    function switchYear() {{
        var year = parseInt(document.getElementById('yearSelector').value);
        var overlays = document.querySelectorAll('.leaflet-control-layers-overlays input[type="checkbox"]');
        
        overlays.forEach(function(checkbox) {{
            var label = checkbox.parentElement.textContent.trim();
            var shouldShow = label.includes('_' + year);
            
            if (shouldShow && !checkbox.checked) {{
                checkbox.click();
            }} else if (!shouldShow && checkbox.checked && label.match(/_\\d{{4}}/)) {{
                checkbox.click();
            }}
        }});
        
        // Update flood impact ratio
        if (roadStats[year]) {{
            var flooded = roadStats[year].flooded;
            var notFlooded = roadStats[year].not_flooded;
            var total = flooded + notFlooded;
            var percentage = total > 0 ? ((flooded / total) * 100).toFixed(2) : 0;
            document.getElementById('floodImpact').textContent = percentage + '%';
        }}
    }}
    
    function switchMapType() {{
        var mapType = document.getElementById('mapTypeSelector').value;
        var baseLayers = document.querySelectorAll('.leaflet-control-layers-base input[type="radio"]');
        
        baseLayers.forEach(function(radio) {{
            var label = radio.parentElement.textContent.trim().toLowerCase();
            if ((mapType === 'cartodbpositron' && label.includes('positron')) ||
                (mapType === 'openstreetmap' && label.includes('openstreet')) ||
                (mapType === 'dark' && label.includes('dark'))) {{
                radio.click();
            }}
        }});
    }}
    
    window.addEventListener('load', function() {{
        setTimeout(function() {{
            var layers = document.querySelector('.leaflet-control-layers');
            if (layers) layers.style.display = 'none';
            
            // Initialize flood impact ratio
            if (roadStats[{years_with_floods[0]}]) {{
                var flooded = roadStats[{years_with_floods[0]}].flooded;
                var notFlooded = roadStats[{years_with_floods[0]}].not_flooded;
                var total = flooded + notFlooded;
                var percentage = total > 0 ? ((flooded / total) * 100).toFixed(2) : 0;
                document.getElementById('floodImpact').textContent = percentage + '%';
            }}
        }}, 100);
    }});
    </script>
    
    <div style="position: fixed; top: 10px; right: 10px; z-index: 9999; background-color: white; 
                padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                font-size: 12px;">
        <div style="margin-bottom: 8px;">
            <label style="display: block; margin-bottom: 4px; color: #333;">Year:</label>
            <select id="yearSelector" onchange="switchYear()" 
                    style="width: 120px; padding: 4px; font-size: 12px; border: 1px solid #ccc; border-radius: 3px;">
                {chr(10).join([f'<option value="{year}">{year}</option>' for year in years_with_floods])}
            </select>
        </div>
        <div style="margin-bottom: 8px;">
            <label style="display: block; margin-bottom: 4px; color: #333;">Map Type:</label>
            <select id="mapTypeSelector" onchange="switchMapType()" 
                    style="width: 120px; padding: 4px; font-size: 12px; border: 1px solid #ccc; border-radius: 3px;">
                <option value="cartodbpositron">CartoDB Positron</option>
                <option value="openstreetmap">OpenStreetMap</option>
                <option value="dark">Dark Map</option>
            </select>
        </div>
        {('<div style="padding: 8px; background-color: #f5f5f5; border-radius: 3px; border: 1px solid #ddd;"><div style="font-size: 11px; color: #666; margin-bottom: 3px;">Flooded Roads Ratio:</div><div style="font-size: 14px; font-weight: bold; color: #FF0000;" id="floodImpact">-</div></div>' if road_stats else '')}
    </div>
    '''
    
    m.get_root().html.add_child(folium.Element(year_selector))
    
    # Add road classification legend (if roads are loaded)
    if road_stats:
        road_legend = '''
        <div style="position: fixed; top: 10px; left: 10px; z-index: 9999; background-color: white; 
                    padding: 12px; border: 1px solid #ccc; border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                    font-size: 12px; max-width: 200px;">
            <div style="font-weight: bold; font-size: 13px; margin-bottom: 8px; color: #333; border-bottom: 1px solid #ddd; padding-bottom: 4px;">
                Road Classification
            </div>
            <div style="margin-bottom: 4px; display: flex; align-items: center;">
                <div style="width: 30px; height: 3px; background-color: #FF0000; margin-right: 8px;"></div>
                <span style="color: #333;">Flooded (All Classes)</span>
            </div>
            <div style="margin-bottom: 4px; display: flex; align-items: center;">
                <div style="width: 30px; height: 3px; background-color: #0000FF; margin-right: 8px;"></div>
                <span style="color: #333;">Motorway</span>
            </div>
            <div style="margin-bottom: 4px; display: flex; align-items: center;">
                <div style="width: 30px; height: 3px; background-color: #00A000; margin-right: 8px;"></div>
                <span style="color: #333;">A Road</span>
            </div>
            <div style="margin-bottom: 4px; display: flex; align-items: center;">
                <div style="width: 30px; height: 3px; background-color: #FFA500; margin-right: 8px;"></div>
                <span style="color: #333;">B Road</span>
            </div>
            <div style="display: flex; align-items: center;">
                <div style="width: 30px; height: 2px; background-color: #808080; margin-right: 8px;"></div>
                <span style="color: #333;">Minor Roads</span>
            </div>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(road_legend))
    
    # Schools legend removed - no longer displaying school label
    
    folium.LayerControl(collapsed=False).add_to(m)
    
    print(f"\n[SAVE] {output_file}")
    m.save(output_file)
    
    file_size = os.path.getsize(output_file) / (1024 * 1024)
    print(f"\n{'='*60}")
    print(f"[COMPLETE] Interactive map created!")
    print(f"{'='*60}")
    print(f"  File: {output_file}")
    print(f"  Size: {file_size:.2f} MB")
    print(f"  Years: {', '.join(map(str, years_with_floods))}")
    print(f"{'='*60}")


def create_flood_coverage_vs_road_impact_chart(
    flood_file: str,
    start_year: int,
    end_year: int,
    road_geojson_dir: str,
    output_file: str = "flood_coverage_vs_road_impact.png"
):
    """
    Create a static chart showing the relationship between flood coverage area percentage
    and affected road network percentage for each year.
    
    Parameters:
    - flood_file: Path to flood GeoJSON file
    - start_year: Start year of analysis
    - end_year: End year of analysis
    - road_geojson_dir: Directory containing road GeoJSON files
    - output_file: Output PNG filename
    """
    print("="*60)
    print("FLOOD COVERAGE VS ROAD IMPACT ANALYSIS")
    print("="*60)
    
    # Get Calderdale boundary
    calderdale_boundary_gdf = get_calderdale_boundary()
    if calderdale_boundary_gdf is None:
        print("[ERROR] Could not fetch Calderdale boundary")
        return
    
    calderdale_boundary = calderdale_boundary_gdf.geometry.iloc[0]
    bounds_27700 = calderdale_boundary_gdf.total_bounds
    min_x, min_y, max_x, max_y = bounds_27700
    calderdale_bbox = box(min_x, min_y, max_x, max_y)
    
    # Calculate Calderdale total area (in square kilometers)
    calderdale_area_sqm = calderdale_boundary.area
    calderdale_area_sqkm = calderdale_area_sqm / 1_000_000
    print(f"\nCalderdale area: {calderdale_area_sqkm:.2f} sq km")
    
    # Load flood data
    print("\nLoading flood data...")
    flood_gdf = gpd.read_file(flood_file)
    if flood_gdf.crs is None:
        flood_gdf.set_crs(epsg=27700, inplace=True)
    elif flood_gdf.crs.to_string() != "EPSG:27700":
        flood_gdf = flood_gdf.to_crs(epsg=27700)
    
    flood_gdf["start_year"] = flood_gdf["start_date"].apply(_parse_start_year)
    
    # Filter and clip
    filtered_gdf = flood_gdf[
        (flood_gdf["start_year"] >= start_year) & 
        (flood_gdf["start_year"] <= end_year) &
        (flood_gdf["start_year"].notna())
    ]
    calderdale_gdf = gpd.clip(filtered_gdf, calderdale_boundary_gdf)
    
    years_with_floods = sorted([int(y) for y in calderdale_gdf["start_year"].unique()])
    
    print(f"\nFound {len(years_with_floods)} years with floods: {years_with_floods}")
    
    # Calculate flood coverage percentage for each year
    flood_coverage_data = {}
    
    for year in years_with_floods:
        year_floods = calderdale_gdf[calderdale_gdf["start_year"] == year]
        
        # Combine all flood polygons for this year
        flood_geoms = []
        for idx, row in year_floods.iterrows():
            if row.geometry and row.geometry.is_valid:
                if row.geometry.geom_type == 'Polygon':
                    flood_geoms.append(row.geometry)
                elif row.geometry.geom_type == 'MultiPolygon':
                    flood_geoms.extend(list(row.geometry.geoms))
        
        if flood_geoms:
            flood_union = unary_union(flood_geoms)
            flood_area_sqm = flood_union.area
            flood_area_sqkm = flood_area_sqm / 1_000_000
            flood_coverage_pct = (flood_area_sqkm / calderdale_area_sqkm) * 100
            
            flood_coverage_data[year] = {
                'area_sqkm': flood_area_sqkm,
                'coverage_pct': flood_coverage_pct,
                'num_outlines': len(year_floods)
            }
            
            print(f"  {year}: {flood_area_sqkm:.3f} sq km ({flood_coverage_pct:.2f}%)")
    
    # Calculate road impact percentage for each year
    print("\nCalculating road impact...")
    
    # Pre-compute flood unions for each year
    flood_unions = {}
    for year in years_with_floods:
        year_floods = calderdale_gdf[calderdale_gdf["start_year"] == year]
        geoms = []
        for idx, row in year_floods.iterrows():
            if row.geometry and row.geometry.is_valid:
                if row.geometry.geom_type == 'Polygon':
                    geoms.append(row.geometry)
                elif row.geometry.geom_type == 'MultiPolygon':
                    geoms.extend(list(row.geometry.geoms))
        if geoms:
            flood_unions[year] = unary_union(geoms)
    
    # Load roads
    road_dir = Path(road_geojson_dir) / 'RoadLink'
    road_files = sorted(list(road_dir.glob('*.geojson')))
    
    all_roads = []
    total_roads = 0
    
    for file_idx, road_file in enumerate(road_files, 1):
        try:
            road_gdf = gpd.read_file(road_file)
            if road_gdf.crs is None:
                road_gdf.set_crs(epsg=27700, inplace=True)
            elif road_gdf.crs.to_string() != "EPSG:27700":
                road_gdf = road_gdf.to_crs(epsg=27700)
            
            roads_in_boundary = road_gdf[road_gdf.geometry.intersects(calderdale_boundary)]
            
            for idx, row in roads_in_boundary.iterrows():
                if row.geometry is None or not row.geometry.is_valid:
                    continue
                
                if row.geometry.geom_type == 'LineString':
                    road_line = row.geometry
                elif row.geometry.geom_type == 'MultiLineString':
                    road_line = max(row.geometry.geoms, key=lambda x: x.length)
                else:
                    continue
                
                all_roads.append(road_line)
                total_roads += 1
                
                if total_roads >= 15000:
                    break
            
            if total_roads >= 15000:
                print(f"  Loaded {total_roads} roads (limit reached)")
                break
                
        except Exception as e:
            continue
    
    print(f"  Total roads loaded: {total_roads}")
    
    # Calculate road impact for each year
    road_impact_data = {}
    
    for year in years_with_floods:
        if year not in flood_unions:
            continue
        
        flooded_count = 0
        for road in all_roads:
            if road.intersects(flood_unions[year]):
                flooded_count += 1
        
        road_impact_pct = (flooded_count / total_roads) * 100 if total_roads > 0 else 0
        
        road_impact_data[year] = {
            'flooded': flooded_count,
            'total': total_roads,
            'impact_pct': road_impact_pct
        }
        
        print(f"  {year}: {flooded_count}/{total_roads} roads ({road_impact_pct:.2f}%)")
    
    # Create visualization
    print("\nCreating visualization...")
    
    # Prepare data for plotting
    years = []
    flood_coverage_pcts = []
    road_impact_pcts = []
    
    for year in sorted(years_with_floods):
        if year in flood_coverage_data and year in road_impact_data:
            years.append(year)
            flood_coverage_pcts.append(flood_coverage_data[year]['coverage_pct'])
            road_impact_pcts.append(road_impact_data[year]['impact_pct'])
    
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # Subplot 1: Scatter plot
    colors = plt.cm.viridis(np.linspace(0, 1, len(years)))
    
    ax1.scatter(flood_coverage_pcts, road_impact_pcts, s=200, c=colors, alpha=0.7, edgecolors='black', linewidth=1.5)
    
    # Add year labels to each point
    for i, year in enumerate(years):
        ax1.annotate(str(year), 
                    (flood_coverage_pcts[i], road_impact_pcts[i]),
                    fontsize=9,
                    fontweight='bold',
                    ha='center',
                    va='center')
    
    ax1.set_xlabel('Flood Coverage Area (%)', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Affected Road Network (%)', fontsize=12, fontweight='bold')
    ax1.set_title('Flood Coverage vs Road Network Impact\n(2000-2025)', fontsize=14, fontweight='bold', pad=15)
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.set_axisbelow(True)
    
    # Add trend line
    if len(years) > 1:
        z = np.polyfit(flood_coverage_pcts, road_impact_pcts, 1)
        p = np.poly1d(z)
        x_trend = np.linspace(min(flood_coverage_pcts), max(flood_coverage_pcts), 100)
        ax1.plot(x_trend, p(x_trend), "r--", alpha=0.5, linewidth=2, label=f'Trend: y={z[0]:.2f}x+{z[1]:.2f}')
        ax1.legend(fontsize=10)
    
    # Subplot 2: Dual axis line chart
    ax2_right = ax2.twinx()
    
    line1 = ax2.plot(years, flood_coverage_pcts, 'o-', color='#4169E1', linewidth=2.5, markersize=8, label='Flood Coverage Area (%)')
    line2 = ax2_right.plot(years, road_impact_pcts, 's-', color='#FF4500', linewidth=2.5, markersize=8, label='Affected Road Network (%)')
    
    ax2.set_xlabel('Year', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Flood Coverage Area (%)', fontsize=12, fontweight='bold', color='#4169E1')
    ax2_right.set_ylabel('Affected Road Network (%)', fontsize=12, fontweight='bold', color='#FF4500')
    ax2.set_title('Flood Coverage and Road Impact Over Time\n(2000-2025)', fontsize=14, fontweight='bold', pad=15)
    
    ax2.tick_params(axis='y', labelcolor='#4169E1')
    ax2_right.tick_params(axis='y', labelcolor='#FF4500')
    
    ax2.grid(True, alpha=0.3, linestyle='--', axis='both')
    ax2.set_axisbelow(True)
    
    # Add legend
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax2.legend(lines, labels, loc='upper left', fontsize=10)
    
    # Set x-axis to show all years
    ax2.set_xticks(years)
    ax2.set_xticklabels(years, rotation=45)
    
    plt.tight_layout()
    
    # Save figure
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"\n[SAVE] Chart saved to: {output_file}")
    
    file_size = os.path.getsize(output_file) / 1024
    print(f"\n{'='*60}")
    print(f"[COMPLETE] Analysis finished!")
    print(f"{'='*60}")
    print(f"  Output file: {output_file}")
    print(f"  File size: {file_size:.2f} KB")
    print(f"  Years analyzed: {len(years)}")
    print(f"  Calderdale area: {calderdale_area_sqkm:.2f} sq km")
    print(f"  Total roads analyzed: {total_roads}")
    print(f"{'='*60}")
    
    # Print summary table
    print("\nSummary Data:")
    print(f"{'Year':<6} {'Flood Area (sq km)':<18} {'Coverage %':<12} {'Flooded Roads':<15} {'Impact %':<10}")
    print("-" * 80)
    for year in years:
        flood_area = flood_coverage_data[year]['area_sqkm']
        flood_pct = flood_coverage_data[year]['coverage_pct']
        flooded_roads = road_impact_data[year]['flooded']
        impact_pct = road_impact_data[year]['impact_pct']
        print(f"{year:<6} {flood_area:<18.3f} {flood_pct:<12.2f} {flooded_roads:<15} {impact_pct:<10.2f}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Create interactive map of flood outlines for Calderdale area (2000-2025) with optional road risk assessment"
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
        help="Output HTML filename (default calderdale_flood_map_<start>_<end>.html)",
    )
    parser.add_argument(
        "--road-dir",
        help="Directory containing road GeoJSON files (enables road flood coverage check)",
    )
    parser.add_argument(
        "--include-roads",
        action="store_true",
        help="Include road flood coverage check (requires --road-dir)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Create interactive map with year selector",
    )
    parser.add_argument(
        "--generate-chart",
        action="store_true",
        help="Generate flood coverage vs road impact chart",
    )

    args = parser.parse_args()

    if args.start_year > args.end_year:
        parser.error("Start year must be less than or equal to end year")
    
    if args.include_roads and not args.road_dir:
        print("[WARNING] --include-roads specified but --road-dir not provided")
        print("           Road flood coverage check will be skipped")

    if args.generate_chart:
        create_flood_coverage_vs_road_impact_chart(
            flood_file=args.flood_file,
            start_year=args.start_year,
            end_year=args.end_year,
            road_geojson_dir=args.road_dir,
            output_file=args.output if args.output else "flood_coverage_vs_road_impact.png"
        )
    elif args.interactive:
        create_interactive_yearly_map(
            flood_file=args.flood_file,
            start_year=args.start_year,
            end_year=args.end_year,
            road_geojson_dir=args.road_dir,
            include_roads=args.include_roads,
            output_file=args.output if args.output else "Calderdale_Interactive.html"
        )
    else:
        create_calderdale_flood_map(
            flood_file=args.flood_file,
            start_year=args.start_year,
            end_year=args.end_year,
            output_file=args.output,
            road_geojson_dir=args.road_dir,
            include_roads=args.include_roads,
            specific_year=None
        )


if __name__ == "__main__":
    main()

