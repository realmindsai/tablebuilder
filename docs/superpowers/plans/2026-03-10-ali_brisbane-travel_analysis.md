# Ali Brisbane Travel Distance Analysis — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an R targets pipeline that calculates OSRM driving distances/times from mesh block centroids within client postcodes to 3 candidate locations, producing weighted summary stats, a full matrix CSV, violin plots, and a leaflet map.

**Architecture:** R targets pipeline in `../ali_brisbane/`. Functions in `R/` directory, tests in `tests/testthat/`. ABS mesh block boundaries + allocation file + Census population counts downloaded and cached in `data/abs/`. OSRM table API called in batches. Results aggregated with population-proportional weights.

**Tech Stack:** R, targets, sf, httr2, dplyr/tidyr, ggplot2, leaflet, gt, readxl, testthat

---

## File Structure

| File | Responsibility |
|------|---------------|
| `_targets.R` | Pipeline definition — all targets wired together |
| `R/read_data.R` | `read_excel_data()`, `summarise_postcodes()` |
| `R/locations.R` | `get_target_locations()` — hardcoded lat/lon for 3 sites |
| `R/spatial.R` | `download_abs_data()`, `load_mb_boundaries()`, `load_poa_boundaries()`, `load_mb_allocation()`, `load_mb_population()` |
| `R/mb_mapping.R` | `build_mb_postcode_map()`, `filter_outlier_postcodes()` |
| `R/weights.R` | `spread_weights()` |
| `R/osrm.R` | `query_osrm_table()`, `route_all_mb_to_locations()` |
| `R/aggregate.R` | `aggregate_postcode_location()`, `summarise_locations()`, `build_full_matrix()` |
| `R/visualize.R` | `make_violin_plots()`, `make_map()`, `make_summary_table_gt()` |
| `tests/testthat/test-read_data.R` | Tests for Excel reading and postcode summarisation |
| `tests/testthat/test-mb_mapping.R` | Tests for MB-postcode mapping and outlier filtering |
| `tests/testthat/test-weights.R` | Tests for population-proportional spread |
| `tests/testthat/test-aggregate.R` | Tests for aggregation and summary stats |
| `tests/testthat/test-locations.R` | Tests for target location definitions |
| `tests/testthat/test-osrm.R` | Tests for OSRM query building (requires live server for integration) |
| `tests/testthat/test-visualize.R` | Tests for visualization output (violin, map, table) |

---

## Chunk 1: Project Setup and Data Reading

### Task 1: Scaffold the R Project

**Files:**
- Create: `../ali_brisbane/_targets.R`
- Create: `../ali_brisbane/.gitignore`
- Create: `../ali_brisbane/DESCRIPTION`
- Create: `../ali_brisbane/tests/testthat.R`

- [ ] **Step 1: Create project directory structure**

```bash
mkdir -p ../ali_brisbane/{R,data/abs,output,tests/testthat}
```

- [ ] **Step 2: Copy input Excel file**

```bash
cp ali_brisbane/Brisbane\ Family\ data.xlsx ../ali_brisbane/data/brisbane_family.xlsx
```

- [ ] **Step 3: Create DESCRIPTION file** (needed for testthat)

```
Package: alibrisbane
Title: Ali Brisbane Travel Distance Analysis
Version: 0.1.0
Description: OSRM travel distance analysis from client postcodes to candidate locations.
License: MIT
Suggests:
    testthat (>= 3.0.0)
Config/testthat/edition: 3
```

- [ ] **Step 4: Create tests/testthat.R**

```r
# ABOUTME: testthat bootstrap file
# ABOUTME: Loads the package test infrastructure
library(testthat)
test_check("alibrisbane")
```

- [ ] **Step 5: Create .gitignore**

```
_targets/
data/abs/*.zip
data/abs/*.shp
data/abs/*.shx
data/abs/*.dbf
data/abs/*.prj
data/abs/*.xlsx
data/abs/mb_shp/
data/abs/poa_shp/
*.Rproj.user
.Rhistory
.RData
.Rproj
output/
renv/
```

- [ ] **Step 6: Create skeleton _targets.R**

```r
# ABOUTME: targets pipeline for Ali Brisbane travel distance analysis
# ABOUTME: Calculates OSRM driving distances from client postcodes to 3 candidate locations

library(targets)

tar_source()

list(
  # Targets will be added as functions are implemented
)
```

- [ ] **Step 7: Install R dependencies**

```bash
cd ../ali_brisbane && Rscript -e '
install.packages(c(
  "targets", "tarchetypes", "readxl", "sf", "httr2",
  "dplyr", "tidyr", "purrr", "readr", "ggplot2",
  "leaflet", "htmlwidgets", "gt", "testthat",
  "RColorBrewer"
))
'
```

- [ ] **Step 8: Initialize git repo and commit**

```bash
cd ../ali_brisbane && git init && git add -A && git commit -m "chore: scaffold R targets project for travel analysis"
```

---

### Task 2: Read Excel Data

**Files:**
- Create: `R/read_data.R`
- Create: `tests/testthat/test-read_data.R`

- [ ] **Step 1: Write the failing tests**

```r
# ABOUTME: Tests for Excel data reading and postcode summarisation
# ABOUTME: Validates data cleaning and aggregation logic

library(testthat)

test_that("read_excel_data returns cleaned tibble", {
  # Use the real data file
  df <- read_excel_data("data/brisbane_family.xlsx")
  expect_s3_class(df, "tbl_df")
  expect_named(df, c("individual_id", "household_id", "postcode"))
  expect_type(df$individual_id, "double")
  expect_type(df$household_id, "double")
  expect_type(df$postcode, "character")
  expect_gt(nrow(df), 400)
})

test_that("summarise_postcodes counts correctly", {
  df <- tibble::tibble(
    individual_id = 1:7,
    household_id = c(1, 1, 1, 2, 2, 3, 3),
    postcode = c("4000", "4000", "4000", "4000", "4000", "4001", "4001")
  )
  result <- summarise_postcodes(df)
  expect_equal(nrow(result), 2)
  expect_equal(result$n_individuals[result$postcode == "4000"], 5)
  expect_equal(result$n_households[result$postcode == "4000"], 2)
  expect_equal(result$n_individuals[result$postcode == "4001"], 2)
  expect_equal(result$n_households[result$postcode == "4001"], 1)
  expect_equal(result$avg_household_size[result$postcode == "4000"], 5 / 2)
  expect_equal(result$avg_household_size[result$postcode == "4001"], 2 / 1)
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-read_data.R")'
```

Expected: FAIL — `read_excel_data` not found.

- [ ] **Step 3: Write implementation**

```r
# ABOUTME: Functions to read and summarise the Brisbane Family Excel data
# ABOUTME: Cleans column names and aggregates individual/household counts per postcode

library(readxl)
library(dplyr)

read_excel_data <- function(path) {
  raw <- read_excel(path, sheet = "Sheet1")
  raw |>
    rename(
      individual_id = 1,
      household_id = 2,
      postcode = 3
    ) |>
    mutate(postcode = as.character(as.integer(postcode))) |>
    filter(!is.na(postcode))
}

summarise_postcodes <- function(df) {
  df |>
    group_by(postcode) |>
    summarise(
      n_individuals = n(),
      n_households = n_distinct(household_id),
      .groups = "drop"
    ) |>
    mutate(avg_household_size = n_individuals / n_households)
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-read_data.R")'
```

