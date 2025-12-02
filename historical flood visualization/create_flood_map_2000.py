"""
Generate interactive map of floods and road networks
Creates visualization HTML map for flood data with risk assessment
"""

import json
import os
from pathlib import Path
from pyproj import Transformer
from datetime import datetime

def load_year_floods(file_path: str, year: int):
    """Load flood data for a specific year"""
    print(f"Loading flood data for year {year}...")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if data.get('type') != 'FeatureCollection':
        return None
    
    all_features = data.get('features', [])
    year_features = []
    
    for feature in all_features:
        props = feature.get('properties', {})
        start_date_str = props.get('start_date', '')
        
        if start_date_str:
            try:
                date_obj = datetime.fromisoformat(start_date_str.replace('T', ' ').split('.')[0])
                if date_obj.year == year:
                    year_features.append(feature)
            except:
                try:
                    year_from_str = int(start_date_str[:4])
                    if year_from_str == year:
                        year_features.append(feature)
                except:
                    pass
    
    print(f"Found {len(year_features):,} flood outlines for year {year}")
    return year_features


def get_flood_bounds(features):
    """Calculate the bounding box of flood coverage"""
    all_x = []
    all_y = []
    
    for feature in features:
        geometry = feature.get('geometry', {})
        geom_type = geometry.get('type')
        coords = geometry.get('coordinates', [])
        
        def extract_coords(c):
            if isinstance(c[0], (int, float)):
                all_x.append(c[0])
                all_y.append(c[1])
            else:
                for item in c:
                    extract_coords(item)
        
        if coords:
            extract_coords(coords)
    
    if not all_x or not all_y:
        return None
    
    # Extend boundary range (add 20% buffer zone)
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    
    width = max_x - min_x
    height = max_y - min_y
    
    bounds = {
        'min_x': min_x - width * 0.2,
        'max_x': max_x + width * 0.2,
        'min_y': min_y - height * 0.2,
        'max_y': max_y + height * 0.2
    }
    
    return bounds


def calculate_road_flood_risk(road_line, flood_union, road_properties=None):
    """
    Calculate flood risk score for a road (0-100)
    
    Parameters:
    - road_line: Shapely LineString object
    - flood_union: Merged flood polygon
    - road_properties: Road attributes (used to determine road type)
    
    Returns:
    - risk_score: Risk score from 0-100
    - risk_level: Risk level string
    - details: Detailed scoring information dictionary
    """
    
    # 1. Spatial intersection analysis (weight 40%)
    try:
        intersection = road_line.intersection(flood_union)
        intersection_length = intersection.length if intersection else 0
        road_length = road_line.length
        
        if road_length > 0:
            intersection_ratio = intersection_length / road_length
        else:
            intersection_ratio = 0
        
        # Convert to score (0-100)
        intersection_score = min(intersection_ratio * 100, 100)
    except:
        intersection_score = 0
        intersection_ratio = 0
    
    # 2. Road endpoint containment analysis (weight 25%)
    try:
        start_point = road_line.coords[0]
        end_point = road_line.coords[-1]
        
        from shapely.geometry import Point
        start_in_flood = flood_union.contains(Point(start_point))
        end_in_flood = flood_union.contains(Point(end_point))
        
        if start_in_flood and end_in_flood:
            endpoint_score = 100  # Both ends flooded
        elif start_in_flood or end_in_flood:
            endpoint_score = 60   # One end flooded
        else:
            endpoint_score = 20   # Both ends not in flood
    except:
        endpoint_score = 20
    
    # 3. Flood core distance analysis (weight 20%)
    try:
        # Calculate distance from road midpoint to flood boundary
        midpoint = road_line.interpolate(0.5, normalized=True)
        
        if flood_union.contains(midpoint):
            # Road midpoint is in flood, calculate distance to boundary
            distance_to_boundary = midpoint.distance(flood_union.boundary)
            # Greater distance (deeper into core) = higher risk
            # Assume >100m is core area
            core_score = min(distance_to_boundary / 100 * 100, 100)
        else:
            # Road midpoint not in flood, lower risk
            core_score = 30
    except:
        core_score = 50
    
    # 4. Road type analysis (weight 15%)
    road_type_multiplier = 1.0
    road_type_name = "Unknown"
    
    if road_properties:
        # Get road type from attributes (common fields in UK OS data)
        road_class = road_properties.get('class', '').lower()
        road_function = road_properties.get('roadFunction', '').lower()
        
        if 'motorway' in road_class or 'motorway' in road_function:
            road_type_multiplier = 0.8  # Motorway, risk reduced 20%
            road_type_name = "Motorway"
        elif 'a road' in road_class or 'primary' in road_function:
            road_type_multiplier = 0.9  # A Road, risk reduced 10%
            road_type_name = "A Road"
        elif 'b road' in road_class or 'secondary' in road_function:
            road_type_multiplier = 1.0  # B Road, risk unchanged
            road_type_name = "B Road"
        elif 'minor' in road_class or 'local' in road_function:
            road_type_multiplier = 1.1  # Minor road, risk increased 10%
            road_type_name = "Minor Road"
        else:
            road_type_multiplier = 1.2  # Local street, risk increased 20%
            road_type_name = "Local Street"
    
    road_type_score = 50 * road_type_multiplier
    
    # Calculate comprehensive risk score
    risk_score = (
        intersection_score * 0.40 +
        endpoint_score * 0.25 +
        core_score * 0.20 +
        road_type_score * 0.15
    )
    
    # Ensure score is within 0-100 range
    risk_score = max(0, min(100, risk_score))
    
    # Determine risk level (English)
    if risk_score >= 90:
        risk_level = "Critical Risk"
    elif risk_score >= 70:
        risk_level = "High Risk"
    elif risk_score >= 50:
        risk_level = "Moderate Risk"
    elif risk_score >= 30:
        risk_level = "Low Risk"
    else:
        risk_level = "Minimal Risk"
    
    # Detailed information
    details = {
        'risk_score': round(risk_score, 2),
        'risk_level': risk_level,
        'intersection_ratio': round(intersection_ratio * 100, 2),
        'intersection_score': round(intersection_score, 2),
        'endpoint_score': round(endpoint_score, 2),
        'core_score': round(core_score, 2),
        'road_type': road_type_name,
        'road_type_score': round(road_type_score, 2)
    }
    
    return risk_score, risk_level, details


