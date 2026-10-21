"""PALEOMAP PaleoAtlas plate positions and published raster age index."""
from __future__ import annotations

from bisect import bisect_left
from functools import lru_cache
from pathlib import Path
import re
import zipfile

import pygplates


MAX_AGE = 750


class PaleoModel:
    def __init__(self, directory: Path):
        directory = Path(directory)
        numeric_archive = directory.parent / "paleodem_2024.zip"
        using_2024 = numeric_archive.is_file()
        if using_2024:
            rotation_file = directory / "scotese2024.rot"
            polygon_file = directory / "scotese2024_polygons.gpml"
            if not rotation_file.is_file() or not polygon_file.is_file():
                raise FileNotFoundError(
                    "Для карт PALEOMAP 2024 нужна соответствующая модель движения плит. "
                    "Запустите fetch_paleodem_2024.py для установки scotese2024.rot "
                    "и scotese2024_polygons.gpml."
                )
            self.source_name = "PALEOMAP 2024 (v19o_r1d)"
        else:
            rotation_file = directory / "scotese.rot"
            polygon_file = directory / "scotese_polygons.gpml"
            self.source_name = "PALEOMAP PaleoAtlas 2016"
        self.rotations = pygplates.RotationModel(str(rotation_file))
        self.partitioner = pygplates.PlatePartitioner(
            pygplates.FeatureCollection(str(polygon_file)),
            self.rotations,
        )
        rasters = directory.parent / "paleoatlas_rasters"
        self.rasters = {int(path.stem.rsplit("_", 1)[-1]): path
                        for path in rasters.glob("*.jpg")}
        if using_2024:
            with zipfile.ZipFile(numeric_archive) as archive:
                self.ages = sorted({int(match[1])
                                    for name in archive.namelist()
                                    if name.lower().endswith(".nc")
                                    and (match := re.match(r"(\d+)", Path(name).name))})
        else:
            self.ages = sorted(self.rasters)
        if not self.ages or self.ages[0] != 0 or self.ages[-1] != MAX_AGE:
            raise FileNotFoundError(
                f"Набор карт {self.source_name} неполный: нужны снимки 0–750 млн лет."
            )

    def frames(self, age: int):
        """Published ages bracketing the requested 1 Ma position."""
        if not 0 <= age <= MAX_AGE:
            raise ValueError("Возраст вне покрытия PALEOMAP PaleoAtlas")
        index = bisect_left(self.ages, age)
        if index < len(self.ages) and self.ages[index] == age:
            return age, age, 0.0
        if index == 0:
            return self.ages[0], self.ages[0], 0.0
        if index == len(self.ages):
            return self.ages[-1], self.ages[-1], 0.0
        older = self.ages[index]
        younger = self.ages[index - 1]
        return younger, older, (age - younger) / (older - younger)

    @lru_cache(maxsize=8192)
    def plate_id(self, lon: float, lat: float) -> int:
        match = self.partitioner.partition_point((lat, lon))
        return match.get_feature().get_reconstruction_plate_id() if match else 0

    @lru_cache(maxsize=256)
    def rotation(self, age: int, plate_id: int):
        return self.rotations.get_rotation(age, plate_id)

    def point(self, lon: float, lat: float, age: int, plate_id: int | None = None):
        if age == 0:
            return lon, lat
        plate_id = self.plate_id(lon, lat) if plate_id is None else plate_id
        point = self.rotation(age, plate_id) * pygplates.PointOnSphere(lat, lon)
        out_lat, out_lon = point.to_lat_lon()
        return out_lon, out_lat

    def ring(self, coordinates, age: int, plate_id: int):
        if age == 0:
            return coordinates
        rotation = self.rotation(age, plate_id)
        return [(lon, lat) for lat, lon in (
            (rotation * pygplates.PointOnSphere(lat, lon)).to_lat_lon()
            for lon, lat in coordinates
        )]
