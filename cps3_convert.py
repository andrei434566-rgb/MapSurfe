"""CPS-3 ASCII XY polygon reader and CRS converter (not ZMAP raster grids).

Examples:
  python cps3_convert.py input.cps output_gk.cps --from-crs EPSG:4326 --to-crs EPSG:28413
  python cps3_convert.py input_gk.cps output_geo.cps --from-crs EPSG:28413 --to-crs EPSG:4326
The optional third Z column is copied as-is; vertical datums are not transformed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path

from paleo_coordinates import CoordinateTransformer

MAX_BYTES = 60 * 1024 * 1024
MAX_VERTICES = 250_000


@dataclass
class CPS3Polygon:
    name: str
    points: list[tuple[float, float, float | None]]


def read_cps3(path: str | Path) -> list[CPS3Polygon]:
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Файл CPS-3 больше 60 МБ.")
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1251", "cp1252"):
        try:
            lines = raw.decode(encoding).splitlines()
            break
        except UnicodeDecodeError:
            pass
    else:
        raise ValueError("Не удалось определить кодировку CPS-3.")
    features: list[CPS3Polygon] = []
    current: list[tuple[float, float, float | None]] = []
    name = path.stem
    vertex_count = 0

    def flush() -> None:
        nonlocal current
        if not current:
            return
        if len(current) > 1 and current[0][:2] == current[-1][:2]:
            current.pop()
        if len(current) < 3:
            raise ValueError(f"В контуре '{name}' меньше трёх вершин.")
        features.append(CPS3Polygon(name, current))
        current = []

    for line_number, rawline in enumerate(lines, 1):
        line = rawline.strip()
        if not line or line.startswith(("!", "#")):
            continue
        if line.startswith("->"):
            flush()
            name = line[2:].strip() or f"Контур {len(features) + 1}"
            continue
        if line.startswith("@"):
            raise ValueError("Это сетка CPS-3/ZMAP, а не ASCII XY-полигон.")
        parts = line.replace(",", " ").replace(";", " ").split()
        if len(parts) < 2:
            if not current:
                continue
            raise ValueError(f"Строка {line_number}: ожидаются координаты X Y [Z].")
        try:
            x, y = float(parts[0]), float(parts[1])
            z = float(parts[2]) if len(parts) >= 3 else None
        except ValueError as exc:
            if not current:
                continue
            raise ValueError(f"Строка {line_number}: неверные числа.") from exc
        if not math.isfinite(x) or not math.isfinite(y) or (z is not None and not math.isfinite(z)):
            raise ValueError(f"Строка {line_number}: NaN/Inf.")
        vertex_count += 1
        if vertex_count > MAX_VERTICES:
            raise ValueError("Больше 250 000 вершин.")
        current.append((x, y, z))
    flush()
    if not features:
        raise ValueError("Не найдены полигоны CPS-3 ASCII XY.")
    return features


def to_wgs84_polygons(path: str | Path, source_crs: str = "EPSG:4326",
                      *, axis_order: str = "xy") -> list[tuple[str, list[tuple[float, float]]]]:
    transform = CoordinateTransformer(source_crs, "EPSG:4326", source_axis_order=axis_order)
    return [(polygon.name, [transform.transform(x, y) for x, y, z in polygon.points])
            for polygon in read_cps3(path)]


def convert_cps3_file(source: str | Path, destination: str | Path,
                      *, source_crs: str, target_crs: str,
                      source_axis_order: str = "xy", target_axis_order: str = "xy") -> Path:
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("Исходный и выходной файл должны быть разными.")
    polygons = read_cps3(source)
    transformer = CoordinateTransformer(
        source_crs, target_crs,
        source_axis_order=source_axis_order, target_axis_order=target_axis_order)
    precision = 9 if transformer.target_is_geographic else 4
    rows = [
        f"! CPS-3 polygon coordinates. CRS={target_crs}; AXIS_ORDER={target_axis_order}",
        "! Z values are preserved, not vertically transformed.",
    ]
    for poly in polygons:
        rows.append("->" + poly.name.replace("\r", " ").replace("\n", " "))
        for x, y, z in poly.points:
            xnew, ynew = transformer.transform(x, y)
            row = f"{xnew:.{precision}f} {ynew:.{precision}f}"
            if z is not None:
                row += f" {z:.8f}"
            rows.append(row)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="CPS-3 ASCII XY: координаты и Гаусс — Крюгер")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--from-crs", required=True, help="EPSG или WKT исходных данных")
    parser.add_argument("--to-crs", required=True, help="EPSG или WKT выходных данных")
    parser.add_argument("--from-order", choices=("xy", "yx"), default="xy")
    parser.add_argument("--to-order", choices=("xy", "yx"), default="xy")
    args = parser.parse_args()
    output = convert_cps3_file(
        args.source, args.destination,
        source_crs=args.from_crs, target_crs=args.to_crs,
        source_axis_order=args.from_order, target_axis_order=args.to_order)
    print(f"Готово: {output}")


if __name__ == "__main__":
    main()