Expected: PASS

- [ ] **Step 5: Wire into _targets.R**

Add to the target list in `_targets.R`:

```r
  tar_target(raw_data, read_excel_data("data/brisbane_family.xlsx")),
  tar_target(postcode_summary, summarise_postcodes(raw_data)),
```

- [ ] **Step 6: Commit**

```bash
git add R/read_data.R tests/testthat/test-read_data.R _targets.R
git commit -m "feat: add Excel data reading and postcode summarisation"
```

---

### Task 3: Target Locations

**Files:**
- Create: `R/locations.R`

- [ ] **Step 1: Write the locations function**

```r
# ABOUTME: Defines the 3 target locations with hardcoded coordinates
# ABOUTME: Returns an sf data frame with location ID, name, address, role, and geometry

library(sf)
library(tibble)

get_target_locations <- function() {
  tibble(
    location_id = c("loc_1", "loc_2", "loc_3"),
    name = c("Annerley", "Riverhills", "Fortitude Valley"),
    address = c(
      "628 Ipswich Road, Annerley",
      "9 Pallinup Street, Riverhills",
      "33 Baxter Street, Fortitude Valley"
    ),
    role = c("Candidate", "Candidate", "Current"),
    lon = c(153.0340, 152.9140, 153.0360),
    lat = c(-27.5100, -27.5590, -27.4560)
  ) |>
    st_as_sf(coords = c("lon", "lat"), crs = 4326)
}
```

- [ ] **Step 2: Write test for locations**

Create `tests/testthat/test-locations.R`:

```r
# ABOUTME: Tests for target location definitions
# ABOUTME: Validates coordinates, CRS, and structure of the 3 locations

library(testthat)
library(sf)

test_that("get_target_locations returns sf with 3 locations", {
  locs <- get_target_locations()
  expect_s3_class(locs, "sf")
  expect_equal(nrow(locs), 3)
  expect_equal(st_crs(locs)$epsg, 4326)
  expect_true(all(c("location_id", "name", "address", "role") %in% names(locs)))
})

test_that("location coordinates are in Brisbane region", {
  locs <- get_target_locations()
  coords <- st_coordinates(locs)
  # Brisbane is roughly lon 152.5-153.5, lat -28 to -27
  expect_true(all(coords[, 1] > 152.5 & coords[, 1] < 153.5))
  expect_true(all(coords[, 2] > -28 & coords[, 2] < -27))
})
```

- [ ] **Step 3: Run test to verify it fails, then passes after implementation**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-locations.R")'
```

- [ ] **Step 4: Wire into _targets.R**

```r
  tar_target(locations, get_target_locations()),
```

- [ ] **Step 5: Commit**

```bash
git add R/locations.R tests/testthat/test-locations.R _targets.R
git commit -m "feat: add target locations with hardcoded coordinates"
```

---

## Chunk 2: Spatial Data and Mesh Block Mapping

### Task 4: Download ABS Spatial Data

**Files:**
- Create: `R/spatial.R`

**Context:** We need 4 ABS datasets:
1. Mesh Block 2021 boundaries (Shapefile, 217 MB) — for centroids
2. POA 2021 boundaries (Shapefile, 53 MB) — for map visualization
3. POA 2021 allocation file (XLSX, 17.7 MB) — maps each MB to its POA (NOTE: the main MB allocation does NOT include POA)
4. Census 2021 Mesh Block Counts (XLSX, 14.5 MB) — person counts per MB (NOT from DataPacks — DataPacks only go to SA1)

**Download URLs:**
- MB boundaries: `https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/digital-boundary-files/MB_2021_AUST_SHP_GDA2020.zip`
- POA boundaries: `https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/digital-boundary-files/POA_2021_AUST_GDA2020_SHP.zip`
- POA allocation: `https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/allocation-files/POA_2021_AUST.xlsx`
- MB population: `https://www.abs.gov.au/census/guide-census-data/mesh-block-counts/2021/Mesh%20Block%20Counts%2C%202021.xlsx`

**Note:** ABS download URLs may change. If automatic download fails, the functions print the manual download URL and instructions. Files are cached in `data/abs/` so downloads only happen once.

- [ ] **Step 1: Write spatial data loading functions**

