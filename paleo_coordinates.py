"""GIS coordinate transformations for paleo-geological overlays.

CRS MUST be supplied by the user: numeric values alone cannot identify a datum,
Gauss-Kruger zone, local MSK, axis order or transformation accuracy.
The GIS axis convention is X=easting/longitude, Y=northing/latitude.
"""
from __future__ import annotations

from functools import lru_cache
import math


class CoordinateSystemError(ValueError):
    """Invalid source coordinates, CRS, or coordinate transformation."""


def gauss_kruger_epsg(zone: int, datum: str = "SK-42") -> str:
    """Return EPSG for 6-degree GK with zone-prefixed easting (SK-42/SK-95)."""
    if isinstance(zone, bool) or not isinstance(zone, int) or not 2 <= zone <= 31:
        raise CoordinateSystemError("Номер шестиградусной зоны Гаусса — Крюгера: 2–31.")
    norm = datum.upper().replace(" ", "").replace("_", "-")
    prefixes = {"SK-42": 28400, "SK42": 28400, "SK-95": 20000, "SK95": 20000}
    if norm not in prefixes:
        raise CoordinateSystemError("Доступны SK-42 и SK-95; для других СК укажите EPSG/WKT.")
    crs = f"EPSG:{prefixes[norm] + zone}"
    try:
        from pyproj import CRS
        CRS.from_user_input(crs)
    except ImportError as exc:
        raise CoordinateSystemError("Необходим pyproj (python -m pip install pyproj).") from exc
    except Exception as exc:
        raise CoordinateSystemError(f"В PROJ отсутствует {crs}.") from exc
    return crs


@lru_cache(maxsize=64)
def _transformer(source_crs: str, target_crs: str):
    try:
        from pyproj import CRS, Transformer
        source, target = CRS.from_user_input(source_crs), CRS.from_user_input(target_crs)
        transformer = (None if source == target else
                       Transformer.from_crs(source, target, always_xy=True, allow_ballpark=False))
        return source, target, transformer
    except ImportError as exc:
        raise CoordinateSystemError("Необходим pyproj (python -m pip install pyproj).") from exc
    except Exception as exc:
        raise CoordinateSystemError(f"Ошибка системы координат/PROJ: {exc}") from exc


class CoordinateTransformer:
    def __init__(self, source_crs: str | int, target_crs: str | int,
                 *, source_axis_order: str = "xy", target_axis_order: str = "xy"):
        if source_axis_order not in ("xy", "yx") or target_axis_order not in ("xy", "yx"):
            raise CoordinateSystemError("Порядок осей: xy либо yx.")
        self.source_axis_order, self.target_axis_order = source_axis_order, target_axis_order
        self.source, self.target, self.converter = _transformer(str(source_crs), str(target_crs))

    @property
    def target_is_geographic(self) -> bool:
        return self.target.is_geographic

    def transform(self, first: float, second: float) -> tuple[float, float]:
        try:
            x, y = float(first), float(second)
            if not (math.isfinite(x) and math.isfinite(y)):
                raise CoordinateSystemError("Координаты NaN/Inf недопустимы.")
            if self.source_axis_order == "yx":
                x, y = y, x
            if self.source.is_geographic and not (-180 <= x <= 180 and -90 <= y <= 90):
                raise CoordinateSystemError("Исходные координаты не являются долготой/широтой. Проверьте CRS.")
            if self.converter is not None:
                x, y = self.converter.transform(x, y, errcheck=True)
            if not (math.isfinite(x) and math.isfinite(y)):
                raise CoordinateSystemError("Нечисловой результат преобразования.")
            if self.target.is_geographic and not (-180 <= x <= 180 and -90 <= y <= 90):
                raise CoordinateSystemError("Результат вне допустимого диапазона долготы/широты.")
            return (y, x) if self.target_axis_order == "yx" else (x, y)
        except CoordinateSystemError:
            raise
        except Exception as exc:
            raise CoordinateSystemError(f"Невозможно преобразовать ({first}, {second}): {exc}") from exc


def transform_xy(first: float, second: float, source_crs: str | int, target_crs: str | int,
                 *, source_axis_order: str = "xy", target_axis_order: str = "xy"):
    return CoordinateTransformer(source_crs, target_crs,
        source_axis_order=source_axis_order,
        target_axis_order=target_axis_order).transform(first, second)
