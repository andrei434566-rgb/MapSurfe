"""Install the pinned, openly licensed PALEOMAP 2024 numeric elevation archive."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile


RECORD = "https://zenodo.org/api/records/10659112"
FILENAME = "5a. PaleoDEM (nc, 3601x1801).zip"
CHECKSUM = "a7285e0e6a7d1e93837ed89243bbfa6e"
MODEL_FILENAME = "3a. PALEOMAP Global Plate Model for Paleogeographic Reconstructions v.19o_r1d.zip"
MODEL_CHECKSUM = "7f4ac618e8320e18e572b352585097f9"
MODEL_ROTATION = "Scotese_Plate_Model_forPgeog_v19o_r1d_v240506a.rot"
MODEL_POLYGONS = "Scotese_Plate_Polygons__forPgeog_v19o_v240506.gpml"


def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_archive(entry: dict, target: Path, checksum: str):
    if entry["checksum"] != "md5:" + checksum:
        raise ValueError("The upstream archive differs from the pinned release.")
    if target.is_file() and file_md5(target) == checksum:
        print(f"{target.name} is already installed; checksum verified.", flush=True)
        return
    partial = target.with_suffix(".zip.part")
    received = 0
    next_report = 0
    with urllib.request.urlopen(entry["links"]["self"], timeout=90) as response:
        with partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                received += len(chunk)
                if received >= next_report:
                    print(f"{target.name}: downloaded {received / 1e6:.1f}/{entry['size'] / 1e6:.1f} MB", flush=True)
                    next_report += 16 * 1024 * 1024
    if received != entry["size"] or file_md5(partial) != checksum:
        raise ValueError("Incomplete download or archive checksum mismatch.")
    partial.replace(target)


def install_plate_model(archive_path: Path, directory: Path) -> dict:
    """Select the paleogeographic pair from the verified archive; retain 2016 files."""
    selected = {}
    with zipfile.ZipFile(archive_path) as archive:
        for source_name, target_name in (
            (MODEL_ROTATION, "scotese2024.rot"),
            (MODEL_POLYGONS, "scotese2024_polygons.gpml"),
        ):
            members = [item for item in archive.infolist()
                       if not item.is_dir() and Path(item.filename).name == source_name]
            if len(members) != 1:
                raise ValueError(f"Expected exactly one plate model file: {source_name}")
            payload = archive.read(members[0])
            target = directory / target_name
            partial = target.with_suffix(target.suffix + ".part")
            partial.write_bytes(payload)
            partial.replace(target)
            selected[target_name] = {
                "archive_member": members[0].filename,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
    return selected


def main():
    directory = Path(__file__).resolve().parent
    model_directory = directory / "model"
    model_directory.mkdir(exist_ok=True)
    with urllib.request.urlopen(RECORD, timeout=60) as response:
        record = json.load(response)
    entries = {item["key"]: item for item in record["files"]}
    entry = entries[FILENAME]
    model_entry = entries[MODEL_FILENAME]
    download_archive(entry, directory / "paleodem_2024.zip", CHECKSUM)
    # Model setup is independent of the DEM cache: an existing DEM still needs
    # its matching rotations and static polygons before city markers can align.
    model_archive = model_directory / "paleomap2024_model.zip"
    download_archive(model_entry, model_archive, MODEL_CHECKSUM)
    model_files = install_plate_model(model_archive, model_directory)
    provenance = {
        "title": record["metadata"]["title"],
        "authors": record["metadata"]["creators"],
        "doi": "10.5281/zenodo.10659112",
        "paper_doi": "10.1144/SP544-2024-28",
        "version": record["metadata"].get("version"),
        "published": record["metadata"]["publication_date"],
        "license": record["metadata"]["license"],
        "file": FILENAME,
        "md5": CHECKSUM,
        "download": entry["links"]["self"],
        "changes": "Numeric elevations rendered with the MapSurfe turquoise/green palette and relief shading.",
        "plate_model": {
            "file": MODEL_FILENAME,
            "md5": MODEL_CHECKSUM,
            "download": model_entry["links"]["self"],
            "version": "v19o_r1d_v240506a",
            "purpose": "PALEOMAP paleogeographic reconstructions, matched to the 2024 elevation maps.",
            "files": model_files,
            "changes": "Original rotation and static polygon files selected and renamed for MapSurfe; coordinates unchanged.",
        },
    }
    (model_directory / "paleodem2024-source.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Installed PALEOMAP 2024 elevations and matching paleogeographic plate model; checksums verified.")


if __name__ == "__main__":
    main()