```r
# ABOUTME: Functions to download and load ABS spatial data (MB boundaries, POA boundaries, allocation, population)
# ABOUTME: Caches downloads in data/abs/ to avoid re-downloading

library(sf)
library(dplyr)
library(readr)

# Download a file if it doesn't already exist locally
download_if_missing <- function(url, dest_path) {
  if (file.exists(dest_path)) {
    message("Using cached: ", dest_path)
    return(dest_path)
  }
  dir.create(dirname(dest_path), recursive = TRUE, showWarnings = FALSE)
  message("Downloading: ", url)
  download.file(url, dest_path, mode = "wb")
  dest_path
}

# Extract a zip file, return the directory containing extracted files
extract_zip <- function(zip_path, exdir = NULL) {
  if (is.null(exdir)) {
    exdir <- tools::file_path_sans_ext(zip_path)
  }
  if (!dir.exists(exdir)) {
    unzip(zip_path, exdir = exdir)
  }
  exdir
}

# Load Mesh Block 2021 boundaries for QLD + NSW (border postcodes)
# Returns sf object with MB_CODE_2021 and geometry
load_mb_boundaries <- function(abs_dir = "data/abs") {
  # Look for already-extracted shapefile
  shp_files <- list.files(abs_dir, pattern = "MB_2021.*\\.shp$", full.names = TRUE, recursive = TRUE)
  if (length(shp_files) == 0) {
    zip_url <- "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/digital-boundary-files/MB_2021_AUST_SHP_GDA2020.zip"
    zip_path <- file.path(abs_dir, "MB_2021_AUST_SHP_GDA2020.zip")
    tryCatch(
      download_if_missing(zip_url, zip_path),
      error = function(e) {
        stop(
          "Could not download MB boundaries. Please download manually from:\n",
          "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/digital-boundary-files\n",
          "Save the MB shapefile zip to: ", zip_path
        )
      }
    )
    extract_zip(zip_path, file.path(abs_dir, "mb_shp"))
    shp_files <- list.files(abs_dir, pattern = "MB_2021.*\\.shp$", full.names = TRUE, recursive = TRUE)
  }
  if (length(shp_files) == 0) stop("No MB shapefile found in ", abs_dir)
  mb <- st_read(shp_files[1], quiet = TRUE)
  # Filter to QLD (3) + NSW (1) to handle border postcodes
  ste_col <- grep("STE_CODE|STATE_CODE", names(mb), value = TRUE, ignore.case = TRUE)[1]
  if (is.na(ste_col)) stop("No state code column found in MB boundaries. Columns: ", paste(names(mb), collapse = ", "))
  mb <- mb |> filter(!!sym(ste_col) %in% c("1", "3"))
  mb
}

# Load POA 2021 boundaries
load_poa_boundaries <- function(abs_dir = "data/abs") {
  shp_files <- list.files(abs_dir, pattern = "POA_2021.*\\.shp$", full.names = TRUE, recursive = TRUE)
  if (length(shp_files) == 0) {
    zip_url <- "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/digital-boundary-files/POA_2021_AUST_GDA2020_SHP.zip"
    zip_path <- file.path(abs_dir, "POA_2021_AUST_GDA2020_SHP.zip")
    tryCatch(
      download_if_missing(zip_url, zip_path),
      error = function(e) {
        stop(
          "Could not download POA boundaries. Please download manually from:\n",
          "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/digital-boundary-files\n",
          "Save the POA shapefile zip to: ", zip_path
        )
      }
    )
    extract_zip(zip_path, file.path(abs_dir, "poa_shp"))
    shp_files <- list.files(abs_dir, pattern = "POA_2021.*\\.shp$", full.names = TRUE, recursive = TRUE)
  }
  if (length(shp_files) == 0) stop("No POA shapefile found in ", abs_dir)
  st_read(shp_files[1], quiet = TRUE)
}

# Load MB-to-POA allocation from ASGS POA allocation file (XLSX)
# NOTE: The main MB_2021_AUST allocation does NOT include POA.
# POA mapping is in a SEPARATE file: POA_2021_AUST.xlsx
# Returns tibble with mb_code and poa_code columns
load_mb_allocation <- function(abs_dir = "data/abs") {
  xlsx_path <- file.path(abs_dir, "POA_2021_AUST.xlsx")
  if (!file.exists(xlsx_path)) {
    xlsx_url <- "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/allocation-files/POA_2021_AUST.xlsx"
    tryCatch(
      download_if_missing(xlsx_url, xlsx_path),
      error = function(e) {
        stop(
          "Could not download POA allocation file. Please download manually from:\n",
          "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/allocation-files\n",
          "Save POA_2021_AUST.xlsx to: ", xlsx_path
        )
      }
    )
  }
  alloc <- readxl::read_excel(xlsx_path)
  # Find MB_CODE and POA_CODE columns
  mb_col <- grep("MB_CODE", names(alloc), value = TRUE, ignore.case = TRUE)[1]
  poa_col <- grep("POA_CODE", names(alloc), value = TRUE, ignore.case = TRUE)[1]
  if (is.na(mb_col) || is.na(poa_col)) {
    stop("Could not find MB_CODE and POA_CODE columns in allocation file. Columns: ", paste(names(alloc), collapse = ", "))
  }
  alloc |>
    select(mb_code = !!sym(mb_col), poa_code = !!sym(poa_col)) |>
    mutate(across(everything(), as.character))
}

# Load Census 2021 Mesh Block population counts (dedicated XLSX, NOT from DataPacks)
# DataPacks only go down to SA1. This is the standalone MB Counts product.
# Returns tibble with mb_code and population columns
load_mb_population <- function(abs_dir = "data/abs") {
  xlsx_path <- file.path(abs_dir, "Mesh_Block_Counts_2021.xlsx")
  if (!file.exists(xlsx_path)) {
    xlsx_url <- "https://www.abs.gov.au/census/guide-census-data/mesh-block-counts/2021/Mesh%20Block%20Counts%2C%202021.xlsx"
    tryCatch(
      download_if_missing(xlsx_url, xlsx_path),
      error = function(e) {
        stop(
          "Census 2021 MB population file not found.\n",
          "Please download from: https://www.abs.gov.au/census/guide-census-data/mesh-block-counts/latest-release\n",
          "Save to: ", xlsx_path
        )
      }
    )
  }
  pop <- readxl::read_excel(xlsx_path)
  # Columns: MB_CODE_2021, Person_Usually_Resident, Dwelling
  mb_col <- grep("MB_CODE", names(pop), value = TRUE, ignore.case = TRUE)[1]
  pop_col <- grep("Person_Usually_Resident|Person.*Resident|Persons", names(pop), value = TRUE, ignore.case = TRUE)[1]
  if (is.na(mb_col) || is.na(pop_col)) {
    stop("Could not find MB_CODE and population columns. Columns: ", paste(names(pop), collapse = ", "))
  }
  pop |>
    select(mb_code = !!sym(mb_col), population = !!sym(pop_col)) |>
    mutate(mb_code = as.character(mb_code), population = as.numeric(population))
}
```

- [ ] **Step 2: Wire into _targets.R**

Add to the target list:

```r
  tar_target(mb_boundaries, load_mb_boundaries("data/abs")),
  tar_target(poa_boundaries, load_poa_boundaries("data/abs")),
  tar_target(mb_allocation, load_mb_allocation("data/abs")),
  tar_target(mb_population, load_mb_population("data/abs")),
```

- [ ] **Step 3: Commit**

```bash
git add R/spatial.R _targets.R
git commit -m "feat: add ABS spatial data download and loading functions"
```

---

### Task 5: Build MB-to-Postcode Map and Outlier Exclusion

**Files:**
- Create: `R/mb_mapping.R`
- Create: `tests/testthat/test-mb_mapping.R`

- [ ] **Step 1: Write the failing tests**

```r
# ABOUTME: Tests for mesh block to postcode mapping and outlier exclusion
# ABOUTME: Uses synthetic spatial data to validate join and filtering logic

library(testthat)
library(sf)
library(tibble)
library(dplyr)

test_that("build_mb_postcode_map joins MB to postcodes with centroids", {
  # Create synthetic MB boundaries (2 MBs)
  mb_bounds <- st_sf(
    MB_CODE_2021 = c("30000001", "30000002"),
    geometry = st_sfc(
      st_point(c(153.0, -27.5)),
      st_point(c(153.1, -27.6))
    ),
    crs = 4326
  ) |> st_buffer(0.01)

  mb_alloc <- tibble(mb_code = c("30000001", "30000002"), poa_code = c("4000", "4001"))
  mb_pop <- tibble(mb_code = c("30000001", "30000002"), population = c(100, 200))
  pc_summary <- tibble(postcode = c("4000", "4001"), n_individuals = c(10, 5), n_households = c(3, 2), avg_household_size = c(10/3, 5/2))

  result <- build_mb_postcode_map(mb_bounds, mb_alloc, mb_pop, pc_summary)

  expect_s3_class(result, "sf")
  expect_true("mb_code" %in% names(result))
  expect_true("postcode" %in% names(result))
  expect_true("population" %in% names(result))
  expect_true("centroid_lon" %in% names(result))
  expect_true("centroid_lat" %in% names(result))
  expect_equal(nrow(result), 2)
})

test_that("build_mb_postcode_map excludes MBs with zero population", {
  mb_bounds <- st_sf(
    MB_CODE_2021 = c("30000001", "30000002", "30000003"),
    geometry = st_sfc(
      st_point(c(153.0, -27.5)),
      st_point(c(153.1, -27.6)),
      st_point(c(153.2, -27.7))
    ),
    crs = 4326
  ) |> st_buffer(0.01)

  mb_alloc <- tibble(mb_code = c("30000001", "30000002", "30000003"), poa_code = c("4000", "4000", "4001"))
  mb_pop <- tibble(mb_code = c("30000001", "30000002", "30000003"), population = c(100, 0, 200))
  pc_summary <- tibble(postcode = c("4000", "4001"), n_individuals = c(10, 5), n_households = c(3, 2), avg_household_size = c(10/3, 5/2))

  result <- build_mb_postcode_map(mb_bounds, mb_alloc, mb_pop, pc_summary)
  expect_equal(nrow(result), 2)  # MB with 0 pop excluded
})

test_that("filter_outlier_postcodes removes postcodes > 3 SD from mean distance", {
  # 5 postcodes: 4 clustered, 1 far away
  pc_summary <- tibble(
    postcode = c("4000", "4001", "4002", "4003", "9999"),
    n_individuals = c(10, 10, 10, 10, 5),
    n_households = c(3, 3, 3, 3, 2),
    avg_household_size = c(10/3, 10/3, 10/3, 10/3, 5/2)
  )
  poa_bounds <- st_sf(
    POA_CODE_2021 = c("4000", "4001", "4002", "4003", "9999"),
    geometry = st_sfc(
      st_point(c(153.0, -27.5)),
      st_point(c(153.01, -27.51)),
      st_point(c(153.02, -27.52)),
      st_point(c(153.03, -27.53)),
      st_point(c(145.0, -16.9))  # Cairns - far away
    ),
    crs = 4326
  ) |> st_buffer(0.01)

  result <- filter_outlier_postcodes(pc_summary, poa_bounds)
  expect_true("9999" %in% result$excluded_postcodes)
  expect_false("9999" %in% result$filtered_summary$postcode)
  expect_equal(nrow(result$filtered_summary), 4)
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-mb_mapping.R")'
```

