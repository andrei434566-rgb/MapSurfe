"""Local polygon import for GeoJSON, KML and WGS84 Shapefile ZIP files."""
from __future__ import annotations

import json
import math
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


MAX_BYTES = 60 * 1024 * 1024
MAX_VERTICES = 250_000


@dataclass
class PolygonFeature:
    name: str
    rings: list[list[tuple[float, float]]]

    @property
    def center(self) -> tuple[float, float]:
        ring = self.rings[0]
        # A simple vertex average works for placing a label; geometry is retained intact.
        return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)


@dataclass
class PolygonLayer:
    name: str
    path: Path
    features: list[PolygonFeature]
    plate: str = "Евразия"
    visible: bool = True


def _ring(points) -> list[tuple[float, float]]:
    out = []
    for point in points:
        if len(point) < 2:
            raise ValueError("Некорректная пара координат в полигоне.")
        lon, lat = float(point[0]), float(point[1])
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("Координаты выходят за пределы WGS84. Перепроецируй слой в EPSG:4326.")
        out.append((lon, lat))
    if len(out) < 3:
        raise ValueError("В контуре меньше трёх точек.")
    if out[0] == out[-1]:
        out.pop()
    return out


def _from_geojson(path: Path) -> list[PolygonFeature]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Ожидается объект GeoJSON FeatureCollection, Feature или Polygon.")
    crs = data.get("crs")
    if crs and "4326" not in str(crs) and "CRS84" not in str(crs).upper():
        raise ValueError("GeoJSON должен быть в WGS84 / EPSG:4326.")
    if data.get("type") == "FeatureCollection":
        source = data.get("features", [])
    elif data.get("type") == "Feature":
        source = [data]
    else:
        source = [{"type": "Feature", "geometry": data, "properties": {}}]
    features = []
    for number, feature in enumerate(source, 1):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        kind, coordinates = geometry.get("type"), geometry.get("coordinates")
        if kind not in ("Polygon", "MultiPolygon"):
            continue
        polygons = [coordinates] if kind == "Polygon" else coordinates
        properties = feature.get("properties") or {}
        name = next((str(properties[key]) for key in ("name", "NAME", "title", "TITLE", "license", "ЛУ", "участок")
                     if properties.get(key)), f"Участок {number}")
        for polygon_number, polygon in enumerate(polygons, 1):
            rings = [_ring(ring) for ring in polygon if len(ring) >= 3]
            if rings:
                suffix = f" · {polygon_number}" if len(polygons) > 1 else ""
                features.append(PolygonFeature(name + suffix, rings))
    return features


def _kml_coords(text: str) -> list[tuple[float, float]]:
    points = []
    for token in (text or "").split():
        pair = token.split(",")
        if len(pair) >= 2:
            points.append((pair[0], pair[1]))
    return _ring(points)


def _from_kml(path: Path) -> list[PolygonFeature]:
    root = ET.parse(path).getroot()
    features = []
    for number, placemark in enumerate(root.iter(), 1):
        if placemark.tag.split("}")[-1] != "Placemark":
            continue
        name = next((el.text for el in placemark if el.tag.split("}")[-1] == "name" and el.text), f"Участок {number}")
        for polygon in placemark.iter():
            if polygon.tag.split("}")[-1] != "Polygon":
                continue
            rings = []
            for boundary in polygon.iter():
                if boundary.tag.split("}")[-1] == "coordinates":
                    rings.append(_kml_coords(boundary.text or ""))
            if rings:
                features.append(PolygonFeature(str(name), rings))
    return features


def _from_cps3_ascii(path: Path, *, source_crs: str = "EPSG:4326",
                     axis_order: str = "xy") -> list[PolygonFeature]:
    """Load CPS-3 ASCII XY polygons using the declared CRS and order.

    For example SK-42 6-degree Gauss-Kruger zone 13: EPSG:28413.
    Use axis_order="yx" for Northing/Easting input. Never guess a CRS.
    """
    from cps3_convert import to_wgs84_polygons
    return [PolygonFeature(name, [_ring(points)]) for name, points in
            to_wgs84_polygons(path, source_crs, axis_order=axis_order)]


def _dbf_names(raw: bytes, count: int) -> list[str]:
    if len(raw) < 32:
        return []
    record_count = min(struct.unpack_from("<I", raw, 4)[0], count)
    header_length = struct.unpack_from("<H", raw, 8)[0]
    record_length = struct.unpack_from("<H", raw, 10)[0]
    fields = []
    offset = 1
    at = 32
    while at + 32 <= len(raw) and raw[at] != 13:
        descriptor = raw[at:at+32]
        name = descriptor[:11].split(b"\0", 1)[0].decode("ascii", "ignore").strip()
        length = descriptor[16]
        fields.append((name, offset, length))
        offset += length
        at += 32
    name_field = next(((offset, length) for name, offset, length in fields
                       if name.lower() in ("name", "title", "license", "lic_name", "site_name", "object")), None)
    if name_field is None:
        name_field = next(((offset, length) for name, offset, length in fields if name), None)
    if name_field is None:
        return []
    names = []
    for i in range(record_count):
        start = header_length + i * record_length
        field = raw[start+name_field[0]:start+name_field[0]+name_field[1]]
        for encoding in ("utf-8", "cp1251", "cp1252"):
            try:
                names.append(field.decode(encoding).strip())
                break
            except UnicodeDecodeError:
                continue
    return names


