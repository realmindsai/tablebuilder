# Ali Brisbane Travel Distance Analysis — Design Spec

## Purpose

Evaluate which of 3 candidate locations is most accessible to an existing client base of 422 individuals (165 households) across 76 Brisbane/SEQ postcodes. Uses mesh-block-level granularity with OSRM driving routes to produce weighted travel time/distance metrics and visualizations.

## Target Locations

| ID | Address | Role |
|----|---------|------|
| loc_1 | 628 Ipswich Road, Annerley | Candidate |
| loc_2 | 9 Pallinup Street, Riverhills | Candidate |
| loc_3 | 33 Baxter Street, Fortitude Valley | Current location |

## Input Data

**Source**: `ali_brisbane/Brisbane Family data.xlsx` (Sheet1)

| Column | Type | Description |
|--------|------|-------------|
| Individual ID | int | Unique person identifier |
| Household CDS | int | Household identifier (groups individuals) |
| Postcode (Cleansed) | int | Australian postcode (76 unique values) |

Summary: 422 individuals, 165 households, 76 postcodes. Range from inner Brisbane (4000) to regional QLD (4870 Cairns, 4700 Bundaberg).

## Technology Stack

- **Language**: R
- **Pipeline**: `targets` (caching, dependency tracking)
- **Spatial**: `sf` for geometry operations
- **Routing**: OSRM via `http://louisa_ts:5000`
- **Visualization**: `leaflet` (maps), `ggplot2` (violin plots), `gt` (tables)
- **Project location**: `../ali_brisbane/` (new repo)

## Pipeline Stages

```
_targets.R:

 1. tar_read_xlsx        Read Excel, clean column names
 2. tar_summarise_pcs    Count individuals & households per postcode
 3. tar_download_mb      Download ABS 2021 mesh block boundaries (gpkg)
 4. tar_download_mb_pop  Download ABS 2021 mesh block population counts
 5. tar_download_poa     Download ABS 2021 POA boundaries (for map polygons)
 6. tar_build_mb_map     Spatial join mesh blocks to postcodes, calc population shares
 7. tar_spread_weights   Distribute postcode counts across mesh blocks proportionally
 8. tar_geocode_locs     Hardcoded lat/lon for the 3 target locations
 9. tar_osrm_routes      OSRM driving routes: each MB centroid x 3 locations
10. tar_aggregate        Roll up weighted stats per postcode x location
11. tar_summary_table    Overall summary per location
12. tar_full_matrix      Full postcode x location matrix (CSV export)
13. tar_violin_plots     Violin plots of travel time distributions
14. tar_map              Leaflet interactive map
```

## Outlier Exclusion

Postcodes with a straight-line distance from the centroid of all postcodes greater than 3 standard deviations above the mean are excluded from the analysis. This removes distant outliers like Cairns (4870), Bundaberg (4700), etc. that would skew weighted averages. Excluded postcodes are listed in the output for transparency but not included in summary stats or visualizations.

This filter is applied early in the pipeline (after tar_summarise_pcs, before OSRM calls) to avoid wasting routing queries on distant postcodes.

## Weighting Logic

### Mesh Block Spread

For each postcode in the input data:

1. Identify all mesh blocks within that postcode (spatial join)
2. Get ABS Census population for each mesh block
3. Calculate each mesh block's share of the postcode's total population
4. Spread the input data's individual count (and household count) across mesh blocks proportionally

Example — Postcode 4509 (32 individuals, ~8 households):

```
Mesh block populations within 4509:
  MB_A: 150 people  → 30% of postcode
  MB_B: 200 people  → 40% of postcode
  MB_C: 150 people  → 30% of postcode

Spread individuals:
  MB_A: 32 x 0.30 = 9.6
  MB_B: 32 x 0.40 = 12.8
  MB_C: 32 x 0.30 = 9.6

Spread households similarly.
```

### Household Size

Calculated from the input data: individuals per Household CDS, averaged per postcode.

## OSRM Routing

- Endpoint: `http://louisa_ts:5000/route/v1/driving/{lon1},{lat1};{lon2},{lat2}`
- Returns: distance (meters), duration (seconds)
- Estimated calls: ~76 postcodes x ~50-100 mesh blocks each x 3 locations = 11,000-23,000 routes
- Optimization: Use OSRM table API (`/table/v1/driving/`) to batch mesh block centroids per chunk with 3 destinations

## Output Metrics

### Per Postcode x Location

| Metric | Description |
|--------|-------------|
| n_individuals | Count from input data |
| n_households | Count from input data |
| avg_household_size | individuals / households |
| weighted_mean_distance_km | Mean distance weighted by MB spread count |
| weighted_mean_duration_min | Mean duration weighted by MB spread count |
| min_mb_distance_km | Minimum mesh block centroid distance |
| max_mb_distance_km | Maximum mesh block centroid distance |
| min_mb_duration_min | Minimum mesh block centroid duration |
| max_mb_duration_min | Maximum mesh block centroid duration |

### Per Location (Summary)

| Metric | Description |
|--------|-------------|
| weighted_mean_distance_km | Overall weighted mean across all postcodes |
| weighted_mean_duration_min | Overall weighted mean duration |
| weighted_median_duration_min | Weighted median |
| p25_duration_min | 25th percentile |
| p75_duration_min | 75th percentile |
| pct_within_15min | % individuals within 15 min |
| pct_within_30min | % individuals within 30 min |
| pct_within_45min | % individuals within 45 min |
| pct_within_60min | % individuals within 60 min |

## Visualizations

### 1. Leaflet Interactive Map

- Postcode (POA) polygons coloured by weighted mean travel time to nearest of the 3 locations
- 3 location markers with popup summary stats
- Click postcode polygon to see breakdown to all 3 locations

### 2. Violin Plots (ggplot2)

- 3 violins (one per location) showing distribution of mesh-block-level travel times, weighted by spread population
- Min/max range per postcode overlaid
- Possibly faceted by region (inner Brisbane, outer Brisbane, Gold Coast, regional)

### 3. Summary Table (gt)

- One row per location
- Weighted mean, median, P25/P75, % within time bands

### 4. Full Matrix CSV

- Complete postcode x location data for further analysis

## ABS Data Downloads

| Dataset | Source | Format |
|---------|--------|--------|
| Mesh Block 2021 boundaries | ABS ASGS Edition 3 | GeoPackage (MB_2021_AUST.gpkg) |
| Mesh Block 2021 population | ABS Census 2021 Mesh Block Counts | CSV |
| POA 2021 boundaries | ABS ASGS Edition 3 | GeoPackage (POA_2021_AUST.gpkg) |

These are direct ABS downloads (not via TableBuilder CLI).

## Project Structure

```
../ali_brisbane/
  _targets.R              # Pipeline definition
  R/
    read_data.R           # Excel reading, cleaning
    spatial.R             # ABS downloads, spatial joins, MB mapping
    osrm.R                # OSRM API calls, batching
    aggregate.R           # Weighting, rollups, summary stats
    visualize.R           # Map, violin plots, tables
  data/
    brisbane_family.xlsx  # Copy of input data (or symlink)
    abs/                  # Downloaded ABS spatial/census files
  output/
    summary_table.csv
    full_matrix.csv
    map.html
    violin_plots.png
  renv.lock               # Dependency lockfile
```

## R Package Dependencies

- targets, tarchetypes
- readxl
- sf
- httr2 (OSRM API calls)
- dplyr, tidyr, purrr
- ggplot2
- leaflet, htmlwidgets
- gt
- renv
