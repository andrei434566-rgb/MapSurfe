"""Published PaleoDEM grids converted to an illuminated, readable atlas palette.

The grid supplies the coast, shelf, bathymetry and elevation. The colors and
hillshade are presentation only; they do not create new geological features.
"""
from __future__ import annotations

from bisect import bisect_left
from functools import lru_cache
from pathlib import Path
import re
from threading import Lock
import zipfile

import cv2
import netCDF4
import numpy as np


SEA_STOPS = [
    (-5200, (14, 44, 75)), (-4500, (18, 62, 94)),
    (-3500, (23, 86, 120)), (-2600, (29, 115, 145)),
    (-1600, (40, 145, 167)), (-800, (60, 172, 187)),
    (-250, (91, 195, 200)), (-30, (133, 214, 210)),
    (0, (165, 224, 214)),
]
LAND_STOPS = [
    (0, (42, 106, 72)), (90, (49, 124, 77)),
    (260, (70, 143, 83)), (500, (101, 160, 93)),
    (800, (138, 174, 107)), (1150, (170, 183, 124)),
    (1600, (191, 183, 136)), (2200, (189, 164, 122)),
    (3100, (174, 150, 132)), (4300, (231, 227, 215)),
]


def relief_shade(dx, dy, sea):
    """Matte two-direction relief lighting, also used by the GPU shader."""
    nx, ny = -dx * 0.0055, -dy * 0.0055
    length = np.sqrt(nx * nx + ny * ny + 1.0)
    key = np.maximum((nx * -0.55 + ny * 0.65 + 0.95) / (length * np.sqrt(1.6275)), 0.0)
    fill = np.maximum((nx * 0.65 + ny * 0.15 + 1.0) / (length * np.sqrt(1.445)), 0.0)
    shade = 0.715 + 0.36 * key + 0.05 * fill
    return np.where(sea, 1.0 + (shade - 1.0) * 0.45, shade)


def relief_legend():
    """Derive height swatches from the same palette as the map."""
    entries = (("−5000 м", -5000), ("−2500", -2500), ("−250", -250),
               ("0 м", 0), ("+800", 800), ("+3000", 3000))
    for label, height in entries:
        stops = SEA_STOPS if height < 0 else LAND_STOPS
        rgb = [round(float(np.interp(height, [v for v, _ in stops],
                                    [color[channel] for _, color in stops])))
               for channel in range(3)]
        yield label, "#" + "".join(f"{channel:02x}" for channel in rgb)


def _make_lut(stops, low, high):
    height = np.arange(low, high + 1, dtype=np.float32)
    # Retain fractional colors until after hillshade. Rounding twice creates
    # visible bands across the very gentle slopes of Precambrian grids.
    result = np.empty((len(height), 3), dtype=np.float32)
    for channel in range(3):
        result[:, channel] = np.interp(
            height, [v for v, _ in stops], [rgb[channel] for _, rgb in stops]
        )
    return result


SEA_LUT = _make_lut(SEA_STOPS, -5200, 0)
LAND_LUT = _make_lut(LAND_STOPS, 0, 4300)
_NETCDF_LOCK = Lock()


