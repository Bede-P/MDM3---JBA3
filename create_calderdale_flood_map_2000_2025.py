import json
import os
from datetime import datetime
from shapely.geometry import box, LineString, Point, Polygon, MultiPolygon
from shapely.ops import unary_union
from pyproj import Transformer
import geopandas as gpd
from pathlib import Path


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


def calculate_multi_year_road_flood_risk_optimized(
    road_line, 
    flood_unions_by_year,
    all_floods_union,
    flood_gdf_by_year=None,  # Added: original flood GeoDataFrames for duration analysis
    road_properties=None,
    start_year=2000,
    end_year=2025
):
    
    
    total_years = end_year - start_year + 1
    
    if not flood_unions_by_year:
        return 0, "No Historical Risk", {
            'risk_score': 0,
            'flood_frequency': 0,
            'years_affected': 0
        }
    
    # === 1. HISTORICAL FLOOD FREQUENCY (25%) ===
    # How many times has this road been affected over 25 years
    # More frequent = higher disruption to school routes
    years_affected = len(flood_unions_by_year)
    frequency_ratio = years_affected / total_years
    
    # Non-linear scaling: roads flooded >5 times are high risk
    if years_affected >= 10:
        frequency_score = 100
    elif years_affected >= 5:
        frequency_score = 70 + (years_affected - 5) * 6
    elif years_affected >= 2:
        frequency_score = 40 + (years_affected - 2) * 10
    else:
        frequency_score = years_affected * 20
    
    # === 2. SPATIAL COVERAGE INTENSITY (35%) ===
    # What percentage of the road has been historically flooded?
    # Critical for school routes: even partial flooding can block access
    try:
        intersection = road_line.intersection(all_floods_union)
        intersection_length = intersection.length if intersection else 0
        road_length = road_line.length
        
        if road_length > 0:
            coverage_ratio = intersection_length / road_length
        else:
            coverage_ratio = 0
        
        # Progressive scoring: >50% coverage is very high risk
        if coverage_ratio >= 0.75:
            coverage_score = 100
        elif coverage_ratio >= 0.50:
            coverage_score = 80 + (coverage_ratio - 0.50) * 80
        elif coverage_ratio >= 0.25:
            coverage_score = 50 + (coverage_ratio - 0.25) * 120
        else:
            coverage_score = coverage_ratio * 200
        
        coverage_score = min(coverage_score, 100)
    except Exception:
        coverage_score = 0
        coverage_ratio = 0
    
    # === 3. ROUTE BLOCKAGE SEVERITY (25%) ===
    # Are endpoints flooded? Critical for school access!
    # If both endpoints flooded → road is completely isolated
    try:
        start_point = Point(road_line.coords[0])
        end_point = Point(road_line.coords[-1])
        
        # Count how many times each endpoint was flooded
        start_flood_count = sum(1 for year_union in flood_unions_by_year.values() 
                                if year_union.contains(start_point))
        end_flood_count = sum(1 for year_union in flood_unions_by_year.values() 
                              if year_union.contains(end_point))
        
        # Calculate blockage severity
        total_endpoint_floods = start_flood_count + end_flood_count
        
        if start_flood_count > 0 and end_flood_count > 0:
            # Both endpoints affected → complete isolation
            blockage_score = 100
        elif total_endpoint_floods >= 5:
            # One endpoint frequently flooded → high risk
            blockage_score = 70 + min(total_endpoint_floods - 5, 6) * 5
        elif total_endpoint_floods > 0:
            # Some endpoint flooding
            blockage_score = 30 + total_endpoint_floods * 8
        else:
            blockage_score = 10
        
        blockage_score = min(blockage_score, 100)
    except Exception:
        blockage_score = 10
        start_flood_count = 0
        end_flood_count = 0
    
    # === 4. FLOOD DURATION IMPACT (10%) ===
    # Inspired by Pregnolato et al. (2017): longer floods = greater disruption
    # Calculate weighted impact based on flood duration
    duration_score = 0
    total_duration_days = 0
    long_duration_floods = 0
    
    if flood_gdf_by_year:
        try:
            from datetime import datetime
            
            midpoint = road_line.interpolate(0.5, normalized=True)
            weighted_duration = 0
            
            for year, year_union in flood_unions_by_year.items():
                if year_union.contains(midpoint):
                    # Check if road was affected by floods this year
                    year_floods = flood_gdf_by_year.get(year)
                    if year_floods is not None and len(year_floods) > 0:
                        # Calculate total duration for floods affecting this road
                        for idx, row in year_floods.iterrows():
                            flood_geom = row.geometry
                            if flood_geom and flood_geom.is_valid:
                                # Check if this flood intersects with road
                                if road_line.intersects(flood_geom):
                                    start_date = row.get('start_date', '')
                                    end_date = row.get('end_date', '')
                                    
                                    if start_date and end_date:
                                        try:
                                            start = datetime.fromisoformat(start_date.replace('T', ' ').split('.')[0])
                                            end = datetime.fromisoformat(end_date.replace('T', ' ').split('.')[0])
                                            duration_days = (end - start).days + 1  # +1 to include both days
                                            
                                            if duration_days > 0:
                                                total_duration_days += duration_days
                                                
                                                # Weight by duration: longer floods have more impact
                                                # >7 days = severe, >3 days = significant, >1 day = moderate
                                                if duration_days >= 7:
                                                    weighted_duration += duration_days * 2.0  # Double weight
                                                    long_duration_floods += 1
                                                elif duration_days >= 3:
                                                    weighted_duration += duration_days * 1.5
                                                else:
                                                    weighted_duration += duration_days * 1.0
                                        except:
                                            pass
            
            # Normalize duration score
            # Assume average flood duration is 2 days, max observed ~30 days
            if weighted_duration > 0:
                # Scale: 0-50 days weighted = 0-100 score
                duration_score = min(weighted_duration / 50 * 100, 100)
            else:
                duration_score = 0
                
        except Exception as e:
            duration_score = 0
    else:
        # Fallback: use persistence as proxy
        try:
            midpoint = road_line.interpolate(0.5, normalized=True)
            years_midpoint_flooded = sum(1 for year_union in flood_unions_by_year.values() 
                                         if year_union.contains(midpoint))
            persistence_ratio = years_midpoint_flooded / total_years
            duration_score = min(persistence_ratio * 100, 100)  # Proxy score
        except:
            duration_score = 0
    
    # === 5. FLOOD PERSISTENCE (5%) ===
    # How consistently is the road center affected?
    # Persistent flooding indicates systematic drainage issues
    try:
        midpoint = road_line.interpolate(0.5, normalized=True)
        
        years_midpoint_flooded = sum(1 for year_union in flood_unions_by_year.values() 
                                     if year_union.contains(midpoint))
        
        persistence_ratio = years_midpoint_flooded / total_years
        persistence_score = min(persistence_ratio * 150, 100)
    except Exception:
        persistence_score = 20
        years_midpoint_flooded = 0
    
    # === 5. INFRASTRUCTURE VULNERABILITY (10%) ===
    # School routes often use minor roads and local streets
    road_type_multiplier = 1.0
    road_type_name = "Unknown"
    infrastructure_importance = "Unknown"
    
    if road_properties:
        road_class = str(road_properties.get('class', '')).lower()
        road_function = str(road_properties.get('roadFunction', '')).lower()
        
        if 'motorway' in road_class or 'motorway' in road_function:
            road_type_multiplier = 0.6  # Motorway - rarely school routes
            road_type_name = "Motorway"
            infrastructure_importance = "Low"
        elif 'a road' in road_class or 'primary' in road_function:
            road_type_multiplier = 0.8  # A Road - better maintained
            road_type_name = "A Road"
            infrastructure_importance = "Medium"
        elif 'b road' in road_class or 'secondary' in road_function:
            road_type_multiplier = 1.0  # B Road - typical school route
            road_type_name = "B Road"
            infrastructure_importance = "High"
        elif 'minor' in road_class or 'local' in road_function:
            road_type_multiplier = 1.3  # Minor road - common for schools
            road_type_name = "Minor Road"
            infrastructure_importance = "Very High"
        else:
            road_type_multiplier = 1.4  # Local street - pedestrian routes
            road_type_name = "Local Street"
            infrastructure_importance = "Critical"
    
    infrastructure_score = 50 * road_type_multiplier
    
    # === CALCULATE COMPREHENSIVE RISK SCORE ===
    # Optimized for school route analysis (inspired by Pregnolato et al. 2017)
    risk_score = (
        frequency_score * 0.20 +       # Historical flood frequency (reduced from 25%)
        coverage_score * 0.30 +         # Spatial coverage (reduced from 35%)
        blockage_score * 0.25 +         # Route blockage severity
        duration_score * 0.10 +         # Flood duration impact (NEW - inspired by paper)
        persistence_score * 0.05 +      # Flood persistence
        infrastructure_score * 0.10    # Infrastructure vulnerability
    )
    
    # Ensure score is within 0-100 range
    risk_score = max(0, min(100, risk_score))
    
    # Determine risk level
    if risk_score >= 85:
        risk_level = "Extreme Risk"
    elif risk_score >= 70:
        risk_level = "Critical Risk"
    elif risk_score >= 55:
        risk_level = "High Risk"
    elif risk_score >= 40:
        risk_level = "Moderate Risk"
    elif risk_score >= 25:
        risk_level = "Low Risk"
    else:
        risk_level = "Minimal Risk"
    
    # Detailed information
    details = {
        'risk_score': round(risk_score, 2),
        'risk_level': risk_level,
        'flood_frequency': years_affected,
        'frequency_ratio': round(frequency_ratio * 100, 2),
        'frequency_score': round(frequency_score, 2),
        'coverage_ratio': round(coverage_ratio * 100, 2),
        'coverage_score': round(coverage_score, 2),
        'blockage_score': round(blockage_score, 2),
        'start_flood_count': start_flood_count,
        'end_flood_count': end_flood_count,
        'duration_score': round(duration_score, 2),
        'total_duration_days': total_duration_days,
        'long_duration_floods': long_duration_floods,
        'persistence_score': round(persistence_score, 2),
        'years_midpoint_flooded': years_midpoint_flooded,
        'road_type': road_type_name,
        'infrastructure_importance': infrastructure_importance,
        'infrastructure_score': round(infrastructure_score, 2)
    }
    
    return risk_score, risk_level, details


