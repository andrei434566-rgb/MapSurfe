"""Prepare the GeoNames city index used by source builds of MapSurfe."""
from pathlib import Path
import urllib.request

from city_catalog import CityCatalog


def main():
    directory = Path(__file__).resolve().parent
    archive = directory / "cities500.zip"
    database = directory / "cities500.sqlite"
    if not database.is_file() and not archive.is_file():
        temporary = archive.with_suffix(".zip.part")
        request = urllib.request.Request(
            "https://download.geonames.org/export/dump/cities500.zip",
            headers={"User-Agent": "MapSurfe-source-setup/1.1"},
        )
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        temporary.replace(archive)
    catalog = CityCatalog(directory)
    print(f"GeoNames index ready: {catalog.count:,} places", flush=True)
    catalog.connection.close()


if __name__ == "__main__":
    main()
