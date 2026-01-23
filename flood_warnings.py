import pandas as pd
import geopandas as gpd
import folium
import branca.colormap as cm
import os
#import matplotlib.cm as mpl_cm
import matplotlib
import matplotlib.colors as mpl_colours

ods_path = "Historic_Flood_Warnings/202510 Historic Flood Warnings – EA.ods"

df = pd.read_excel(
    ods_path,
    engine="odf",
    sheet_name=0
)

# Clean CODE column
df["CODE"] = df["CODE"].astype(str).str.strip()

# Frequency per flood area
freq = (
    df.groupby("CODE")
      .size()
      .reset_index(name="frequency")
)

#print(freq.head())

#####################

flood_areas = gpd.read_file("Historic_Flood_Warnings/flood_areas.geojson")


#print(flood_areas.geometry.isna().value_counts())

#print("Original CRS:", flood_areas.crs)
# print("Geometry type:", flood_areas.geometry.iloc[0].geom_type)
# print("Bounds:", flood_areas.total_bounds)


# confirm column name
#print(flood_areas.columns)

gdf = flood_areas.merge(
    freq,
    left_on="fws_tacode",
    right_on="CODE",
    how="inner"
)

print(f"Mapped {len(gdf)} flood areas")

gdf = gdf.to_crs(epsg=4326)

# simplifies the geo stuff so faster
gdf["geometry"] = gdf.geometry.simplify(
    tolerance=0.001,  # degrees now, not metres
    preserve_topology=True
)



# map bbuilding
# colormap = cm.linear.YlOrRd_09.scale(
#     gdf["frequency"].min(),
#     gdf["frequency"].max()
# )

plasma = matplotlib.colormaps["plasma_r"]

norm = mpl_colours.LogNorm(
    vmin=gdf["frequency"].min(),
    vmax=gdf["frequency"].max()
)

def plasma_colour(val):
    return mpl_colours.to_hex(plasma(norm(val)))

def style_function(feature):
    freq = feature["properties"]["frequency"]
    return {
        "fillColor": plasma_colour(freq),
        "color": "black",
        "weight": 0.3,
        "fillOpacity": 0.7,
    }

#colormap.caption = "Flood Watch Frequency"

m = folium.Map(
    location=[54.5, -2.5],
    zoom_start=6,
    tiles="CartoDB positron"
)

# def style_function(feature):
#     freq = feature["properties"]["frequency"]
#     return {
#         "fillColor": colormap(freq),
#         "color": "black",
#         "weight": 0.6,
#         "fillOpacity": 0.6,
#     }

folium.GeoJson(
    gdf,
    style_function=style_function,
    tooltip=folium.GeoJsonTooltip(
        fields=[
            "fws_tacode",
            "ta_name",
            #"floodAreaType",
            "frequency"
        ],
        aliases=[
            "Code",
            "Area Name",
            #"Type",
            "Times Flagged"
        ],
        localize=True
    ),
    name="Flood Areas"
).add_to(m)

#colormap.add_to(m)
folium.LayerControl().add_to(m)

legend_html = """
<div style="
position: fixed;
bottom: 30px;
left: 30px;
width: 220px;
height: 120px;
background-color: white;
border: 2px solid grey;
z-index: 9999;
font-size: 14px;
padding: 10px;
">
<b>Flood Warning Frequency</b><br>
Low &nbsp;<span style="background:#f0f921;">&nbsp;&nbsp;&nbsp;</span>
&nbsp;→&nbsp;
High <span style="background:#0d0887;">&nbsp;&nbsp;&nbsp;</span><br>
(Log scale)
</div>
"""

m.get_root().html.add_child(folium.Element(legend_html))

#m.save("flood_frequency_map.html")
m.save(os.path.expanduser("~/Downloads/flood_frequency_map.html"))

