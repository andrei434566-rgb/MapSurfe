"""Published PaleoDEM grids converted to an illuminated, readable atlas palette.

The grid supplies the coast, shelf, bathymetry and elevation. The colors and
hillshade are presentation only; they do not create new geological features.
"""
from __future__ import annotations

from bisect import bisect_left
from functools import lru_cache
from pathlib import Path
import re
import zipfile

import cv2
import netCDF4
import numpy as np


# High-chroma PALEOMAP-inspired ocean/relief palette.
# Visualization only: DEM heights and derived coastlines remain unchanged.
SEA_STOPS = [
    (-5200, (1, 20, 64)), (-4500, (2, 37, 98)),
    (-3500, (3, 72, 151)), (-2600, (5, 107, 185)),
    (-1600, (11, 148, 217)), (-800, (32, 181, 230)),
    (-250, (78, 207, 242)), (-30, (119, 222, 247)),
    (0, (146, 235, 247)),
]
LAND_STOPS = [
    (0, (17, 87, 39)), (90, (25, 112, 40)),
    (260, (46, 131, 45)), (500, (81, 151, 49)),
    (800, (129, 161, 55)), (1150, (172, 163, 61)),
    (1600, (202, 155, 71)), (2200, (207, 134, 71)),
    (3100, (229, 181, 111)), (4300, (249, 226, 183)),
]

def _make_lut(stops, low, high):
    height = np.arange(low, high + 1, dtype=np.float32)
    result = np.empty((len(height), 3), dtype=np.uint8)
    for channel in range(3):
        result[:, channel] = np.interp(
            height, [v for v, _ in stops], [rgb[channel] for _, rgb in stops]
        ).astype(np.uint8)
    return result


SEA_LUT = _make_lut(SEA_STOPS, -5200, 0)
LAND_LUT = _make_lut(LAND_STOPS, 0, 4300)


