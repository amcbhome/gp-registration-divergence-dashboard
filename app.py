from pathlib import Path
import json

import pandas as pd
import plotly.express as px
import streamlit as st
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from streamlit_plotly_events import plotly_events

st.set_page_config(
    page_title="GP Registration Divergence Dashboard",
    page_icon="📊",
    layout="wide",
)

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
CSV_PATH = DATA_DIR / "list_size_census_comparison.csv"
GEOJSON_PATH = DATA_DIR / "local_authority_boundaries.geojson"

REGION_ORDER = [
    "North East", "North West", "Yorkshire and The Humber",
    "East Midlands", "West Midlands", "East of England",
    "London", "South East", "South West",
]


@st.cache_data
def load_data(csv_bytes):
    from io import BytesIO

    df = pd.read_csv(BytesIO(csv_bytes))
    required = [
        "Local Authority Code", "Local Authority Name",
        "Census Count", "List Size", "Region Name",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("CSV is missing columns: " + ", ".join(missing))

    for col in ["Census Count", "List Size"]:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        )
    df = df.dropna(subset=["Census Count", "List Size"]).copy()
    df["Local Authority Code"] = df["Local Authority Code"].astype(str).str.strip()
    df["Difference"] = df["List Size"] - df["Census Count"]
    df["Percentage difference"] = (
        df["Difference"] / df["Census Count"].where(df["Census Count"] != 0) * 100
    )
    return df


@st.cache_data
def build_region_geojson(geojson_bytes, code_region_pairs):
    from io import BytesIO

    source = json.load(BytesIO(geojson_bytes))
    code_to_region = dict(code_region_pairs)
    grouped = {}

    for feature in source.get("features", []):
        props = feature.get("properties", {})
        code = str(props.get("LAD21CD", "")).strip()
        region = code_to_region.get(code)
        if not region:
            continue
        try:
            geom = shape(feature["geometry"])
            if not geom.is_empty:
                grouped.setdefault(region, []).append(geom)
        except Exception:
            continue

    features = []
    for region in REGION_ORDER:
        geometries = grouped.get(region, [])
        if not geometries:
            continue
        features.append({
            "type": "Feature",
            "properties": {"Region Name": region},
            "geometry": mapping(unary_union(geometries)),
        })
    return {"type": "FeatureCollection", "features": features}


def fmt_num(value):
    return f"{value:,.0f}"


def fmt_pct(value):
    return f"{value:+.2f}%"


st.title("GP Registrations vs Census Population")
st.caption(
    "Explore differences between GP registration list sizes and Census 2021 "
    "population across the nine regions of England."
)

# File uploader fallback means the app remains diagnosable before data files
# have been added to the public repository.
csv_upload = None
geo_upload = None
if not CSV_PATH.exists() or not GEOJSON_PATH.exists():
    st.warning(
        "The app code is installed, but one or both data files are missing from "
        "the repository's data/ folder. Upload the CSV and GeoJSON below, or add "
        "them to data/ in GitHub."
    )
    csv_upload = st.file_uploader(
        "Comparison dataset (CSV)", type=["csv"], key="csv_upload"
    )
    geo_upload = st.file_uploader(
        "Local-authority boundaries (GeoJSON)", type=["geojson", "json"],
        key="geo_upload"
    )

if csv_upload is not None:
    csv_bytes = csv_upload.getvalue()
elif CSV_PATH.exists():
    csv_bytes = CSV_PATH.read_bytes()
else:
    st.stop()

if geo_upload is not None:
    geo_bytes = geo_upload.getvalue()
elif GEOJSON_PATH.exists():
    geo_bytes = GEOJSON_PATH.read_bytes()
else:
    st.stop()

try:
    df = load_data(csv_bytes)
except Exception as exc:
    st.error(f"Could not read the CSV: {exc}")
    st.stop()

# National KPIs
census_total = df["Census Count"].sum()
list_total = df["List Size"].sum()
difference_total = list_total - census_total
percentage_total = difference_total / census_total * 100 if census_total else 0

st.subheader("England overview")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Census population", fmt_num(census_total))
k2.metric("GP registrations", fmt_num(list_total))
k3.metric("Difference", fmt_num(difference_total), delta=fmt_pct(percentage_total))
k4.metric("Local authorities in dataset", f"{df['Local Authority Code'].nunique():,}")

st.info(
    "A difference between GP registrations and Census population is a discrepancy "
    "between two data sources, not proof that individual patient records are invalid."
)

# Regional totals
regional = (
    df.groupby("Region Name", as_index=False)
    .agg(
        Census=("Census Count", "sum"),
        Registrations=("List Size", "sum"),
        Authorities=("Local Authority Code", "nunique"),
    )
)
regional["Difference"] = regional["Registrations"] - regional["Census"]
regional["Percentage difference"] = (
    regional["Difference"] / regional["Census"].where(regional["Census"] != 0) * 100
)
regional["Region Name"] = pd.Categorical(
    regional["Region Name"], categories=REGION_ORDER, ordered=True
)
regional = regional.sort_values("Region Name").reset_index(drop=True)