def _from_shapefile_zip(path: Path) -> list[PolygonFeature]:
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        shp_name = next((name for name in members if name.lower().endswith(".shp")), None)
        if not shp_name:
            raise ValueError("В ZIP нет файла .shp.")
        stem = shp_name[:-4].lower()
        prj_name = next((name for name in members if name.lower() == stem + ".prj"), None)
        if prj_name is None:
            raise ValueError("В ZIP нет .prj. Нужна подтверждённая система WGS84 / EPSG:4326.")
        if archive.getinfo(shp_name).file_size > MAX_BYTES:
            raise ValueError("Распакованный Shapefile больше 60 МБ.")
        projection = archive.read(prj_name).decode("utf-8-sig", "ignore").upper()
        if "PROJCS" in projection or "PROJCRS" in projection or "PROJECTEDCRS" in projection:
            raise ValueError("Shapefile имеет проекционные координаты. Перепроецируй в WGS84 / EPSG:4326.")
        if not ("WGS_1984" in projection or "WGS 84" in projection or "4326" in projection):
            raise ValueError("Shapefile должен быть в WGS84 / EPSG:4326. Перепроецируй его в GIS.")
        shp = archive.read(shp_name)
        dbf_name = next((name for name in members if name.lower() == stem + ".dbf"), None)
        names = _dbf_names(archive.read(dbf_name), 100_000) if dbf_name else []
    if len(shp) < 100 or struct.unpack_from(">I", shp, 0)[0] != 9994:
        raise ValueError("Некорректный Shapefile.")
    if struct.unpack_from("<I", shp, 32)[0] not in (5, 15, 25):
        raise ValueError("Shapefile должен содержать полигоны.")
    features = []
    at = 100
    record_number = 0
    while at + 8 <= len(shp):
        length = struct.unpack_from(">I", shp, at+4)[0] * 2
        start, end = at+8, at+8+length
        if end > len(shp) or length < 4:
            raise ValueError("Повреждённая запись Shapefile.")
        record_number += 1
        shape_type = struct.unpack_from("<I", shp, start)[0]
        if shape_type in (5, 15, 25):
            if start + 44 > end:
                raise ValueError("Повреждённая геометрия Shapefile.")
            part_count, point_count = struct.unpack_from("<II", shp, start+36)
            parts_start = start + 44
            points_start = parts_start + part_count * 4
            if point_count > MAX_VERTICES or points_start + point_count * 16 > end:
                raise ValueError("Слишком много точек или повреждённая геометрия.")
            starts = [struct.unpack_from("<I", shp, parts_start+i*4)[0] for i in range(part_count)] + [point_count]
            rings = []
            for a,b in zip(starts, starts[1:]):
                points = [struct.unpack_from("<dd", shp, points_start+i*16) for i in range(a,b)]
                if len(points) >= 3:
                    rings.append(_ring(points))
            if rings:
                name = names[record_number-1] if record_number <= len(names) and names[record_number-1] else f"Участок {record_number}"
                features.append(PolygonFeature(name, rings))
        at = end
    return features


def load_polygon_layer(path: str | Path, *, source_crs: str = "EPSG:4326",
                       axis_order: str = "xy") -> PolygonLayer:
    source = Path(path)
    if source.stat().st_size > MAX_BYTES:
        raise ValueError("Слой больше 60 МБ. Упрости геометрию или раздели файл.")
    suffix = source.suffix.lower()
    if suffix in (".geojson", ".json"):
        features = _from_geojson(source)
    elif suffix == ".kml":
        features = _from_kml(source)
    elif suffix == ".zip":
        features = _from_shapefile_zip(source)
    elif suffix in (".cps", ".cps3", ".dat", ".pol", ".txt"):
        features = _from_cps3_ascii(source, source_crs=source_crs, axis_order=axis_order)
    else:
        raise ValueError("Поддерживаются CPS-3 ASCII XY, GeoJSON, KML и Shapefile ZIP в WGS84.")
    if not features:
        raise ValueError("В файле нет полигонов.")
    if sum(len(ring) for feature in features for ring in feature.rings) > MAX_VERTICES:
        raise ValueError("Больше 250 000 вершин. Упрости слой перед импортом.")
    return PolygonLayer(source.stem, source, features)