- [ ] **Step 3: Write implementation**

```r
# ABOUTME: Joins mesh blocks to postcodes and calculates centroids
# ABOUTME: Filters outlier postcodes more than 3 SD from the mean distance to the centroid

library(sf)
library(dplyr)

build_mb_postcode_map <- function(mb_boundaries, mb_allocation, mb_population, postcode_summary) {
  mb_code_col <- grep("MB_CODE", names(mb_boundaries), value = TRUE, ignore.case = TRUE)[1]

  mb_boundaries |>
    rename(mb_code = !!sym(mb_code_col)) |>
    mutate(mb_code = as.character(mb_code)) |>
    st_centroid() |>
    mutate(
      centroid_lon = st_coordinates(geometry)[, 1],
      centroid_lat = st_coordinates(geometry)[, 2]
    ) |>
    st_drop_geometry() |>
    inner_join(mb_allocation, by = "mb_code") |>
    rename(postcode = poa_code) |>
    inner_join(mb_population, by = "mb_code") |>
    filter(postcode %in% postcode_summary$postcode, population > 0) |>
    st_as_sf(coords = c("centroid_lon", "centroid_lat"), crs = 4326, remove = FALSE)
}

filter_outlier_postcodes <- function(postcode_summary, poa_boundaries) {
  poa_code_col <- grep("POA_CODE", names(poa_boundaries), value = TRUE, ignore.case = TRUE)[1]

  # Build distance-from-centre for each postcode in a single pipeline
  poa_distances <- poa_boundaries |>
    rename(postcode = !!sym(poa_code_col)) |>
    mutate(postcode = as.character(postcode)) |>
    filter(postcode %in% postcode_summary$postcode) |>
    st_centroid() |>
    mutate(
      coords = st_coordinates(geometry) |> as_tibble(),
      mean_lon = mean(coords$X),
      mean_lat = mean(coords$Y),
      mean_centre = st_sfc(st_point(c(first(mean_lon), first(mean_lat))), crs = 4326),
      dist_to_centre = as.numeric(st_distance(geometry, first(mean_centre)))
    ) |>
    st_drop_geometry() |>
    select(postcode, dist_to_centre) |>
    mutate(
      mean_dist = mean(dist_to_centre),
      sd_dist = sd(dist_to_centre),
      threshold = mean_dist + 3 * sd_dist,
      is_outlier = dist_to_centre > threshold
    )

  excluded <- poa_distances |> filter(is_outlier) |> pull(postcode)

  list(
    filtered_summary = postcode_summary |> filter(!postcode %in% excluded),
    excluded_postcodes = excluded,
    threshold_km = first(poa_distances$threshold) / 1000,
    mean_dist_km = first(poa_distances$mean_dist) / 1000,
    sd_dist_km = first(poa_distances$sd_dist) / 1000
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-mb_mapping.R")'
```

- [ ] **Step 5: Wire into _targets.R**

```r
  tar_target(mb_postcode_map, build_mb_postcode_map(mb_boundaries, mb_allocation, mb_population, postcode_summary)),
  tar_target(outlier_result, filter_outlier_postcodes(postcode_summary, poa_boundaries)),
  tar_target(filtered_postcodes, outlier_result$filtered_summary),
```

- [ ] **Step 6: Commit**

```bash
git add R/mb_mapping.R tests/testthat/test-mb_mapping.R _targets.R
git commit -m "feat: add MB-to-postcode mapping and outlier exclusion"
```

---

### Task 6: Spread Weights to Mesh Blocks

**Files:**
- Create: `R/weights.R`
- Create: `tests/testthat/test-weights.R`

- [ ] **Step 1: Write the failing tests**

```r
# ABOUTME: Tests for population-proportional weight spreading
# ABOUTME: Validates that individual/household counts distribute correctly across mesh blocks

library(testthat)
library(tibble)
library(dplyr)
library(sf)

test_that("spread_weights distributes individuals proportionally by MB population", {
  # Postcode 4000 has 10 individuals, 2 MBs with populations 100 and 300
  mb_map <- st_sf(
    mb_code = c("MB_A", "MB_B"),
    postcode = c("4000", "4000"),
    population = c(100, 300),
    centroid_lon = c(153.0, 153.01),
    centroid_lat = c(-27.5, -27.51),
    geometry = st_sfc(st_point(c(153.0, -27.5)), st_point(c(153.01, -27.51))),
    crs = 4326
  )
  pc_summary <- tibble(
    postcode = "4000",
    n_individuals = 10,
    n_households = 3,
    avg_household_size = 10 / 3
  )

  result <- spread_weights(mb_map, pc_summary)

  expect_equal(nrow(result), 2)
  expect_equal(result$spread_individuals[result$mb_code == "MB_A"], 10 * 100 / 400)
  expect_equal(result$spread_individuals[result$mb_code == "MB_B"], 10 * 300 / 400)
  expect_equal(sum(result$spread_individuals), 10)
  expect_equal(sum(result$spread_households), 3)
})

test_that("spread_weights handles postcode with single MB", {
  mb_map <- st_sf(
    mb_code = "MB_ONLY",
    postcode = "4001",
    population = 500,
    centroid_lon = 153.0,
    centroid_lat = -27.5,
    geometry = st_sfc(st_point(c(153.0, -27.5))),
    crs = 4326
  )
  pc_summary <- tibble(postcode = "4001", n_individuals = 7, n_households = 2, avg_household_size = 3.5)

  result <- spread_weights(mb_map, pc_summary)
  expect_equal(result$spread_individuals, 7)
  expect_equal(result$spread_households, 2)
})

test_that("spread_weights only includes postcodes in filtered summary", {
  mb_map <- st_sf(
    mb_code = c("MB_A", "MB_B"),
    postcode = c("4000", "4999"),
    population = c(100, 200),
    centroid_lon = c(153.0, 145.0),
    centroid_lat = c(-27.5, -16.9),
    geometry = st_sfc(st_point(c(153.0, -27.5)), st_point(c(145.0, -16.9))),
    crs = 4326
  )
  pc_summary <- tibble(postcode = "4000", n_individuals = 10, n_households = 3, avg_household_size = 10/3)

  result <- spread_weights(mb_map, pc_summary)
  expect_equal(nrow(result), 1)
  expect_equal(result$postcode, "4000")
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-weights.R")'
```