class PaleoVisualData:
    def __init__(self, directory: Path, old_rasters: dict[int, Path]):
        high_resolution = directory / "paleodem_01deg.zip"
        self.path = high_resolution if high_resolution.exists() else directory / "paleodem_02deg.zip"
        self.resolution = "0,1°" if high_resolution.exists() else "0,2°"
        self.color_cache = directory / ("paleodem_color_01deg_vivid_v1" if high_resolution.exists()
                                        else "paleodem_color_vivid_v1")
        if not self.path.exists():
            raise FileNotFoundError(f"Нет набора PaleoDEM 2018: {self.path}")
        with zipfile.ZipFile(self.path) as archive:
            self.members = {}
            for name in archive.namelist():
                if name.startswith("__MACOSX") or not name.endswith(".nc"):
                    continue
                found = re.search(r"_([0-9.]+)Ma\.nc$", name)
                if found:
                    self.members[float(found.group(1))] = name
        self.ages = sorted(self.members)
        if self.ages[0] != 0 or self.ages[-1] != 540:
            raise ValueError("Неполный архив PaleoDEM: нужны карты 0–540 млн лет")
        self.old_rasters = old_rasters
        self.old_ages = sorted(old_rasters)

    def frames(self, age: float):
        if 540 < age < 600:
            return "bridge", 540.0, 600.0, (age - 540) / 60.0
        if age <= 540:
            ages = self.ages
            mode = "dem"
        else:
            ages = self.old_ages
            mode = "atlas"
        index = bisect_left(ages, age)
        if index >= len(ages):
            return mode, ages[-1], ages[-1], 0.0
        if ages[index] == age or index == 0:
            return mode, ages[index], ages[index], 0.0
        younger, older = ages[index - 1], ages[index]
        return mode, younger, older, (age - younger) / (older - younger)

    @lru_cache(maxsize=10)
    def image(self, mode: str, age: float):
        if mode == "bridge":
            return self.image("dem", 540.0) if age <= 540 else self.image("atlas", 600.0)
        if mode == "dem":
            cached = self.color_cache / f"{age:g}.jpg"
            if cached.exists():
                payload = np.fromfile(cached, dtype=np.uint8)
                decoded = cv2.imdecode(payload, cv2.IMREAD_COLOR)
                if decoded is not None:
                    return np.ascontiguousarray(cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB))
            return self._dem_image(age)
        return self._old_image(int(age))

    def _dem_image(self, age: float):
        with zipfile.ZipFile(self.path) as archive:
            payload = archive.read(self.members[age])
        with netCDF4.Dataset("paleodem", memory=payload) as nc:
            # OpenGL treats the first uploaded row as the texture bottom. Keep
            # row zero at the southern edge regardless of the source grid's
            # latitude ordering. PaleoDEM's current files run north-to-south.
            latitudes = np.asarray(nc.variables["latitude"][:])
            elevation = np.asarray(nc.variables["z"][:, :-1], dtype=np.float32)
            if latitudes[0] > latitudes[-1]:
                elevation = np.flipud(elevation)
        elevation = np.nan_to_num(elevation, nan=-4920.0)
        depth_index = np.clip(np.rint(elevation), -5200, 0).astype(np.int32) + 5200
        land_index = np.clip(np.rint(elevation), 0, 4300).astype(np.int32)
        colors = np.where(
            (elevation < 0)[..., None], SEA_LUT[depth_index], LAND_LUT[land_index]
        ).astype(np.float32)

        # A directional hillshade uses the actual elevation gradients. The
        # same, subtle texture at all dates prevents animation shimmer.
        dx = cv2.Sobel(elevation, cv2.CV_32F, 1, 0, ksize=3) / 8.0
        dy = cv2.Sobel(elevation, cv2.CV_32F, 0, 1, ksize=3) / 8.0
        shade = np.clip(1.03 + (dy - dx) * 0.0022, 0.72, 1.23)
        shade *= np.where(elevation < 0, 0.84, 1.0)
        # The published PaleoAtlas image for the same date contributes only
        # local illumination detail. Its older land/sea colors never control
        # the classification supplied by the newer numerical elevation grid.
        detailed_age = min(self.old_ages, key=lambda year: abs(year-age))
        old = cv2.imdecode(np.fromfile(self.old_rasters[detailed_age], dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if old is not None:
            detail = cv2.resize(old, (elevation.shape[1], elevation.shape[0]),
                                interpolation=cv2.INTER_CUBIC).astype(np.float32)
            detail = np.flipud(detail)
            high_frequency = detail - cv2.GaussianBlur(detail, (0, 0), 5.5)
            shade *= 1.0 + np.clip(high_frequency, -8, 25) * 0.006
        rng = np.random.default_rng(803)
        grain = rng.standard_normal(elevation.shape, dtype=np.float32)
        grain = cv2.GaussianBlur(grain, (0, 0), 1.15)
        shade *= np.clip(1.0 + grain * 0.065, 0.95, 1.05)
        return np.ascontiguousarray(np.clip(colors * shade[..., None], 0, 255).astype(np.uint8))

    def _old_image(self, age: int):
        source = cv2.imdecode(np.fromfile(self.old_rasters[age], dtype=np.uint8), cv2.IMREAD_COLOR)
        if source is None:
            raise OSError(f"Не удалось прочитать карту {age} млн лет")
        rgb = cv2.cvtColor(source, cv2.COLOR_BGR2RGB)
        hsv = cv2.cvtColor(source, cv2.COLOR_BGR2HSV)
        # Older-than-540-Ma snapshots have no 2018 height grid. Recolor the
        # source by its water/land hues without claiming a newer reconstruction.
        sea = (hsv[..., 0] >= 83) & (hsv[..., 0] <= 130) & (hsv[..., 1] > 54)
        brightness = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        depth = np.clip((brightness * 5900 - 5200).astype(np.int32), -5200, 0)
        heights = np.clip((brightness * 2900).astype(np.int32), 0, 4300)
        recolored = np.where(sea[..., None], SEA_LUT[depth + 5200], LAND_LUT[heights])
        mixed = cv2.addWeighted(recolored, 0.83, rgb, 0.17, 0)
        return np.ascontiguousarray(np.flipud(mixed))
