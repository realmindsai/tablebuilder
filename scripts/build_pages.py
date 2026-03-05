# ABOUTME: Build script for the GitHub Pages dictionary explorer.
# ABOUTME: Generates static assets from the SQLite dictionary database.

import json
import shutil
import sqlite3
from pathlib import Path

import click


REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs" / "explorer"
DATA_DIR = DOCS_DIR / "data"
VENDOR_DIR = DOCS_DIR / "vendor"
ASSETS_DIR = DOCS_DIR / "assets"
DB_SOURCE = Path.home() / ".tablebuilder" / "dictionary.db"
LOGO_SOURCE = Path.home() / ".claude" / "skills" / "rmai-brand-guidelines" / "assets" / "final_logo.svg"


@click.command()
@click.option("--db", default=str(DB_SOURCE), help="Path to dictionary.db")
def build(db):
    """Build the GitHub Pages explorer from the dictionary database."""
    db_path = Path(db)
    if not db_path.exists():
        click.echo(f"Error: database not found at {db_path}", err=True)
        raise SystemExit(1)

    # Create directory structure
    for d in [DATA_DIR, VENDOR_DIR, ASSETS_DIR, DOCS_DIR / "css", DOCS_DIR / "js"]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy database
    click.echo(f"Copying dictionary.db ({db_path.stat().st_size // 1024 // 1024}MB)...")
    shutil.copy2(db_path, DATA_DIR / "dictionary.db")

    # Generate Fuse.js index
    click.echo("Generating variables index for fuzzy search...")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT dataset_name, group_path, code, label, "
        "substr(categories_text, 1, 200) as categories_preview "
        "FROM variables_fts"
    ).fetchall()
    index = [dict(r) for r in rows]
    conn.close()

    index_path = DATA_DIR / "variables_index.json"
    index_path.write_text(json.dumps(index, separators=(",", ":")))
    index_size = index_path.stat().st_size / 1024 / 1024
    click.echo(f"  {len(index)} variables, {index_size:.1f}MB")

    # Generate datasets list (small, for browse view)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    datasets = conn.execute(
        "SELECT name, geographies_json, summary FROM datasets ORDER BY name"
    ).fetchall()
    ds_list = []
    for ds in datasets:
        ds_list.append({
            "name": ds["name"],
            "geographies": json.loads(ds["geographies_json"]),
            "summary": ds["summary"],
        })
    conn.close()
    (DATA_DIR / "datasets.json").write_text(json.dumps(ds_list, separators=(",", ":")))
    click.echo(f"  {len(ds_list)} datasets")

    # Copy logo
    if LOGO_SOURCE.exists():
        shutil.copy2(LOGO_SOURCE, ASSETS_DIR / "rmai_logo.svg")
        click.echo("Copied RMAI logo")
    else:
        click.echo(f"Warning: logo not found at {LOGO_SOURCE}", err=True)

    # Download vendor dependencies
    import urllib.request

    vendors = {
        "sql-wasm.js": "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.11.0/sql-wasm.js",
        "sql-wasm.wasm": "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.11.0/sql-wasm.wasm",
        "fuse.min.js": "https://cdnjs.cloudflare.com/ajax/libs/fuse.js/7.0.0/fuse.min.js",
    }

    for filename, url in vendors.items():
        dest = VENDOR_DIR / filename
        if not dest.exists():
            click.echo(f"Downloading {filename}...")
            urllib.request.urlretrieve(url, dest)
        else:
            click.echo(f"  {filename} already exists, skipping")

    click.echo(f"Done! Static site ready at {DOCS_DIR}")


if __name__ == "__main__":
    build()