- [ ] **Step 3: Write implementation**

```r
# ABOUTME: Spreads postcode-level individual/household counts across mesh blocks
# ABOUTME: Uses mesh block population as a proportional distribution key

library(dplyr)
library(sf)

spread_weights <- function(mb_postcode_map, filtered_postcodes) {
  mb_postcode_map |>
    filter(postcode %in% filtered_postcodes$postcode) |>
    group_by(postcode) |>
    mutate(
      postcode_total_pop = sum(population),
      pop_share = population / postcode_total_pop
    ) |>
    ungroup() |>
    inner_join(
      filtered_postcodes |> select(postcode, n_individuals, n_households),
      by = "postcode"
    ) |>
    mutate(
      spread_individuals = n_individuals * pop_share,
      spread_households = n_households * pop_share
    ) |>
    select(mb_code, postcode, population, pop_share,
           centroid_lon, centroid_lat,
           spread_individuals, spread_households)
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-weights.R")'
```

- [ ] **Step 5: Wire into _targets.R**

```r
  tar_target(mb_weights, spread_weights(mb_postcode_map, filtered_postcodes)),
```

- [ ] **Step 6: Commit**

```bash
git add R/weights.R tests/testthat/test-weights.R _targets.R
git commit -m "feat: add population-proportional weight spreading to mesh blocks"
```

---

## Chunk 3: OSRM Routing

### Task 7: OSRM API Functions

**Files:**
- Create: `R/osrm.R`
- Create: `tests/testthat/test-osrm.R`

**Context:** The OSRM table API accepts coordinates and returns duration and distance matrices. We batch mesh block centroids into chunks of ~100 with the 3 destinations appended.

Endpoint: `GET /table/v1/driving/{coords}?sources={src_indices}&destinations={dest_indices}&annotations=duration,distance`

- [ ] **Step 1: Write the failing tests**

```r
# ABOUTME: Tests for OSRM API query building and response parsing
# ABOUTME: Tests marked 'osrm_live' require http://louisa_ts:5000 to be running

library(testthat)
library(tibble)

test_that("build_osrm_table_url constructs correct URL", {
  sources <- tibble(lon = c(153.0, 153.1), lat = c(-27.5, -27.6))
  destinations <- tibble(lon = c(153.03, 152.91), lat = c(-27.51, -27.56))

  url <- build_osrm_table_url(
    sources, destinations,
    base_url = "http://louisa_ts:5000"
  )

  expect_true(grepl("^http://louisa_ts:5000/table/v1/driving/", url))
  expect_true(grepl("sources=0;1", url))
  expect_true(grepl("destinations=2;3", url))
  expect_true(grepl("annotations=duration,distance", url))
  # Check coordinates are in lon,lat format
  expect_true(grepl("153,-27.5;153.1,-27.6;153.03,-27.51;152.91,-27.56", url))
})

test_that("parse_osrm_table_response extracts duration and distance matrices", {
  # Simulated OSRM response structure
  response <- list(
    code = "Ok",
    durations = matrix(c(100, 200, 300, 400), nrow = 2, ncol = 2),
    distances = matrix(c(1000, 2000, 3000, 4000), nrow = 2, ncol = 2)
  )
  mb_codes <- c("MB_A", "MB_B")
  loc_ids <- c("loc_1", "loc_2")

  result <- parse_osrm_table_response(response, mb_codes, loc_ids)

  expect_equal(nrow(result), 4)  # 2 MBs x 2 locations
  expect_true(all(c("mb_code", "location_id", "duration_sec", "distance_m") %in% names(result)))
  expect_equal(result$duration_sec[result$mb_code == "MB_A" & result$location_id == "loc_1"], 100)
  expect_equal(result$distance_m[result$mb_code == "MB_B" & result$location_id == "loc_2"], 4000)
})

test_that("chunk_indices creates correct batches", {
  chunks <- chunk_indices(250, chunk_size = 100)
  expect_equal(length(chunks), 3)
  expect_equal(chunks[[1]], 1:100)
  expect_equal(chunks[[2]], 101:200)
  expect_equal(chunks[[3]], 201:250)
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-osrm.R")'
```

- [ ] **Step 3: Write implementation**

```r
# ABOUTME: OSRM table API client for batch driving distance/duration queries
# ABOUTME: Chunks mesh block centroids into batches and queries against louisa_ts:5000

library(httr2)
library(dplyr)
library(tidyr)
library(purrr)
library(tibble)

build_osrm_table_url <- function(sources, destinations, base_url = "http://louisa_ts:5000") {
  # Combine all coordinates: sources first, then destinations
  all_coords <- c(
    paste(sources$lon, sources$lat, sep = ","),
    paste(destinations$lon, destinations$lat, sep = ",")
  )
  coords_str <- paste(all_coords, collapse = ";")

  n_src <- nrow(sources)
  n_dst <- nrow(destinations)
  src_indices <- paste(seq(0, n_src - 1), collapse = ";")
  dst_indices <- paste(seq(n_src, n_src + n_dst - 1), collapse = ";")

  paste0(
    base_url, "/table/v1/driving/", coords_str,
    "?sources=", src_indices,
    "&destinations=", dst_indices,
    "&annotations=duration,distance"
  )
}

parse_osrm_table_response <- function(response, mb_codes, location_ids) {
  # Convert duration matrix to long-format tibble via pivot
  response$durations |>
    do.call(rbind, args = _) |>
    as_tibble(.name_repair = ~location_ids) |>
    mutate(mb_code = mb_codes) |>
    pivot_longer(-mb_code, names_to = "location_id", values_to = "duration_sec") |>
    # Join distance matrix the same way
    inner_join(
      response$distances |>
        do.call(rbind, args = _) |>
        as_tibble(.name_repair = ~location_ids) |>
        mutate(mb_code = mb_codes) |>
        pivot_longer(-mb_code, names_to = "location_id", values_to = "distance_m"),
      by = c("mb_code", "location_id")
    )
}

chunk_indices <- function(n, chunk_size = 100) {
  starts <- seq(1, n, by = chunk_size)
  lapply(starts, function(s) s:min(s + chunk_size - 1, n))
}

route_all_mb_to_locations <- function(mb_weights, locations, osrm_url = "http://louisa_ts:5000", chunk_size = 100) {
  mb_data <- mb_weights |>
    sf::st_drop_geometry() |>
    select(mb_code, postcode, centroid_lon, centroid_lat, spread_individuals, spread_households)

  loc_destinations <- locations |>
    sf::st_coordinates() |>
    as_tibble() |>
    rename(lon = X, lat = Y)

  loc_ids <- locations$location_id

  message("Routing ", nrow(mb_data), " mesh blocks x ", nrow(loc_destinations), " locations")

  # Chunk, query OSRM, parse, and bind in a single pipeline
  chunk_indices(nrow(mb_data), chunk_size) |>
    map(function(idx) {
      chunk <- mb_data |> slice(idx)

      chunk |>
        select(lon = centroid_lon, lat = centroid_lat) |>
        build_osrm_table_url(loc_destinations, base_url = osrm_url) |>
        request() |>
        req_timeout(120) |>
        req_retry(max_tries = 3, backoff = ~ 2) |>
        req_perform() |>
        resp_body_json() |>
        (\(resp) {
          if (resp$code != "Ok") { warning("OSRM error: ", resp$code); return(NULL) }
          parse_osrm_table_response(resp, chunk$mb_code, loc_ids)
        })() |>
        left_join(
          chunk |> select(mb_code, postcode, spread_individuals, spread_households),
          by = "mb_code"
        )
    }, .progress = TRUE) |>
    bind_rows() |>
    mutate(
      distance_km = distance_m / 1000,
      duration_min = duration_sec / 60
    )
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-osrm.R")'
```

