#!/usr/bin/env python3
"""Fetch the pinned EPA distribution of the Clemson USGS 3DEP terrain tile.

Uses only Python's standard library. Existing data are verified and preserved;
checksum mismatches require explicit investigation rather than replacement.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request
import zipfile


SOURCE_URL = (
    "https://gaftp.epa.gov/Air/aqmg/3dep/08-2024/1_arcsecond/"
    "USGS_1_n35w083.zip"
)
ARCHIVE_NAME = "USGS_1_n35w083.zip"
TILE_NAME = "USGS_1_n35w083.tif"
PROVENANCE_NAME = "terrain_provenance.json"
EXPECTED = {
    ARCHIVE_NAME: (
        42537184,
        "6ea73ee637ef2c569726778627aa2a288467b84a716a0eda9f79d2e2a1939813",
    ),
    TILE_NAME: (
        52215789,
        "7e62151b544b0253d3446400e3a1fbcef8d2cfe7d7093ff1f6399ab73501e829",
    ),
}
CHUNK_SIZE = 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, name: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Expected a regular file; preserving {path}")
    size, expected_hash = EXPECTED[name]
    if path.stat().st_size != size or sha256(path) != expected_hash:
        raise RuntimeError(
            f"Checksum/size mismatch; preserving {path}. "
            "Investigate the existing file before removing or replacing it."
        )


def publish_without_overwrite(temporary: Path, destination: Path) -> None:
    """Publish a complete file atomically and preserve any concurrent writer."""
    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise RuntimeError(
            f"Destination appeared during preparation; preserving {destination}"
        ) from exc


def download(archive: Path) -> dict:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{ARCHIVE_NAME}.", suffix=".part", dir=archive.parent
    )
    temporary = Path(temporary_name)
    try:
        request = urllib.request.Request(
            SOURCE_URL, headers={"User-Agent": "clemson-amp-terrain/1.0"}
        )
        # urllib's default HTTPS context verifies certificates and host names.
        with os.fdopen(descriptor, "wb") as output:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200 or not response.url.startswith("https://"):
                    raise RuntimeError("Terrain download did not return HTTPS 200")
                metadata = {
                    "http_status": response.status,
                    "http_last_modified": response.headers.get("Last-Modified"),
                    "resolved_url": response.url,
                }
                size = 0
                for chunk in iter(lambda: response.read(CHUNK_SIZE), b""):
                    size += len(chunk)
                    if size > EXPECTED[ARCHIVE_NAME][0]:
                        raise RuntimeError("Terrain archive exceeds its pinned size")
                    output.write(chunk)
        verify(temporary, ARCHIVE_NAME)
        publish_without_overwrite(temporary, archive)
        return metadata
    finally:
        temporary.unlink(missing_ok=True)


def verify_archive_and_extract(archive: Path, tile: Path) -> None:
    verify(archive, ARCHIVE_NAME)
    with zipfile.ZipFile(archive) as bundle:
        # CRC-check every member but extract only the exact pinned TIFF name.
        bad_member = bundle.testzip()
        if bad_member is not None:
            raise RuntimeError(f"ZIP CRC validation failed for {bad_member}")
        if bundle.namelist().count(TILE_NAME) != 1:
            raise RuntimeError("Expected exactly one named Clemson TIFF in archive")
        if bundle.getinfo(TILE_NAME).file_size != EXPECTED[TILE_NAME][0]:
            raise RuntimeError("Archive TIFF size differs from pinned size")
        if tile.exists() or tile.is_symlink():
            verify(tile, TILE_NAME)
            return
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{TILE_NAME}.", suffix=".part", dir=tile.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output, bundle.open(TILE_NAME) as source:
                for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
                    output.write(chunk)
            verify(temporary, TILE_NAME)
            publish_without_overwrite(temporary, tile)
        finally:
            temporary.unlink(missing_ok=True)


def save_provenance(directory: Path, http_metadata: dict, archive_checked: bool) -> None:
    path = directory / PROVENANCE_NAME
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Expected a regular provenance file; preserving {path}")
        existing = json.loads(path.read_text())
        records = existing.get("files", [])
        tile_record = next((r for r in records if r.get("filename") == TILE_NAME), {})
        if (
            existing.get("source_url") != SOURCE_URL
            or tile_record.get("sha256") != EXPECTED[TILE_NAME][1]
        ):
            raise RuntimeError(f"Provenance does not match pinned tile; preserving {path}")
        return
    provenance = {
        "source_name": "USGS 3DEP 1 arcsecond DEM, EPA static 08-2024 distribution",
        "source_url": SOURCE_URL,
        "originator": "U.S. Geological Survey",
        "distributor": "U.S. Environmental Protection Agency",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "transport": "HTTPS with standard urllib TLS verification enabled",
        "validation": {
            "tiff_sha256_matches_pin": True,
            "zip_sha256_and_all_member_crcs_checked": archive_checked,
        },
        "files": [
            {"filename": name, "size_bytes": size, "sha256": digest}
            for name, (size, digest) in EXPECTED.items()
            if (directory / name).is_file()
        ],
        "raster": {
            "horizontal_datum": "NAD83",
            "epsg": 4269,
            "resolution": "1 arcsecond, approximately 30 metres",
            "pixel_type": "Float32",
            "compression": "Uncompressed",
            "size_pixels": [3612, 3612],
        },
        "distribution_caveat": (
            "08-2024 labels the static EPA collection, not the original survey date. "
            "Original acquisition date and explicit vertical datum are unverified."
        ),
        **http_metadata,
    }
    # Exclusive creation preserves any user or concurrent provenance file.
    with path.open("x") as output:
        output.write(json.dumps(provenance, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "terrain",
        help="terrain cache directory (default: clemson_amp/data/terrain)",
    )
    parser.add_argument("--offline", action="store_true", help="only validate cached data")
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    archive, tile = directory / ARCHIVE_NAME, directory / TILE_NAME
    if tile.exists() or tile.is_symlink():
        verify(tile, TILE_NAME)
    http_metadata = {}
    if not archive.exists() and not archive.is_symlink() and not tile.exists():
        if args.offline:
            raise RuntimeError("No cached terrain TIFF or ZIP; offline mode cannot fetch it")
        print(f"Downloading {SOURCE_URL}", flush=True)
        http_metadata = download(archive)
    archive_checked = archive.exists() or archive.is_symlink()
    if archive_checked:
        verify_archive_and_extract(archive, tile)
    verify(tile, TILE_NAME)
    save_provenance(directory, http_metadata, archive_checked)
    print(f"Verified terrain: {tile}")
    print("Pinned SHA256 matches; " + ("ZIP CRC checks passed." if archive_checked else "TIFF cache reused."))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Terrain preparation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