try:
    region_geojson = build_region_geojson(
        geo_bytes, tuple(zip(df["Local Authority Code"], df["Region Name"]))
    )
except Exception as exc:
    st.error(f"Could not prepare the map boundaries: {exc}")
    st.stop()

geo_regions = [f["properties"]["Region Name"] for f in region_geojson["features"]]
map_data = regional[regional["Region Name"].astype(str).isin(geo_regions)].copy()
map_data["Region Name"] = map_data["Region Name"].astype(str)

if not region_geojson["features"]:
    st.error(
        "No map polygons matched the CSV local-authority codes. This app expects "
        "December 2021 boundaries with the LAD21CD property. Check the boundary file."
    )
    st.stop()

st.subheader("Select a region on the map")
st.write("Tap a region once to show its local-authority data below.")

low = float(map_data["Percentage difference"].min())
high = float(map_data["Percentage difference"].max())
if low == high:
    high = low + 0.01

fig = px.choropleth_mapbox(
    map_data,
    geojson=region_geojson,
    locations="Region Name",
    featureidkey="properties.Region Name",
    color="Percentage difference",
    color_continuous_scale="YlOrRd",
    range_color=(low, high),
    hover_name="Region Name",
    hover_data={
        "Census": ":,.0f",
        "Registrations": ":,.0f",
        "Difference": ":,.0f",
        "Percentage difference": ":.2f",
        "Authorities": True,
    },
    mapbox_style="open-street-map",
    center={"lat": 52.7, "lon": -1.7},
    zoom=4.6,
    opacity=0.75,
    labels={
        "Percentage difference": "Difference (%)",
        "Census": "Census population",
        "Registrations": "GP registrations",
        "Difference": "Difference",
        "Authorities": "Local authorities",
    },
)
fig.update_layout(
    height=600,
    margin={"r": 0, "t": 5, "l": 0, "b": 0},
    coloraxis_colorbar_title="Difference (%)",
)
fig.update_traces(marker_line_width=1.4, marker_line_color="#333333")

clicked = plotly_events(
    fig,
    click_event=True,
    select_event=False,
    hover_event=False,
    override_height=600,
    key="england_region_map",
)

if clicked:
    region_clicked = clicked[0].get("location")
    if region_clicked in REGION_ORDER:
        st.session_state["selected_region"] = region_clicked

selected_region = st.session_state.get("selected_region")

if selected_region:
    selected = regional[regional["Region Name"].astype(str) == selected_region]
    if not selected.empty:
        row = selected.iloc[0]
        st.divider()
        st.header(selected_region)
        a, b, c, d = st.columns(4)
        a.metric("Census population", fmt_num(row["Census"]))
        b.metric("GP registrations", fmt_num(row["Registrations"]))
        c.metric("Difference", fmt_num(row["Difference"]))
        d.metric("Difference (%)", fmt_pct(row["Percentage difference"]))

        local = df[df["Region Name"] == selected_region].sort_values(
            "Percentage difference", ascending=False
        )
        table = local[
            ["Local Authority Name", "Census Count", "List Size",
             "Difference", "Percentage difference"]
        ].rename(columns={
            "Local Authority Name": "Local authority",
            "Census Count": "Census population",
            "List Size": "GP registrations",
            "Percentage difference": "Difference (%)",
        })

        st.caption("Local authorities ranked by percentage difference, largest first.")
        st.dataframe(
            table,
            use_container_width=True,
            hide_index=True,
            height=520,
            column_config={
                "Census population": st.column_config.NumberColumn(format="%d"),
                "GP registrations": st.column_config.NumberColumn(format="%d"),
                "Difference": st.column_config.NumberColumn(format="%+d"),
                "Difference (%)": st.column_config.NumberColumn(format="%+.2f%%"),
            },
        )
        if st.button("Clear selection"):
            st.session_state.pop("selected_region", None)
            st.rerun()

st.divider()
st.subheader("Regional comparison")
summary = regional.copy()
summary["Region Name"] = summary["Region Name"].astype(str)
summary = summary[
    ["Region Name", "Authorities", "Census", "Registrations",
     "Difference", "Percentage difference"]
].rename(columns={
    "Region Name": "Region",
    "Authorities": "Local authorities",
    "Census": "Census population",
    "Registrations": "GP registrations",
    "Percentage difference": "Difference (%)",
}).sort_values("Difference (%)", ascending=False)

st.dataframe(
    summary,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Census population": st.column_config.NumberColumn(format="%d"),
        "GP registrations": st.column_config.NumberColumn(format="%d"),
        "Difference": st.column_config.NumberColumn(format="%+d"),
        "Difference (%)": st.column_config.NumberColumn(format="%+.2f%%"),
    },
)

st.caption(
    "Boundary matching uses LAD21CD from December 2021 local-authority boundaries. "
    "The CSV contains 309 records. Differences may reflect reference dates, coverage, "
    "population movement, registration practices, or other methodological factors."
)