def load_roads_in_flood_polygons(road_geojson_dir: str, flood_features_transformed, transformer):
    """
    Load only roads truly within flood polygons and calculate flood risk score for each road
    Use spatial geometry to determine if roads intersect with flood polygons
    """
    try:
        from shapely.geometry import LineString, Polygon, MultiPolygon, Point
        from shapely.ops import unary_union
    except ImportError:
        print("[ERROR] Need to install shapely library: pip install shapely")
        return []
    
    road_dir = Path(road_geojson_dir) / 'RoadLink'
    
    if not road_dir.exists():
        print(f"[ERROR] Road network directory does not exist: {road_dir}")
        return []
    
    print(f"\nBuilding flood polygons...")
    
    # Build flood polygon collection
    flood_polygons = []
    for feature in flood_features_transformed:
        geom = feature.get('geometry', {})
        geom_type = geom.get('type')
        coords = geom.get('coordinates', [])
        
        if geom_type == 'Polygon' and coords:
            outer_ring = coords[0]
            ring_tuples = [(coord[0], coord[1]) for coord in outer_ring]
            
            if len(ring_tuples) >= 3:
                try:
                    poly = Polygon(ring_tuples)
                    if poly.is_valid:
                        flood_polygons.append(poly)
                except:
                    pass
        
        elif geom_type == 'MultiPolygon' and coords:
            for polygon in coords:
                if polygon and len(polygon) > 0:
                    outer_ring = polygon[0]
                    ring_tuples = [(coord[0], coord[1]) for coord in outer_ring]
                    
                    if len(ring_tuples) >= 3:
                        try:
                            poly = Polygon(ring_tuples)
                            if poly.is_valid:
                                flood_polygons.append(poly)
                        except:
                            pass
    
    print(f"  Built {len(flood_polygons)} flood polygons")
    
    if not flood_polygons:
        print("  Warning: Cannot build flood polygons")
        return []
    
    # Merge all flood polygons
    try:
        flood_union = unary_union(flood_polygons)
        bounds = flood_union.bounds  # (minx, miny, maxx, maxy)
        print(f"  Flood polygons merged")
        print(f"  Bounds: Longitude[{bounds[0]:.4f} ~ {bounds[2]:.4f}], Latitude[{bounds[1]:.4f} ~ {bounds[3]:.4f}]")
    except Exception as e:
        print(f"  Warning: Cannot merge flood polygons: {e}")
        flood_union = None
        bounds = None
    
    if not flood_union:
        return []
    
    print(f"\nFiltering roads within flood area...")
    
    road_files = sorted(list(road_dir.glob('*.geojson')))
    all_road_features = []
    
    for i, road_file in enumerate(road_files, 1):
        try:
            with open(road_file, 'r', encoding='utf-8') as f:
                road_data = json.load(f)
            
            features = road_data.get('features', [])
            
            # Keep only roads that intersect with flood polygons
            roads_in_flood = []
            for feature in features:
                geom = feature.get('geometry', {})
                geom_type = geom.get('type')
                coords = geom.get('coordinates', [])
                
                if not coords:
                    continue
                
                # Transform road coordinates and check if intersects with flood
                if geom_type == 'LineString':
                    transformed_coords = []
                    for coord in coords:
                        lon, lat = transformer.transform(coord[0], coord[1])
                        transformed_coords.append((lon, lat))
                    
                    try:
                        road_line = LineString(transformed_coords)
                        
                        # Check if road intersects with flood area
                        if road_line.intersects(flood_union):
                            # Calculate risk score
                            risk_score, risk_level, risk_details = calculate_road_flood_risk(
                                road_line, flood_union, feature.get('properties', {})
                            )
                            
                            # Save transformed coordinates
                            geom['coordinates'] = [[lon, lat] for lon, lat in transformed_coords]
                            
                            # Add risk information to properties
                            if 'properties' not in feature:
                                feature['properties'] = {}
                            feature['properties']['flood_risk_score'] = risk_score
                            feature['properties']['flood_risk_level'] = risk_level
                            feature['properties']['risk_details'] = risk_details
                            
                            roads_in_flood.append(feature)
                    except:
                        pass
                
                elif geom_type == 'MultiLineString':
                    transformed_lines = []
                    has_intersection = False
                    intersecting_lines = []
                    
                    for line in coords:
                        transformed_line = []
                        for coord in line:
                            lon, lat = transformer.transform(coord[0], coord[1])
                            transformed_line.append((lon, lat))
                        transformed_lines.append(transformed_line)
                        
                        try:
                            road_line = LineString(transformed_line)
                            if road_line.intersects(flood_union):
                                has_intersection = True
                                intersecting_lines.append(road_line)
                        except:
                            pass
                    
                    if has_intersection and intersecting_lines:
                        # Use first intersecting segment to calculate risk (simplified)
                        # Or merge all segments
                        from shapely.ops import linemerge
                        try:
                            merged_line = linemerge(intersecting_lines)
                            if merged_line.geom_type == 'LineString':
                                primary_line = merged_line
                            else:
                                primary_line = intersecting_lines[0]
                        except:
                            primary_line = intersecting_lines[0]
                        
                        # Calculate risk score
                        risk_score, risk_level, risk_details = calculate_road_flood_risk(
                            primary_line, flood_union, feature.get('properties', {})
                        )
                        
                        geom['coordinates'] = [[[lon, lat] for lon, lat in line] for line in transformed_lines]
                        
                        # Add risk information to properties
                        if 'properties' not in feature:
                            feature['properties'] = {}
                        feature['properties']['flood_risk_score'] = risk_score
                        feature['properties']['flood_risk_level'] = risk_level
                        feature['properties']['risk_details'] = risk_details
                        
                        roads_in_flood.append(feature)
            
            if roads_in_flood:
                all_road_features.extend(roads_in_flood)
                print(f"    [{i}/{len(road_files)}] {road_file.stem}: {len(roads_in_flood):,} roads in flood area")
        
        except Exception as e:
            print(f"    [{i}/{len(road_files)}] {road_file.stem}: Error - {e}")
        
        # Limit total count to avoid file being too large
        if len(all_road_features) > 100000:
            print(f"    Reached limit (100,000 roads), stopping load")
            break
    
    print(f"\n  Total found {len(all_road_features):,} roads in flood area")
    return all_road_features