class PaleoVisualData:
    def __init__(self, directory: Path, old_rasters: dict[int, Path]):
        latest = directory / "paleodem_2024.zip"
        high_resolution = directory / "paleodem_01deg.zip"
        if latest.exists():
            self.path = latest
            self.resolution = "0,1°"
            self.source_name = "PALEOMAP PaleoDEM 2024"
            self.color_cache = directory / "paleodem_color_2024_v4_atlas_lossless"
        else:
            self.path = (high_resolution if high_resolution.exists()
                         else directory / "paleodem_02deg.zip")
            self.resolution = "0,1°" if high_resolution.exists() else "0,2°"
            self.source_name = "PaleoDEM 2018"
            self.color_cache = directory / ("paleodem_color_01deg_v6_atlas_lossless" if high_resolution.exists()
                                            else "paleodem_color_02deg_v6_atlas_lossless")
        if not self.path.exists():
            raise FileNotFoundError(f"Нет набора PaleoDEM 2018: {self.path}")
        with zipfile.ZipFile(self.path) as archive:
            self.members = {}
            for name in archive.namelist():
                if name.startswith("__MACOSX") or not name.endswith(".nc"):
                    continue
                found = (re.match(r"([0-9]+)_.*\.nc$", Path(name).name)
                         if latest.exists() else re.search(r"_([0-9.]+)Ma\.nc$", name))
                if found:
                    self.members[float(found.group(1))] = name
        self.ages = sorted(self.members)
        expected = set(range(0, 541, 5))
        if latest.exists():
            expected.update((600, 630, 690, 750))
        missing = sorted(expected.difference(self.members))
        if missing:
            raise ValueError(f"Неполный архив PaleoDEM: отсутствуют карты {missing}")
        self.dem_max_age = self.ages[-1]
        self.has_precambrian_dem = self.dem_max_age >= 750
        if self.has_precambrian_dem:
            self.source_description = (
                "Scotese et al., PALEOMAP PaleoDEM 2024, CC BY 4.0. "
                "Числовые высоты и глубины, сетка 3601 × 1801 с шагом 0,1°. "
                "0–540 млн лет: опубликованные карты через 5 млн лет; "
                "докембрий: опорные реконструкции 600, 630, 690 и 750 млн лет. "
                "Между опорными датами вычисляется единая поверхность высот, "
                "затем определяется берег и применяется палитра. Изображения не "
                "накладываются. Промежуточные карты обозначены как расчётные. "
                "В докембрии исходная геологическая детализация и достоверность "
                "ниже: шаг сетки не определяет точность каждого берега или горы. "
                "DOI: 10.5281/zenodo.10659112. Палитра и светотень MapSurfe."
            )
        else:
            self.source_description = (
                f"0–540 млн лет: числовые сетки PaleoDEM 2018 с шагом {self.resolution}. "
                "Глубже в прошлом используются иллюстрированные карты PALEOMAP 2016. "
                "Для числового рельефа до 750 млн лет установите PALEOMAP 2024 "
                "командой python fetch_paleodem_2024.py. "
                "В числовом диапазоне промежуточные высоты интерполируются до окрашивания. "
                "Для старых иллюстраций показана ближайшая опубликованная карта."
            )
        self.old_rasters = old_rasters
        self.old_ages = sorted(old_rasters)

    def frames(self, age: float):
        """Bracket numeric heights, retaining discrete illustrated fallbacks."""
        if age <= self.dem_max_age:
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
        if mode == "dem":
            return mode, younger, older, (age - younger) / (older - younger)
        nearest = younger if age - younger <= older - age else older
        return mode, nearest, nearest, 0.0

    @lru_cache(maxsize=2)
    def elevation(self, age: float):
        with zipfile.ZipFile(self.path) as archive:
            payload = archive.read(self.members[age])
        return self._read_elevation(payload)

    @staticmethod
    def _slopes(elevation, age):
        # Smooth only lighting in the coarsely quantized ancient source. The
        # elevation channel and its coastline remain unchanged.
        lighting = (cv2.GaussianBlur(elevation, (0, 0), 0.95)
                    if age > 540 else elevation)
        # Longitude is periodic; neither the date line nor a pole is a cliff.
        padded = np.pad(lighting, ((1, 1), (0, 0)), mode="edge")
        padded = np.pad(padded, ((0, 0), (1, 1)), mode="wrap")
        dx = cv2.Sobel(padded, cv2.CV_32F, 1, 0, ksize=3)[1:-1, 1:-1] / 8.0
        dy = cv2.Sobel(padded, cv2.CV_32F, 0, 1, ksize=3)[1:-1, 1:-1] / 8.0
        return dx, dy

    @lru_cache(maxsize=3)
    def texture(self, mode: str, age: float):
        """Height and its lighting gradients, or an illustrated RGB fallback.

        The GPU mixes numeric surfaces before the sea/land decision. Half
        floats keep three channels no larger than two float32 height grids.
        """
        if mode != "dem":
            return self.image(mode, age)
        height = self.elevation(age)
        dx, dy = self._slopes(height, age)
        return np.ascontiguousarray(np.stack((height, dx, dy), axis=-1), dtype=np.float16)

    @staticmethod
    def palette_texture():
        colors = np.empty((2, 1024, 3), dtype=np.float32)
        for row, stops, low, high in ((0, SEA_STOPS, -5200, 0),
                                       (1, LAND_STOPS, 0, 4300)):
            levels = np.linspace(low, high, colors.shape[1])
            for channel in range(3):
                colors[row, :, channel] = np.interp(
                    levels, [v for v, _ in stops], [rgb[channel] for _, rgb in stops]
                ) / 255.0
        return colors

    @lru_cache(maxsize=10)
    def image(self, mode: str, age: float):
        if mode == "dem":
            # Lossless RGB preserves narrow coastlines and relief colors. Old
            # JPEG caches are deliberately not reused: their chroma is blurred.
            cached = self.color_cache / f"{age:g}.png"
            if cached.exists():
                payload = np.fromfile(cached, dtype=np.uint8)
                decoded = cv2.imdecode(payload, cv2.IMREAD_COLOR)
                if decoded is not None:
                    return np.ascontiguousarray(cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB))
            return self._dem_image(age)
        return self._old_image(int(age))

    def _dem_image(self, age: float):
        elevation = self.elevation(age)
        depth_index = np.clip(np.rint(elevation), -5200, 0).astype(np.int32) + 5200
        land_index = np.clip(np.rint(elevation), 0, 4300).astype(np.int32)
        colors = np.where(
            (elevation < 0)[..., None], SEA_LUT[depth_index], LAND_LUT[land_index]
        ).astype(np.float32)

        # The smooth Precambrian source is quantized in 40 m steps. Derivatives
        # of those steps draw artificial contour rings. Soften illumination
        # alone by less than a grid cell; coast masks and palette heights still
        # use the unchanged source above. Detailed younger terrain stays sharp.
        dx, dy = self._slopes(elevation, age)
        shade = relief_shade(dx, dy, elevation < 0)
        return np.ascontiguousarray(np.rint(np.clip(colors * shade[..., None], 0, 255)).astype(np.uint8))

    @staticmethod
    def _read_elevation(payload: bytes):
        """Read either PALEOMAP format into south-to-north, -180-to-180 pixels."""
        # netCDF/HDF5 readers share native state across the globe's workers.
        with _NETCDF_LOCK, netCDF4.Dataset("paleodem", memory=payload) as nc:
            lat_var = nc.variables.get("latitude")
            lon_var = nc.variables.get("longitude")
            if lat_var is None or lon_var is None:
                raise ValueError("В PaleoDEM отсутствуют координаты широты или долготы")
            latitudes = np.asarray(lat_var[:])
            longitudes = np.asarray(lon_var[:])
            dimensions = (lat_var.dimensions[0], lon_var.dimensions[0])
            candidates = [var for var in nc.variables.values()
                          if var.ndim == 2 and set(var.dimensions) == set(dimensions)]
            if len(candidates) != 1:
                raise ValueError("Не удалось однозначно определить слой высот PaleoDEM")
            variable = candidates[0]
            elevation = np.ma.asarray(variable[:], dtype=np.float32).filled(np.nan)
            if variable.dimensions != dimensions:
                elevation = elevation.T
            # A global grid repeats the antimeridian at both ends. Upload one
            # copy, then sort longitude for the globe's periodic texture axis.
            if np.isclose(abs(longitudes[-1] - longitudes[0]), 360.0):
                longitudes = longitudes[:-1]
                elevation = elevation[:, :-1]
            longitude_order = np.argsort((longitudes + 180.0) % 360.0 - 180.0)
            elevation = elevation[:, longitude_order]
            # OpenGL uploads row zero at the bottom, so it must be the south.
            if latitudes[0] > latitudes[-1]:
                elevation = np.flipud(elevation)
        return np.ascontiguousarray(np.nan_to_num(elevation, nan=-5200.0,
                                                 neginf=-11000.0, posinf=9000.0))

    def _old_image(self, age: int):
        source = cv2.imdecode(np.fromfile(self.old_rasters[age], dtype=np.uint8), cv2.IMREAD_COLOR)
        if source is None:
            raise OSError(f"Не удалось прочитать карту {age} млн лет")
        hsv = cv2.cvtColor(source, cv2.COLOR_BGR2HSV)
        # Older-than-540-Ma snapshots have no 2018 height grid. Recolor the
        # source by its water/land hues without claiming a newer reconstruction.
        sea = (hsv[..., 0] >= 83) & (hsv[..., 0] <= 130) & (hsv[..., 1] > 54)
        brightness = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        depth = np.clip((brightness * 5900 - 5200).astype(np.int32), -5200, 0)
        heights = np.clip((brightness * 4300).astype(np.int32), 0, 4300)
        recolored = np.where(sea[..., None], SEA_LUT[depth + 5200], LAND_LUT[heights])
        return np.ascontiguousarray(np.flipud(recolored.astype(np.uint8)))
