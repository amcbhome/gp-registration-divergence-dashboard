from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="GP Registrations vs Census Population",
    page_icon="📊",
    layout="wide",
)

DATA_PATH = (
    Path(__file__).parent
    / "data"
    / "list_size_census_comparison.csv"
)

REGION_ORDER = [
    "North East",
    "North West",
    "Yorkshire and The Humber",
    "East Midlands",
    "West Midlands",
    "East of England",
    "London",
    "South East",
    "South West",
]


@st.cache_data
def load_data(file_bytes):
    from io import BytesIO

    df = pd.read_csv(BytesIO(file_bytes))

    required = [
        "Local Authority Code",
        "Local Authority Name",
        "Census Count",
        "List Size",
        "Region Name",
    ]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError("Missing CSV columns: " + ", ".join(missing))

    for column in ["Census Count", "List Size"]:
        df[column] = pd.to_numeric(
            df[column].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        )

    df = df.dropna(subset=["Census Count", "List Size", "Region Name"]).copy()
    df["Difference"] = df["List Size"] - df["Census Count"]
    df["Difference (%)"] = (
        df["Difference"] / df["Census Count"].where(df["Census Count"] != 0) * 100
    )
    return df


def number(value):
    return f"{value:,.0f}"


def percentage(value):
    return f"{value:+.2f}%"


st.title("GP Registrations vs Census Population")
st.caption(
    "Compare GP registration list sizes with Census 2021 population "
    "across the nine regions of England."
)

if not DATA_PATH.exists():
    st.error("The comparison CSV was not found at data/list_size_census_comparison.csv.")
    st.stop()

try:
    df = load_data(DATA_PATH.read_bytes())
except Exception as exc:
    st.error(f"Could not load the comparison data: {exc}")
    st.stop()

# England overview
census_total = df["Census Count"].sum()
registration_total = df["List Size"].sum()
difference_total = registration_total - census_total
difference_pct = difference_total / census_total * 100 if census_total else 0

st.subheader("England overview")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Census population", number(census_total))
col2.metric("GP registrations", number(registration_total))
col3.metric("Difference", number(difference_total), delta=percentage(difference_pct))
col4.metric("Local authorities", f"{df['Local Authority Code'].nunique():,}")

st.info(
    "A difference between GP registrations and Census population is a discrepancy "
    "between two data sources. It is not, by itself, proof that individual patient "
    "records are invalid."
)

# Regional selector in the sidebar
st.sidebar.header("Explore a region")
regions_present = set(df["Region Name"].dropna().astype(str))
regions = [region for region in REGION_ORDER if region in regions_present]
selected_region = st.sidebar.selectbox("Select an English region", regions)

# Regional totals
regional = (
    df.groupby("Region Name", as_index=False)
    .agg(
        Census_population=("Census Count", "sum"),
        GP_registrations=("List Size", "sum"),
        Local_authorities=("Local Authority Code", "nunique"),
    )
)
regional["Difference"] = regional["GP_registrations"] - regional["Census_population"]
regional["Difference (%)"] = (
    regional["Difference"]
    / regional["Census_population"].where(regional["Census_population"] != 0)
    * 100
)

selected = regional[regional["Region Name"] == selected_region].iloc[0]

st.divider()
st.header(selected_region)
st.caption("Regional totals and local-authority comparisons for the selected region.")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Census population", number(selected["Census_population"]))
col2.metric("GP registrations", number(selected["GP_registrations"]))
col3.metric("Difference", number(selected["Difference"]))
col4.metric("Difference (%)", percentage(selected["Difference (%)"]))

local = df[df["Region Name"] == selected_region].copy()
local = local.sort_values("Difference (%)", ascending=False)

table = local[
    [
        "Local Authority Name",
        "Census Count",
        "List Size",
        "Difference",
        "Difference (%)",
    ]
].rename(
    columns={
        "Local Authority Name": "Local authority",
        "Census Count": "Census population",
        "List Size": "GP registrations",
    }
)

st.subheader("Local-authority table")
st.caption(
    f"{len(table)} local authorities, ranked by percentage difference "
    "from highest to lowest."
)
st.dataframe(
    table,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Census population": st.column_config.NumberColumn(format="%d"),
        "GP registrations": st.column_config.NumberColumn(format="%d"),
        "Difference": st.column_config.NumberColumn(format="%+d"),
        "Difference (%)": st.column_config.NumberColumn(format="%+.2f%%"),
    },
)

with st.expander("Compare all nine regions"):
    all_regions = regional.copy()
    all_regions["Region Name"] = pd.Categorical(
        all_regions["Region Name"], categories=REGION_ORDER, ordered=True
    )
    all_regions = all_regions.sort_values("Region Name")
    all_regions = all_regions.rename(
        columns={
            "Region Name": "Region",
            "Census_population": "Census population",
            "GP_registrations": "GP registrations",
            "Local_authorities": "Local authorities",
        }
    )
    st.dataframe(
        all_regions,
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
    "Differences may reflect reference dates, coverage, population movement, "
    "registration practices, or other methodological factors. They should be "
    "investigated rather than automatically interpreted as invalid registrations."
)