def create_flood_map_2022(flood_file: str, road_geojson_dir: str,
                          output_file: str = 'flood_map_2022.html',
                          include_roads: bool = True,
                          year: int = 2000):
    """
    Create interactive map of floods and road network for specified year
    
    Parameters:
    - flood_file: Flood data file path
    - road_geojson_dir: Road network data directory
    - output_file: Output HTML filename
    - include_roads: Whether to include road network data
    - year: Year (default 2000)
    """
    
    try:
        import folium
        from folium import plugins
    except ImportError:
        print("[ERROR] Need to install folium library: pip install folium")
        return
    
    print("=" * 60)
    print(f"Creating {year} Flood & Road Network Interactive Map")
    print("=" * 60)
    
    # 1. Load flood data for specified year
    year_floods = load_year_floods(flood_file, year)
    
    if not year_floods:
        print(f"Error: No flood data found for year {year}")
        print(f"\nTip: Check if flood data file contains records for {year}")
        return
    
    # 2. Calculate flood coverage boundaries (original coordinate system)
    print("\nCalculating flood coverage area...")
    bounds_original = get_flood_bounds(year_floods)
    
    if not bounds_original:
        print("Error: Cannot calculate boundaries")
        return
    
    print(f"Flood coverage range (EPSG:27700 - British National Grid):")
    print(f"  X: {bounds_original['min_x']:.0f} ~ {bounds_original['max_x']:.0f} meters")
    print(f"  Y: {bounds_original['min_y']:.0f} ~ {bounds_original['max_y']:.0f} meters")
    
    # 3. Transform flood data coordinates
    print("\nTransforming flood data coordinates (EPSG:27700 -> EPSG:4326)...")
    transformer = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    
    def transform_coords(coords):
        if isinstance(coords[0], (int, float)):
            lon, lat = transformer.transform(coords[0], coords[1])
            return [lon, lat]
        else:
            return [transform_coords(c) for c in coords]
    
    # Create copy of transformed flood features
    year_floods_transformed = []
    all_coords = []
    
    for i, feature in enumerate(year_floods):
        # Deep copy feature
        import copy
        feature_copy = copy.deepcopy(feature)
        
        geom = feature_copy.get('geometry', {})
        if geom.get('coordinates'):
            geom['coordinates'] = transform_coords(geom['coordinates'])
            
            # Extract coordinates for center point calculation
            coords = geom['coordinates']
            def extract_coords(c):
                if isinstance(c[0], (int, float)):
                    all_coords.append([c[0], c[1]])
                else:
                    for item in c:
                        extract_coords(item)
            extract_coords(coords)
        
        year_floods_transformed.append(feature_copy)
        
        if (i + 1) % 100 == 0 or (i + 1) == len(year_floods):
            print(f"    Transformed {i + 1}/{len(year_floods)} flood outlines...")
    
    # Calculate center point and transformed bounds (based on actual transformed coordinates)
    if all_coords:
        all_lons = [c[0] for c in all_coords]
        all_lats = [c[1] for c in all_coords]
        
        # Calculate boundaries directly using transformed coordinates
        min_lon, max_lon = min(all_lons), max(all_lons)
        min_lat, max_lat = min(all_lats), max(all_lats)
        
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        
        print(f"\nActual flood coverage range (lat/lon):")
        print(f"  Longitude: {min_lon:.4f}° ~ {max_lon:.4f}°")
        print(f"  Latitude: {min_lat:.4f}° ~ {max_lat:.4f}°")
        print(f"  Map center: ({center_lat:.4f}°, {center_lon:.4f}°)")
    else:
        # Default England center
        center_lat, center_lon = 52.5, -2.0
        print(f"\nUsing default center: ({center_lat}, {center_lon})")
    
    # 4. Load road network within flood polygons (if needed)
    road_features = []
    if include_roads:
        road_features = load_roads_in_flood_polygons(road_geojson_dir, year_floods_transformed, transformer)
    else:
        print("\nSkipping road network data loading")
    
    # 5. Create map
    print(f"\nCreating interactive map...")
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=7,
        tiles='OpenStreetMap'
    )
    
    # Add multiple basemap options
    folium.TileLayer('CartoDB positron', name='Light Map').add_to(m)
    folium.TileLayer('CartoDB dark_matter', name='Dark Map').add_to(m)
    
    # 6. Add flood layer
    print(f"  Adding flood outline layer ({len(year_floods_transformed)} outlines)...")
    flood_geojson = {
        'type': 'FeatureCollection',
        'features': year_floods_transformed
    }
    
    def flood_style(feature):
        return {
            'fillColor': '#4A90E2',
            'color': '#2E5C8A',
            'weight': 1,
            'fillOpacity': 0.5,
            'opacity': 0.7
        }
    
    flood_layer = folium.FeatureGroup(name=f'Flood Outlines ({year})', show=True)
    folium.GeoJson(
        flood_geojson,
        style_function=flood_style,
        tooltip=folium.GeoJsonTooltip(
            fields=['name', 'start_date', 'end_date'],
            aliases=['Name:', 'Start Date:', 'End Date:'],
            localize=True
        )
    ).add_to(flood_layer)
    flood_layer.add_to(m)
    
    # 7. Add road network layer (if available) - colored by risk level
    if road_features:
        print(f"  Adding road network layer ({len(road_features):,} roads)...")
        
        # Count roads by risk level
        risk_stats = {
            'Critical Risk': 0,
            'High Risk': 0,
            'Moderate Risk': 0,
            'Low Risk': 0,
            'Minimal Risk': 0
        }
        
        for feature in road_features:
            risk_level = feature.get('properties', {}).get('flood_risk_level', 'Unknown')
            if risk_level in risk_stats:
                risk_stats[risk_level] += 1
        
        print(f"    Risk level distribution:")
        for level, count in risk_stats.items():
            if count > 0:
                print(f"      {level}: {count:,} roads")
        
        # Define risk colors and styles (higher contrast colors)
        def get_risk_color(risk_level):
            color_map = {
                'Critical Risk': '#DC143C',  # 深红色 (Crimson)
                'High Risk': '#FF4500',      # 橙红色 (OrangeRed)
                'Moderate Risk': '#FFD700',  # 金黄色 (Gold)
                'Low Risk': '#87CEEB',       # 天蓝色 (SkyBlue)
                'Minimal Risk': '#32CD32'    # 石灰绿 (LimeGreen)
            }
            return color_map.get(risk_level, '#808080')  # 默认灰色
        
        def get_risk_weight(risk_level):
            weight_map = {
                'Critical Risk': 4,
                'High Risk': 3,
                'Moderate Risk': 2.5,
                'Low Risk': 2,
                'Minimal Risk': 1.5
            }
            return weight_map.get(risk_level, 2)
        
        def road_style(feature):
            props = feature.get('properties', {})
            risk_level = props.get('flood_risk_level', 'Unknown')
            risk_score = props.get('flood_risk_score', 0)
            
            return {
                'color': get_risk_color(risk_level),
                'weight': get_risk_weight(risk_level),
                'opacity': 0.85
            }
        
        # Create road network layer
        road_geojson = {
            'type': 'FeatureCollection',
            'features': road_features
        }
        
        road_layer = folium.FeatureGroup(name='Road Network Risk Assessment', show=True)
        
        # Add tooltip to display detailed risk information
        folium.GeoJson(
            road_geojson,
            style_function=road_style,
            tooltip=folium.GeoJsonTooltip(
                fields=['flood_risk_level', 'flood_risk_score'],
                aliases=['Risk Level:', 'Risk Score:'],
                localize=True
            )
        ).add_to(road_layer)
        road_layer.add_to(m)
    else:
        print("  No road network data added")
    
    # 8. Add controls
    folium.LayerControl(collapsed=False).add_to(m)
    plugins.Fullscreen(position='topright', title='Fullscreen', title_cancel='Exit Fullscreen').add_to(m)
    plugins.MeasureControl(primary_length_unit='meters', primary_area_unit='sqmeters').add_to(m)
    
    # 9. 添加地图标题和风险图例（英文）
    if road_features:
        # 计算风险统计
        risk_counts = {}
        for feature in road_features:
            risk_level = feature.get('properties', {}).get('flood_risk_level', 'Unknown')
            risk_counts[risk_level] = risk_counts.get(risk_level, 0) + 1
        
        legend_items = []
        legend_colors = {
            'Critical Risk': '#DC143C',
            'High Risk': '#FF4500',
            'Moderate Risk': '#FFD700',
            'Low Risk': '#87CEEB',
            'Minimal Risk': '#32CD32'
        }
        
        for level in ['Critical Risk', 'High Risk', 'Moderate Risk', 'Low Risk', 'Minimal Risk']:
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
                    background-color: white;
                    border: 2px solid grey;
                    z-index: 9999;
                    font-size: 14px;
                    padding: 10px;
                    border-radius: 5px;
                    box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
            <div style="font-weight: bold; font-size: 16px; margin-bottom: 8px;">
                England Floods & Road Risk ({year})
            </div>
            <div style="font-size: 11px; color: #555; margin-bottom: 8px;">
                Flood Outlines: {len(year_floods):,} | Affected Roads: {len(road_features):,}
            </div>
            <div style="border-top: 1px solid #ddd; padding-top: 8px;">
                <div style="font-weight: bold; font-size: 12px; margin-bottom: 5px;">
                    Road Closure Risk Levels:
                </div>
                {legend_html}
            </div>
            <div style="margin-top: 8px; font-size: 10px; color: #888; border-top: 1px solid #eee; padding-top: 5px;">
                * Estimated based on spatial analysis
            </div>
        </div>
        '''
    else:
        title_html = f'''
        <div style="position: fixed; 
                    top: 10px; 
                    left: 50px; 
                    width: auto;
                    height: auto;
                    background-color: white;
                    border: 2px solid grey;
                    z-index: 9999;
                    font-size: 18px;
                    font-weight: bold;
                    padding: 10px;
                    border-radius: 5px;
                    box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
            <p style="margin: 0;">England Flood Coverage ({year})</p>
            <p style="margin: 5px 0 0 0; font-size: 12px; font-weight: normal;">
                Flood Outlines: {len(year_floods):,}
            </p>
        </div>
        '''
    
    m.get_root().html.add_child(folium.Element(title_html))
    
    # 10. Save map
    print(f"\nSaving map to: {output_file}")
    m.save(output_file)
    
    html_size = os.path.getsize(output_file) / (1024 * 1024)
    
    print("\n" + "=" * 60)
    print("[OK] Map generated successfully!")
    print("=" * 60)
    print(f"  Filename: {output_file}")
    print(f"  File size: {html_size:.2f} MB")
    print(f"  Year: {year}")
    print(f"  Flood outline count: {len(year_floods):,}")
    
    if road_features:
        print(f"  Affected roads: {len(road_features):,}")
        
        # Calculate risk level distribution
        risk_distribution = {}
        for feature in road_features:
            risk_level = feature.get('properties', {}).get('flood_risk_level', 'Unknown')
            risk_distribution[risk_level] = risk_distribution.get(risk_level, 0) + 1
        
        print("\nRoad closure risk assessment results:")
        for level in ['Critical Risk', 'High Risk', 'Moderate Risk', 'Low Risk', 'Minimal Risk']:
            count = risk_distribution.get(level, 0)
            if count > 0:
                percentage = count / len(road_features) * 100
                print(f"  {level}: {count:,} roads ({percentage:.1f}%)")
    
    print("\nLayer description:")
    print(f"  [Blue areas] Flood coverage for year {year}")
    if road_features:
        print(f"  [Colored roads] Colored by closure risk level:")
        print(f"    - Crimson: Critical Risk (almost certain closure)")
        print(f"    - Orange-Red: High Risk (very likely closure)")
        print(f"    - Gold: Moderate Risk (possible partial closure)")
        print(f"    - Sky Blue: Low Risk (minor impact)")
        print(f"    - Lime Green: Minimal Risk (basically unaffected)")
    
    print("\nUsage:")
    print(f"  1. Open in browser: {output_file}")
    print(f"  2. Use mouse wheel to zoom map")
    print(f"  3. Hover over roads to see risk level and score")
    print(f"  4. Click flood outlines for detailed information")
    print(f"  5. Use top-right controls to toggle layers")
    print("\nAlgorithm description:")
    print(f"  Risk score based on: Spatial intersection(40%) + Endpoint containment(25%) +")
    print(f"                       Core distance(20%) + Road type(15%)")
    print("=" * 60)


if __name__ == "__main__":
    # Configure file paths and year
    flood_file = "Recorded_Flood_Outlines.geojson"
    road_geojson_dir = "data/geojson"
    target_year = 2000  # Can be modified to any year
    output_file = f"flood_map_{target_year}.html"
    
    # Check if files exist
    if not os.path.exists(flood_file):
        print(f"[ERROR] Cannot find flood data file: {flood_file}")
        print("Please ensure the file is in current directory")
        exit(1)
    
    if not os.path.exists(road_geojson_dir):
        print(f"[WARNING] Cannot find road network data directory: {road_geojson_dir}")
        print("Will only generate flood outline map without road network")
        include_roads = False
    else:
        include_roads = True
    
    print(f"Flood Map Generator for Year {target_year}")
    print("-" * 60)
    print(f"Target year: {target_year}")
    print(f"Flood data: {flood_file}")
    print(f"Road data: {road_geojson_dir}")
    print(f"Output file: {output_file}")
    print(f"Include roads: {'Yes' if include_roads else 'No'}")
    print("-" * 60)
    print()
    
    # Generate map
    create_flood_map_2022(
        flood_file=flood_file,
        road_geojson_dir=road_geojson_dir,
        output_file=output_file,
        include_roads=include_roads,
        year=target_year
    )