- [ ] **Step 5: Wire into _targets.R**

```r
  tar_target(mb_routes, route_all_mb_to_locations(mb_weights, locations)),
```

- [ ] **Step 6: Commit**

```bash
git add R/osrm.R tests/testthat/test-osrm.R _targets.R
git commit -m "feat: add OSRM table API client with batched routing"
```

---

## Chunk 4: Aggregation and Output

### Task 8: Aggregate Per Postcode x Location

**Files:**
- Create: `R/aggregate.R`
- Create: `tests/testthat/test-aggregate.R`

- [ ] **Step 1: Write the failing tests**

```r
# ABOUTME: Tests for aggregation of MB-level routes to postcode-level stats
# ABOUTME: Validates weighted means, min/max, and summary statistics

library(testthat)
library(tibble)
library(dplyr)

test_that("aggregate_postcode_location computes correct weighted stats", {
  routes <- tibble(
    mb_code = c("MB_A", "MB_B", "MB_A", "MB_B"),
    postcode = c("4000", "4000", "4000", "4000"),
    location_id = c("loc_1", "loc_1", "loc_2", "loc_2"),
    spread_individuals = c(6, 4, 6, 4),
    spread_households = c(2, 1, 2, 1),
    distance_km = c(10, 20, 30, 40),
    duration_min = c(15, 25, 35, 45),
    distance_m = c(10000, 20000, 30000, 40000),
    duration_sec = c(900, 1500, 2100, 2700)
  )

  result <- aggregate_postcode_location(routes)

  loc1 <- result |> filter(postcode == "4000", location_id == "loc_1")
  expect_equal(loc1$weighted_mean_distance_km, (6*10 + 4*20) / (6+4))  # 14
  expect_equal(loc1$weighted_mean_duration_min, (6*15 + 4*25) / (6+4))  # 19
  expect_equal(loc1$min_mb_distance_km, 10)
  expect_equal(loc1$max_mb_distance_km, 20)
  expect_equal(loc1$min_mb_duration_min, 15)
  expect_equal(loc1$max_mb_duration_min, 25)
})

test_that("summarise_locations computes overall weighted stats", {
  pc_loc <- tibble(
    postcode = c("4000", "4001", "4000", "4001"),
    location_id = c("loc_1", "loc_1", "loc_2", "loc_2"),
    n_individuals = c(10, 5, 10, 5),
    n_households = c(3, 2, 3, 2),
    weighted_mean_distance_km = c(10, 20, 30, 40),
    weighted_mean_duration_min = c(15, 25, 35, 45),
    min_mb_distance_km = c(8, 18, 28, 38),
    max_mb_distance_km = c(12, 22, 32, 42),
    min_mb_duration_min = c(13, 23, 33, 43),
    max_mb_duration_min = c(17, 27, 37, 47),
    avg_household_size = c(10/3, 5/2, 10/3, 5/2)
  )

  result <- summarise_locations(pc_loc)
  expect_equal(nrow(result), 2)  # 2 locations

  loc1 <- result |> filter(location_id == "loc_1")
  expected_mean <- (10*15 + 5*25) / (10+5)
  expect_equal(loc1$weighted_mean_duration_min, expected_mean)
})

test_that("build_full_matrix includes all postcode metadata", {
  pc_loc <- tibble(
    postcode = c("4000", "4001"),
    location_id = c("loc_1", "loc_1"),
    n_individuals = c(10, 5),
    n_households = c(3, 2),
    weighted_mean_distance_km = c(10, 20),
    weighted_mean_duration_min = c(15, 25),
    min_mb_distance_km = c(8, 18),
    max_mb_distance_km = c(12, 22),
    min_mb_duration_min = c(13, 23),
    max_mb_duration_min = c(17, 27),
    avg_household_size = c(10/3, 5/2)
  )
  filtered_pcs <- tibble(postcode = c("4000", "4001"), n_individuals = c(10, 5), n_households = c(3, 2), avg_household_size = c(10/3, 5/2))

  result <- build_full_matrix(pc_loc, filtered_pcs)
  expect_true("avg_household_size" %in% names(result))
  expect_equal(nrow(result), 2)
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-aggregate.R")'
```

- [ ] **Step 3: Write implementation**

```r
# ABOUTME: Aggregates mesh-block-level OSRM routes to postcode x location statistics
# ABOUTME: Computes weighted means, min/max, percentiles, and time-band breakdowns

library(dplyr)
library(tidyr)

aggregate_postcode_location <- function(mb_routes) {
  mb_routes |>
    group_by(postcode, location_id) |>
    summarise(
      n_individuals = sum(spread_individuals),
      n_households = sum(spread_households),
      weighted_mean_distance_km = weighted.mean(distance_km, spread_individuals),
      weighted_mean_duration_min = weighted.mean(duration_min, spread_individuals),
      min_mb_distance_km = min(distance_km),
      max_mb_distance_km = max(distance_km),
      min_mb_duration_min = min(duration_min),
      max_mb_duration_min = max(duration_min),
      .groups = "drop"
    )
}

summarise_locations <- function(postcode_location_stats) {
  # Expand postcode-level rows to individual-weighted rows for percentile calcs
  expanded <- postcode_location_stats |>
    mutate(weight = pmax(1, round(n_individuals))) |>
    uncount(weight, .remove = FALSE)

  # Calculate percentiles per location from expanded data
  percentiles <- expanded |>
    group_by(location_id) |>
    summarise(
      weighted_median_duration_min = median(weighted_mean_duration_min),
      p25_duration_min = quantile(weighted_mean_duration_min, 0.25, names = FALSE),
      p75_duration_min = quantile(weighted_mean_duration_min, 0.75, names = FALSE),
      .groups = "drop"
    )

  # Calculate weighted means and time-band percentages
  postcode_location_stats |>
    group_by(location_id) |>
    summarise(
      total_individuals = sum(n_individuals),
      total_households = sum(n_households),
      weighted_mean_distance_km = weighted.mean(weighted_mean_distance_km, n_individuals),
      weighted_mean_duration_min = weighted.mean(weighted_mean_duration_min, n_individuals),
      pct_within_15min = sum(n_individuals[weighted_mean_duration_min <= 15]) / sum(n_individuals) * 100,
      pct_within_30min = sum(n_individuals[weighted_mean_duration_min <= 30]) / sum(n_individuals) * 100,
      pct_within_45min = sum(n_individuals[weighted_mean_duration_min <= 45]) / sum(n_individuals) * 100,
      pct_within_60min = sum(n_individuals[weighted_mean_duration_min <= 60]) / sum(n_individuals) * 100,
      .groups = "drop"
    ) |>
    inner_join(percentiles, by = "location_id")
}

build_full_matrix <- function(postcode_location_stats, filtered_postcodes) {
  postcode_location_stats |>
    left_join(
      filtered_postcodes |> select(postcode, avg_household_size),
      by = "postcode"
    )
}

write_csv_output <- function(data, path) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  readr::write_csv(data, path)
  path
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_file("tests/testthat/test-aggregate.R")'
```

