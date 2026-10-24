"""CPS-3 ASCII XY / numbered closed LINES reader and CRS converter.

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
MAX_CONTOURS = 10_000
MAX_LINE_CHARS = 16_384


@dataclass
class CPS3Polygon:
    name: str
    points: list[tuple[float, float, float | None]]


def _fsasci_directive(line: str) -> bool:
    """Recognise the native CPS-3 header, including malformed spellings of it."""
    token = line.split(maxsplit=1)[0].upper() if line else ""
    return token.startswith(("#FSASC", "#FATTR"))


def _read_fsasci_lines(lines: list[str], path: Path) -> list[CPS3Polygon]:
    """Read the confirmed native CPS-3 LINES variant with numbered closed XY rings.

    Header fields are accepted as an exact supported variant, not interpreted as
    CRS information or an attribute schema. Other FSASCI variants need a sample
    and a format description before they can be imported safely.
    """
    features: list[CPS3Polygon] = []
    current: list[tuple[float, float, float | None]] = []
    current_id: str | None = None
    vertex_count = 0
    state = "fsasci"
    undefined = 1e10

    def flush(line_number: int) -> None:
        nonlocal current
        if current_id is None:
            return
        label = f"Контур {current_id}"
        if not current:
            raise ValueError(f"Строка {line_number}: у контура {current_id} нет координат.")
        if current[0][:2] != current[-1][:2]:
            raise ValueError(
                f"{label}: линия CPS-3 не замкнута. Для полигона последняя "
                "пара X Y должна повторять первую.")
        while len(current) > 1 and current[0][:2] == current[-1][:2]:
            current.pop()
        if len({point[:2] for point in current}) < 3:
            raise ValueError(f"В контуре {current_id} меньше трёх различных вершин.")
        if len(features) >= MAX_CONTOURS:
            raise ValueError("Больше 10 000 контуров CPS-3.")
        features.append(CPS3Polygon(f"{path.stem} — контур {current_id}", current))
        current = []

    for line_number, rawline in enumerate(lines, 1):
        if len(rawline) > MAX_LINE_CHARS:
            raise ValueError(f"Строка {line_number}: слишком длинная строка CPS-3.")
        line = rawline.strip()
        if not line or line.startswith("!"):
            continue
        parts = line.split()
        if state == "fsasci":
            if (len(parts) != 6 or parts[:5] != ["#FSASCI", "0", "1", "LINES", "0"]):
                raise ValueError(
                    f"Строка {line_number}: неподдерживаемый или неполный заголовок CPS-3. "
                    "Поддерживается #FSASCI 0 1 LINES 0 1e+10.")
            try:
                header_undefined = float(parts[5])
            except ValueError as exc:
                raise ValueError(
                    f"Строка {line_number}: неверное неопределённое значение в #FSASCI.") from exc
            if header_undefined != undefined:
                raise ValueError(
                    f"Строка {line_number}: неподдерживаемый заголовок #FSASCI. "
                    "Для этого варианта ожидается неопределённое значение 1e+10.")
            state = "fattr"
            continue
        if state == "fattr":
            if parts != ["#FATTR", "0", "3"]:
                raise ValueError(
                    f"Строка {line_number}: после #FSASCI ожидается #FATTR 0 3. "
                    "Другие схемы атрибутов пока не поддерживаются.")
            state = "data"
            continue
        if line.startswith(("#", "@", "->")):
            raise ValueError(
                f"Строка {line_number}: неподдерживаемая директива внутри CPS-3 LINES.")
        if len(parts) == 1:
            identifier = parts[0]
            if (not identifier.isascii() or not identifier.isdigit()
                    or len(identifier) > 20):
                raise ValueError(
                    f"Строка {line_number}: ожидается целый номер контура "
                    "или пара координат X Y.")
            flush(line_number)
            current_id = identifier
            continue
        if len(parts) != 2:
            raise ValueError(
                f"Строка {line_number}: CPS-3 LINES ожидает ровно две колонки X Y; "
                f"найдено {len(parts)}. Другие колонки и атрибуты не поддерживаются.")
        if current_id is None:
            raise ValueError(
                f"Строка {line_number}: перед координатами отсутствует номер контура.")
        try:
            x, y = (float(token.replace(",", ".")) for token in parts)
        except ValueError as exc:
            raise ValueError(
                f"Строка {line_number}: неверные координаты X Y. "
                "Разделите координаты пробелом; допустимы десятичная точка или запятая.") from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"Строка {line_number}: координаты NaN/Inf недопустимы.")
        if x == undefined or y == undefined:
            raise ValueError(
                f"Строка {line_number}: найдено неопределённое значение CPS-3 1e+10 "
                f"в контуре {current_id}. Удалите или исправьте пропущенную вершину.")
        vertex_count += 1
        if vertex_count > MAX_VERTICES:
            raise ValueError("Больше 250 000 вершин.")
        current.append((x, y, None))
    if state != "data":
        missing = "#FSASCI и #FATTR" if state == "fsasci" else "#FATTR 0 3"
        raise ValueError(f"Неполный заголовок CPS-3: отсутствует {missing}.")
    flush(len(lines) + 1)
    if not features:
        raise ValueError("В CPS-3 LINES не найдены замкнутые контуры.")
    return features


def read_cps3(path: str | Path) -> list[CPS3Polygon]:
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Файл CPS-3 больше 60 МБ.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Файл CPS-3 больше 60 МБ.")
    for encoding in ("utf-8-sig", "cp1251", "cp1252"):
        try:
            lines = raw.decode(encoding).splitlines()
            break
        except UnicodeDecodeError:
            pass
    else:
        raise ValueError("Не удалось определить кодировку CPS-3.")
    if any(_fsasci_directive(line.strip()) for line in lines):
        return _read_fsasci_lines(lines, path)
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
        spaced_parts = line.replace(";", " ").split()
        decimal_comma = (len(spaced_parts) in (2, 3)
                         and all(item.count(",") == 1 and not item.endswith(",")
                                 for item in spaced_parts[:2])
                         and all(item.count(",") <= 1 and "." not in item
                                 for item in spaced_parts))
        if (not decimal_comma and len(spaced_parts) in (2, 3)
                and any("," in item and not item.endswith(",") for item in spaced_parts)):
            try:
                for item in spaced_parts:
                    float(item.replace(",", "."))
            except ValueError:
                pass
            else:
                raise ValueError(
                    f"Строка {line_number}: неоднозначные запятые в координатах. "
                    "Используйте десятичную точку и пробелы между X Y [Z] "
                    "либо десятичную запятую в обеих координатах X и Y.")
        parts = ([item.replace(",", ".") for item in spaced_parts] if decimal_comma
                 else line.replace(",", " ").replace(";", " ").split())
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
        if len(parts) > 3:
            raise ValueError(
                f"Строка {line_number}: найдено {len(parts)} колонок. "
                "Загрузчик CPS-3 ожидает X Y или X Y Z. "
                "Таблица с ID, номером контура или другими колонками требует "
                "отдельного описания формата; эти значения нельзя считать координатами.")
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
    parser = argparse.ArgumentParser(description="CPS-3 XY / LINES: координаты и Гаусс — Крюгер")
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