def load_roads_with_multi_year_flood_risk(
    road_geojson_dir: str,
    calderdale_gdf: gpd.GeoDataFrame,
    calderdale_bbox,
    start_year: int,
    end_year: int
):
    """
    Load roads in Calderdale area and calculate multi-year flood risk
    
    Parameters:
    - road_geojson_dir: Directory containing road GeoJSON files
    - calderdale_gdf: GeoDataFrame with flood data for Calderdale (in EPSG:27700)
    - calderdale_bbox: Bounding box for Calderdale area
    - start_year: Start year of analysis
    - end_year: End year of analysis
    
    Returns:
    - List of road features with risk scores in WGS84 coordinates
    """
    road_dir = Path(road_geojson_dir) / 'RoadLink'
    
    if not road_dir.exists():
        print(f"[WARNING] Road network directory does not exist: {road_dir}")
        return []
    
    print(f"\n{'='*60}")
    print("MULTI-YEAR ROAD FLOOD RISK ASSESSMENT")
    print(f"{'='*60}")
    print(f"Analysis period: {start_year}-{end_year} ({end_year-start_year+1} years)")
    
    # === PRE-COMPUTE FLOOD UNIONS (MAJOR OPTIMIZATION) ===
    print("\n[OPTIMIZATION] Pre-computing flood unions by year...")
    flood_unions_by_year = {}
    flood_gdf_by_year = {}  # Store original GeoDataFrames for duration analysis
    all_flood_polygons = []
    
    for year in range(start_year, end_year + 1):
        year_floods = calderdale_gdf[calderdale_gdf['start_year'] == year]
        if len(year_floods) > 0:
            # Store original GeoDataFrame for duration analysis
            flood_gdf_by_year[year] = year_floods
            
            # Extract and merge geometries for this year
            year_geoms = []
            for idx, row in year_floods.iterrows():
                geom = row.geometry
                if geom and geom.is_valid:
                    if geom.geom_type == 'Polygon':
                        year_geoms.append(geom)
                        all_flood_polygons.append(geom)
                    elif geom.geom_type == 'MultiPolygon':
                        geoms_list = list(geom.geoms)
                        year_geoms.extend(geoms_list)
                        all_flood_polygons.extend(geoms_list)
            
            if year_geoms:
                # Pre-compute union for this year
                year_union = unary_union(year_geoms)
                flood_unions_by_year[year] = year_union
                print(f"  Year {year}: {len(year_floods):,} outlines → merged")
    
    if not flood_unions_by_year:
        print("[WARNING] No flood data found")
        return []
    
    # Pre-compute total flood union (for quick intersection check)
    print(f"\n[OPTIMIZATION] Pre-computing combined flood union...")
    all_floods_union = unary_union(all_flood_polygons)
    print(f"  Combined {len(all_flood_polygons):,} polygons from {len(flood_unions_by_year)} years")
    
    print(f"\nTotal years with flood data: {len(flood_unions_by_year)}")
    
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
    roads_with_risk = 0
    
    # Get bounding box bounds for filtering
    bbox_bounds = calderdale_bbox.bounds  # (minx, miny, maxx, maxy)
    
    print(f"\n[PROCESSING] Analyzing roads in {len(road_files)} files...")
    for file_idx, road_file in enumerate(road_files, 1):
        try:
            # Load road GeoJSON
            road_gdf = gpd.read_file(road_file)
            
            # Set CRS to EPSG:27700 if not set
            if road_gdf.crs is None:
                road_gdf.set_crs(epsg=27700, inplace=True)
            elif road_gdf.crs.to_string() != "EPSG:27700":
                road_gdf = road_gdf.to_crs(epsg=27700)
            
            # Filter roads that intersect with Calderdale bounding box
            roads_in_bbox = road_gdf[road_gdf.geometry.intersects(calderdale_bbox)]
            
            if len(roads_in_bbox) == 0:
                continue
            
            file_roads_with_risk = 0
            file_roads_checked = 0
            
            for idx, row in roads_in_bbox.iterrows():
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
                
                # Calculate multi-year flood risk using OPTIMIZED function
                # For roads without flood intersection, set default risk values
                if not road_line.intersects(all_floods_union):
                    # No flood intersection - set as "No Flood Risk"
                    risk_score = 0
                    risk_level = "No Flood Risk"
                    risk_details = {
                        'risk_score': 0,
                        'flood_frequency': 0,
                        'years_affected': 0
                    }
                else:
                    # Has flood intersection - calculate actual risk
                    risk_score, risk_level, risk_details = calculate_multi_year_road_flood_risk_optimized(
                        road_line=road_line,
                        flood_unions_by_year=flood_unions_by_year,
                        all_floods_union=all_floods_union,
                        flood_gdf_by_year=flood_gdf_by_year,  # Pass for duration analysis
                        road_properties=row.to_dict(),
                        start_year=start_year,
                        end_year=end_year
                    )
                
                # Track roads with risk
                if risk_score > 0:
                    roads_with_risk += 1
                    file_roads_with_risk += 1
                
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
                
                # Create feature for ALL roads (with and without risk)
                properties = row.to_dict()
                # Remove geometry from properties if present
                properties.pop('geometry', None)
                
                # Add risk information
                properties.update({
                    'flood_risk_score': risk_score,
                    'flood_risk_level': risk_level,
                    'risk_details': risk_details
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
                  f"{file_roads_checked} checked, {file_roads_with_risk} at risk")
            
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
    print(f"[COMPLETE] Road Risk Assessment")
    print(f"{'='*60}")
    print(f"Total roads processed: {total_roads_processed:,}")
    print(f"Roads with flood risk: {roads_with_risk:,}")
    print(f"Roads included in map: {len(all_road_features):,}")
    
    return all_road_features


def create_calderdale_flood_map(
    flood_file: str = "Recorded_Flood_Outlines.geojson",
    start_year: int = 2000,
    end_year: int = 2025,
    output_file: str = None,
    road_geojson_dir: str = None,
    include_roads: bool = False,
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
        output_file = f"calderdale_flood_map_{start_year}_{end_year}.html"

    if not os.path.exists(flood_file):
        print(f"[ERROR] Cannot find file: {flood_file}")
        return

    print("=" * 60)
    print("Calderdale Flood Map (2000-2025)")
    print("=" * 60)

    # ----- 1. Define Calderdale bounds in WGS84 -----
    min_lon, max_lon = -2.25, -1.75
    min_lat, max_lat = 53.55, 53.85

    # ----- 2. Transform bounds to EPSG:27700 for clipping -----
    transformer_to_27700 = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
    min_x, min_y = transformer_to_27700.transform(min_lon, min_lat)
    max_x, max_y = transformer_to_27700.transform(max_lon, max_lat)

    print(f"Calderdale bounding box (EPSG:27700):")
    print(f"  min_x = {min_x:.1f}, min_y = {min_y:.1f}")
    print(f"  max_x = {max_x:.1f}, max_y = {max_y:.1f}")

    # Create bounding box for clipping
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
    print(f"Filtering by year range ({start_year}-{end_year})...")
    # Parse years and add as column
    flood_gdf["start_year"] = flood_gdf["start_date"].apply(_parse_start_year)
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

    # ----- 5. Clip to Calderdale bounding box -----
    print("Clipping to Calderdale bounding box...")
    # Create a GeoDataFrame for the bounding box to use with clip
    bbox_gdf = gpd.GeoDataFrame([1], geometry=[calderdale_bbox], crs=flood_gdf.crs)
    
    # Use clip to actually cut geometries at the boundary (reduces file size)
    calderdale_gdf = gpd.clip(filtered_gdf, bbox_gdf)

    if len(calderdale_gdf) == 0:
        print("[ERROR] No flood events found in Calderdale area")
        return

    print(f"[INFO] Clipped to {len(calderdale_gdf):,} outlines in Calderdale area")
    print(f"[INFO] Geometries clipped to boundary box (reduced file size)")

    # ----- 6. Transform coordinates to WGS84 -----
    print("Transforming coordinates to WGS84...")
    calderdale_wgs84 = calderdale_gdf.to_crs(epsg=4326)
    
    # Use Calderdale center for map (same as flood_risk_map.py)
    center_lat = (min_lat + max_lat) / 2
    center_lon = (min_lon + max_lon) / 2
    
    # Use fixed zoom level (same as flood_risk_map.py)
    zoom_start = 11

    print(f"[MAP] Center: ({center_lat:.4f}, {center_lon:.4f}), Zoom: {zoom_start}")
    
    # Define Calderdale bounds in WGS84 for map limits (square region)
    calderdale_bounds_wgs84 = [
        [min_lat, min_lon],  # Southwest corner
        [max_lat, max_lon],  # Northeast corner
    ]
    
    # Convert GeoDataFrame back to GeoJSON format for Folium
    calderdale_features = json.loads(calderdale_wgs84.to_json())
    calderdale_features = calderdale_features.get("features", [])
    
    # ----- 6.5. Load and assess road flood risk (if requested) -----
    road_features = []
    if include_roads and road_geojson_dir:
        road_features = load_roads_with_multi_year_flood_risk(
            road_geojson_dir=road_geojson_dir,
            calderdale_gdf=calderdale_gdf,
            calderdale_bbox=calderdale_bbox,
            start_year=start_year,
            end_year=end_year
        )
    elif include_roads and not road_geojson_dir:
        print("\n[WARNING] Road risk assessment requested but no road directory provided")
    else:
        print("\n[INFO] Skipping road risk assessment")

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

    # ----- 9. Add road risk layer (if available) -----
    if road_features:
        print(f"\nAdding road risk layer to map...")
        print(f"  Total roads loaded: {len(road_features):,}")
        
        # Count roads by risk level
        risk_stats = {}
        roads_with_risk_count = 0
        for feature in road_features:
            risk_level = feature.get('properties', {}).get('flood_risk_level', 'Unknown')
            risk_stats[risk_level] = risk_stats.get(risk_level, 0) + 1
            if risk_level != 'No Flood Risk' and risk_level != 'No Historical Risk':
                roads_with_risk_count += 1
        
        print(f"  Roads with flood risk: {roads_with_risk_count:,}")
        print(f"  Roads without flood risk: {len(road_features) - roads_with_risk_count:,}")
        print(f"  Risk level distribution:")
        for level in ['Extreme Risk', 'Critical Risk', 'High Risk', 'Moderate Risk', 'Low Risk', 'Minimal Risk', 'No Flood Risk']:
            count = risk_stats.get(level, 0)
            if count > 0:
                pct = count / len(road_features) * 100
                print(f"    {level}: {count:,} roads ({pct:.1f}%)")
        
        # Define risk colors and styles
        def get_risk_color(risk_level):
            color_map = {
                'Extreme Risk': '#8B0000',      # Dark Red
                'Critical Risk': '#DC143C',     # Crimson
                'High Risk': '#FF4500',         # OrangeRed
                'Moderate Risk': '#FFD700',     # Gold
                'Low Risk': '#87CEEB',          # SkyBlue
                'Minimal Risk': '#32CD32',      # LimeGreen
                'No Flood Risk': '#228B22',     # Forest Green (no flood risk)
                'No Historical Risk': '#90EE90' # LightGreen
            }
            return color_map.get(risk_level, '#808080')
        
        def get_risk_weight(risk_level):
            weight_map = {
                'Extreme Risk': 5,
                'Critical Risk': 4,
                'High Risk': 3,
                'Moderate Risk': 2.5,
                'Low Risk': 2,
                'Minimal Risk': 1.5,
                'No Flood Risk': 1.5,           # Slightly thicker for visibility
                'No Historical Risk': 1
            }
            return weight_map.get(risk_level, 2)
        
        def road_style(feature):
            props = feature.get('properties', {})
            risk_level = props.get('flood_risk_level', 'Unknown')
            
            return {
                'color': get_risk_color(risk_level),
                'weight': get_risk_weight(risk_level),
                'opacity': 0.85
            }
        
        # Create road GeoJSON
        road_geojson = {
            'type': 'FeatureCollection',
            'features': road_features
        }
        
        # Create road layer with detailed tooltip
        road_layer = folium.FeatureGroup(name='Road Flood Risk (Multi-Year)', show=True)
        
        # Flatten risk_details for tooltip display
        for feature in road_features:
            props = feature.get('properties', {})
            details = props.get('risk_details', {})
            props['years_affected'] = details.get('flood_frequency', 0)
            props['frequency_pct'] = details.get('frequency_ratio', 0)
            props['coverage_pct'] = details.get('cumulative_inundation_ratio', 0)
            props['road_type_info'] = details.get('road_type', 'Unknown')
        
        folium.GeoJson(
            road_geojson,
            style_function=road_style,
            tooltip=folium.GeoJsonTooltip(
                fields=[
                    'flood_risk_level', 
                    'flood_risk_score',
                    'years_affected',
                    'frequency_pct',
                    'coverage_pct',
                    'road_type_info'
                ],
                aliases=[
                    'Risk Level:',
                    'Risk Score:',
                    'Years Affected:',
                    'Frequency (%):',
                    'Coverage (%):',
                    'Road Type:'
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
        
        # Create comprehensive title with risk statistics
        risk_counts = {}
        for feature in road_features:
            risk_level = feature.get('properties', {}).get('flood_risk_level', 'Unknown')
            risk_counts[risk_level] = risk_counts.get(risk_level, 0) + 1
        
        legend_items = []
        legend_colors = {
            'Extreme Risk': '#8B0000',
            'Critical Risk': '#DC143C',
            'High Risk': '#FF4500',
            'Moderate Risk': '#FFD700',
            'Low Risk': '#87CEEB',
            'Minimal Risk': '#32CD32',
            'No Flood Risk': '#228B22'
        }
        
        for level in ['Extreme Risk', 'Critical Risk', 'High Risk', 'Moderate Risk', 'Low Risk', 'Minimal Risk', 'No Flood Risk']:
            count = risk_counts.get(level, 0)
            if count > 0:
                color = legend_colors.get(level, '#808080')
                legend_items.append(f'''
                    <div style="margin: 3px 0;">
                        <span style="display: inline-block; width: 30px; height: 3px; 
                                     background-color: {color}; vertical-align: middle;"></span>
                        <span style="margin-left: 5px; font-size: 11px;">{level} ({count:,})</span>
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
                Calderdale Flood & Road Risk ({start_year}-{end_year})
            </div>
            <div style="font-size: 11px; color: #555; margin-bottom: 8px;">
                Flood Outlines: {len(calderdale_features):,} | Analysis Period: {end_year-start_year+1} years
            </div>
            <div style="font-size: 11px; color: #555; margin-bottom: 8px;">
                Total Roads: {len(road_features):,} | Years with Floods: {years_with_floods}
            </div>
            <div style="border-top: 1px solid #ddd; padding-top: 8px;">
                <div style="font-weight: bold; font-size: 12px; margin-bottom: 5px;">
                    Multi-Year Road Risk Levels:
                </div>
                {legend_html}
            </div>
            <div style="margin-top: 8px; font-size: 10px; color: #888; border-top: 1px solid #eee; padding-top: 5px;">
                * Based on historical frequency, trend, coverage, and road type
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
                Calderdale Flood Outlines ({start_year}-{end_year})
            </div>
            <div style="font-size: 11px; color: #555;">
                Flood Outlines: {len(calderdale_features):,} | Analysis Period: {end_year-start_year+1} years
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
        print(f"  Roads with risk: {len(road_features):,}")
        print(f"\n  Risk Assessment Algorithm (School Route Analysis):")
        print(f"    - Historical Frequency (20%): Total flood events over study period")
        print(f"    - Spatial Coverage (30%): Percentage of road historically flooded")
        print(f"    - Route Blockage (25%): Endpoint flooding causing complete isolation")
        print(f"    - Flood Duration (10%): Impact weighted by flood duration (inspired by Pregnolato et al. 2017)")
        print(f"    - Flood Persistence (5%): Systematic flooding at road center")
        print(f"    - Infrastructure Vulnerability (10%): Road type & school route importance")
    print("=" * 60)


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
        help="Directory containing road GeoJSON files (enables road risk assessment)",
    )
    parser.add_argument(
        "--include-roads",
        action="store_true",
        help="Include road flood risk assessment (requires --road-dir)",
    )

    args = parser.parse_args()

    if args.start_year > args.end_year:
        parser.error("Start year must be less than or equal to end year")
    
    if args.include_roads and not args.road_dir:
        print("[WARNING] --include-roads specified but --road-dir not provided")
        print("           Road risk assessment will be skipped")

    create_calderdale_flood_map(
        flood_file=args.flood_file,
        start_year=args.start_year,
        end_year=args.end_year,
        output_file=args.output,
        road_geojson_dir=args.road_dir,
        include_roads=args.include_roads,
    )


if __name__ == "__main__":
    main()