- [ ] **Step 5: Wire into _targets.R**

```r
  tar_target(postcode_location_stats, aggregate_postcode_location(mb_routes)),
  tar_target(location_summary, summarise_locations(postcode_location_stats)),
  tar_target(full_matrix, build_full_matrix(postcode_location_stats, filtered_postcodes)),
  tar_target(matrix_csv, write_csv_output(full_matrix, "output/full_matrix.csv"), format = "file"),
  tar_target(summary_csv, write_csv_output(location_summary, "output/summary_table.csv"), format = "file"),
```

- [ ] **Step 6: Commit**

```bash
git add R/aggregate.R tests/testthat/test-aggregate.R _targets.R
git commit -m "feat: add aggregation and summary statistics"
```

---

## Chunk 5: Visualization

### Task 9: Violin Plots

**Files:**
- Create: `R/visualize.R`
- Create: `tests/testthat/test-visualize.R`

- [ ] **Step 1: Write visualization tests**

Create `tests/testthat/test-visualize.R`:

```r
# ABOUTME: Tests for visualization output functions
# ABOUTME: Validates that plots and map produce output files without error

library(testthat)
library(tibble)
library(sf)

# Shared test fixtures
make_test_routes <- function() {
  tibble(
    mb_code = rep(c("MB_A", "MB_B"), each = 3),
    postcode = rep("4000", 6),
    location_id = rep(c("loc_1", "loc_2", "loc_3"), 2),
    spread_individuals = rep(c(6, 4), each = 3),
    spread_households = rep(c(2, 1), each = 3),
    distance_km = c(10, 20, 15, 12, 22, 17),
    duration_min = c(15, 25, 20, 18, 28, 22),
    distance_m = distance_km * 1000,
    duration_sec = duration_min * 60
  )
}

make_test_locations <- function() {
  st_as_sf(
    tibble(
      location_id = c("loc_1", "loc_2", "loc_3"),
      name = c("Annerley", "Riverhills", "Fortitude Valley"),
      address = c("628 Ipswich Rd", "9 Pallinup St", "33 Baxter St"),
      role = c("Candidate", "Candidate", "Current"),
      lon = c(153.034, 152.914, 153.036),
      lat = c(-27.51, -27.559, -27.456)
    ),
    coords = c("lon", "lat"), crs = 4326
  )
}

test_that("make_violin_plots produces a PNG file", {
  routes <- make_test_routes()
  locs <- make_test_locations()
  out <- withr::with_tempdir({
    dir.create("output")
    make_violin_plots(routes, locs)
  })
  expect_true(file.exists(out))
  expect_true(grepl("\\.png$", out))
})
```

- [ ] **Step 2: Write violin plot function**

```r
# ABOUTME: Visualization functions for travel analysis results
# ABOUTME: Produces violin plots (ggplot2), leaflet map, and gt summary table

library(ggplot2)
library(dplyr)
library(sf)
library(leaflet)
library(gt)
library(RColorBrewer)
library(htmlwidgets)

make_violin_plots <- function(mb_routes, locations) {
  plot_data <- mb_routes |>
    left_join(
      locations |> st_drop_geometry() |> select(location_id, name, role),
      by = "location_id"
    ) |>
    mutate(label = paste0(name, "\n(", role, ")") |> factor())

  p <- ggplot(plot_data, aes(x = label, y = duration_min, weight = spread_individuals)) +
    geom_violin(aes(fill = label), alpha = 0.7, scale = "width") +
    geom_boxplot(width = 0.15, outlier.shape = NA, alpha = 0.5) +
    scale_fill_brewer(palette = "Set2") +
    labs(
      title = "Travel Time Distribution to Each Location",
      subtitle = "Weighted by client population spread across mesh blocks",
      x = NULL,
      y = "Driving Time (minutes)"
    ) +
    theme_minimal(base_size = 14) +
    theme(legend.position = "none") +
    coord_cartesian(ylim = c(0, quantile(plot_data$duration_min, 0.98)))

  out_path <- "output/violin_plots.png"
  dir.create(dirname(out_path), recursive = TRUE, showWarnings = FALSE)
  ggsave(out_path, p, width = 10, height = 7, dpi = 150)
  out_path
}
```

- [ ] **Step 2: Wire into _targets.R**

```r
  tar_target(violin_plot, make_violin_plots(mb_routes, locations), format = "file"),
```

- [ ] **Step 3: Commit**

```bash
git add R/visualize.R tests/testthat/test-visualize.R _targets.R
git commit -m "feat: add violin plot visualization"
```

---

### Task 10: Leaflet Map

**Files:**
- Modify: `R/visualize.R`

- [ ] **Step 1: Add map function to visualize.R**

Append to `R/visualize.R`:

```r
make_map <- function(poa_boundaries, postcode_location_stats, locations, filtered_postcodes) {
  # Prepare POA polygons with stats for the nearest location
  poa_code_col <- grep("POA_CODE", names(poa_boundaries), value = TRUE, ignore.case = TRUE)[1]
  poa <- poa_boundaries |>
    rename(postcode = !!sym(poa_code_col)) |>
    mutate(postcode = as.character(postcode)) |>
    filter(postcode %in% filtered_postcodes$postcode)

  # Join location names for readable popups
  loc_names <- locations |>
    st_drop_geometry() |>
    select(location_id, name)

  # Build popup showing ALL 3 locations per postcode
  all_stats <- postcode_location_stats |>
    left_join(loc_names, by = "location_id")

  popup_df <- all_stats |>
    arrange(postcode, weighted_mean_duration_min) |>
    group_by(postcode) |>
    summarise(
      n_individuals = first(n_individuals),
      best_duration = min(weighted_mean_duration_min),
      popup_detail = paste0(
        name, ": ", round(weighted_mean_duration_min, 1), " min (",
        round(weighted_mean_distance_km, 1), " km)"
      ) |> paste(collapse = "<br/>"),
      .groups = "drop"
    ) |>
    mutate(popup = paste0(
      "<strong>Postcode: ", postcode, "</strong><br/>",
      "Individuals: ", round(n_individuals), "<br/><br/>",
      popup_detail
    ))

  poa_with_stats <- poa |>
    left_join(popup_df, by = "postcode")

  # Colour palette based on best travel time
  pal <- colorNumeric(
    palette = "YlOrRd",
    domain = poa_with_stats$best_duration,
    na.color = "#cccccc"
  )

  # Build location data for markers
  loc_data <- locations |>
    mutate(
      coords = st_coordinates(geometry) |> as_tibble(),
      lon = coords$X,
      lat = coords$Y,
      popup = paste0("<strong>", name, "</strong><br/>", address, "<br/>Role: ", role)
    ) |>
    st_drop_geometry()

  m <- leaflet() |>
    addTiles() |>
    addPolygons(
      data = poa_with_stats,
      fillColor = ~pal(best_duration),
      fillOpacity = 0.6,
      weight = 1,
      color = "#333",
      popup = ~popup
    ) |>
    addCircleMarkers(
      lng = loc_data$lon, lat = loc_data$lat,
      radius = 10,
      color = c("#e41a1c", "#377eb8", "#4daf4a"),
      fillOpacity = 1,
      popup = loc_data$popup
    ) |>
    addLegend(
      position = "bottomright",
      pal = pal,
      values = poa_with_stats$best_duration,
      title = "Travel Time (min)<br/>to nearest location"
    )

  out_path <- "output/map.html"
  dir.create(dirname(out_path), recursive = TRUE, showWarnings = FALSE)
  saveWidget(m, file = normalizePath(out_path, mustWork = FALSE), selfcontained = TRUE)
  out_path
}
```

- [ ] **Step 2: Wire into _targets.R**

```r
  tar_target(map_html, make_map(poa_boundaries, postcode_location_stats, locations, filtered_postcodes), format = "file"),
```

- [ ] **Step 3: Commit**

```bash
git add R/visualize.R _targets.R
git commit -m "feat: add leaflet map visualization"
```

---

### Task 11: GT Summary Table

**Files:**
- Modify: `R/visualize.R`

- [ ] **Step 1: Add GT table function to visualize.R**

Append to `R/visualize.R`:

```r
make_summary_table_gt <- function(location_summary, locations) {
  tbl_data <- location_summary |>
    left_join(
      locations |> st_drop_geometry() |> select(location_id, name, address, role),
      by = "location_id"
    ) |>
    select(
      Location = name,
      Address = address,
      Role = role,
      Individuals = total_individuals,
      Households = total_households,
      `Mean Distance (km)` = weighted_mean_distance_km,
      `Mean Time (min)` = weighted_mean_duration_min,
      `Median Time (min)` = weighted_median_duration_min,
      `P25 (min)` = p25_duration_min,
      `P75 (min)` = p75_duration_min,
      `≤15 min (%)` = pct_within_15min,
      `≤30 min (%)` = pct_within_30min,
      `≤45 min (%)` = pct_within_45min,
      `≤60 min (%)` = pct_within_60min
    )

  tbl <- tbl_data |>
    gt() |>
    tab_header(
      title = "Location Accessibility Comparison",
      subtitle = "Weighted by client population distributed across mesh blocks"
    ) |>
    fmt_number(columns = where(is.numeric), decimals = 1) |>
    fmt_number(columns = c("Individuals", "Households"), decimals = 0)

  out_path <- "output/summary_table.html"
  dir.create(dirname(out_path), recursive = TRUE, showWarnings = FALSE)
  gtsave(tbl, out_path)
  out_path
}
```

- [ ] **Step 2: Wire into _targets.R**

```r
  tar_target(summary_table_gt, make_summary_table_gt(location_summary, locations), format = "file"),
```

- [ ] **Step 3: Commit**

```bash
git add R/visualize.R _targets.R
git commit -m "feat: add GT summary table visualization"
```

---

### Task 12: Finalize _targets.R and Integration Test

**Files:**
- Modify: `_targets.R`

- [ ] **Step 1: Write the complete _targets.R**

```r
# ABOUTME: targets pipeline for Ali Brisbane travel distance analysis
# ABOUTME: Calculates OSRM driving distances from client postcodes to 3 candidate locations

library(targets)

tar_source()

list(
  # --- Data reading ---
  tar_target(raw_data, read_excel_data("data/brisbane_family.xlsx")),
  tar_target(postcode_summary, summarise_postcodes(raw_data)),

  # --- ABS spatial data ---
  tar_target(mb_boundaries, load_mb_boundaries("data/abs")),
  tar_target(poa_boundaries, load_poa_boundaries("data/abs")),
  tar_target(mb_allocation, load_mb_allocation("data/abs")),
  tar_target(mb_population, load_mb_population("data/abs")),

  # --- Mesh block mapping ---
  tar_target(mb_postcode_map, build_mb_postcode_map(mb_boundaries, mb_allocation, mb_population, postcode_summary)),
  tar_target(outlier_result, filter_outlier_postcodes(postcode_summary, poa_boundaries)),
  tar_target(filtered_postcodes, outlier_result$filtered_summary),

  # --- Weights ---
  tar_target(mb_weights, spread_weights(mb_postcode_map, filtered_postcodes)),

  # --- Locations ---
  tar_target(locations, get_target_locations()),

  # --- OSRM routing ---
  tar_target(mb_routes, route_all_mb_to_locations(mb_weights, locations)),

  # --- Aggregation ---
  tar_target(postcode_location_stats, aggregate_postcode_location(mb_routes)),
  tar_target(location_summary, summarise_locations(postcode_location_stats)),
  tar_target(full_matrix, build_full_matrix(postcode_location_stats, filtered_postcodes)),

  # --- CSV exports ---
  tar_target(matrix_csv, write_csv_output(full_matrix, "output/full_matrix.csv"), format = "file"),
  tar_target(summary_csv, write_csv_output(location_summary, "output/summary_table.csv"), format = "file"),

  # --- Visualization ---
  tar_target(violin_plot, make_violin_plots(mb_routes, locations), format = "file"),
  tar_target(map_html, make_map(poa_boundaries, postcode_location_stats, locations, filtered_postcodes), format = "file"),
  tar_target(summary_table_gt, make_summary_table_gt(location_summary, locations), format = "file")
)
```

- [ ] **Step 2: Validate pipeline DAG**

```bash
cd ../ali_brisbane && Rscript -e 'library(targets); tar_validate()'
```

Expected: No errors. May warn about missing ABS data files (expected until download step runs).

- [ ] **Step 3: Run all unit tests**

```bash
cd ../ali_brisbane && Rscript -e 'testthat::test_dir("tests/testthat")'
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add _targets.R
git commit -m "feat: finalize complete targets pipeline"
```

---

## Execution Notes

### Manual Steps Required

1. **ABS Data Downloads** (~300 MB total): The spatial data functions will attempt automatic download. If ABS URLs have changed, download manually:
   - MB boundaries (217 MB shapefile): https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/digital-boundary-files
   - POA boundaries (53 MB shapefile): same page
   - POA allocation file (17.7 MB XLSX): https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/allocation-files
   - MB population counts (14.5 MB XLSX): https://www.abs.gov.au/census/guide-census-data/mesh-block-counts/latest-release

2. **OSRM Server**: `http://louisa_ts:5000` must be running before Task 7 integration. Unit tests for URL building and response parsing work without the server.

3. **Location Coordinates**: Hardcoded approximate lat/lon. Verify and adjust if needed:
   - Annerley: -27.5100, 153.0340
   - Riverhills: -27.5590, 152.9140
   - Fortitude Valley: -27.4560, 153.0360

### Running the Pipeline

```bash
cd ../ali_brisbane && Rscript -e 'library(targets); tar_make()'
```

### Pipeline Dependency Graph

```
raw_data -> postcode_summary -> outlier_result -> filtered_postcodes -> mb_weights -> mb_routes
                                                                                        |
mb_boundaries ─┐                                                                        v
mb_allocation ─┤-> mb_postcode_map -> mb_weights                    postcode_location_stats
mb_population ─┘                                                      /        |          \
                                                            location_summary  full_matrix  (viz)
poa_boundaries -> outlier_result                               |          |
               -> map_html                               summary_csv  matrix_csv
locations -> mb_routes
          -> violin_plot
          -> summary_table_gt
```
