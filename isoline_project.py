"""Read a bounded inventory of an Isoline GIS IPR project.

This module inspects the version of the structured IPR container used by
Isoline GIS 2020. It does not import, decompress or georeference geometry.
Opaque layer data is never searched for coordinates or executable content.
External image paths are reported as text and are never opened or resolved.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct


MAX_PROJECT_BYTES = 60 * 1024 * 1024
MAX_MAPS = 256
MAX_LAYERS = 4096
MAX_TEXT_BYTES = 16 * 1024
MAX_METADATA_BYTES = 1024 * 1024

_IPR_MAGIC = bytes.fromhex("EA749342A657414F98AC60E3D41F3516")
_STRUCT_VERSION = b"\x1e\x35\x05\x01"
_LSS_VERSION = b"LSS\x1e\x35\x05\x00"

# These field IDs describe container structure, not geographic coordinates.
_PROJECT = 0x00015695
_MAP_COLLECTION = 0x00015602
_MAP_SLOT = 0x00010EB3
_MAP = 0x00015676
_MAP_VIEW = 0x0001C27A
_MAP_DATA = 0x0002F2FA
_PROJECTION = 0x00010AE4
_LAYER = 0x0002766A
_LAYER_METADATA = 0x00019EFA


@dataclass(frozen=True)
class IsolineProjectInfo:
    """Project inventory only; no polygon coordinates are imported."""

    project_name: str
    polygon_layer_names: list[str]
    layer_count: int
    projection: str | None
    external_files: list[str]


class _FormatError(ValueError):
    pass


class _Reader:
    """Cursor whose reads and child TLV fields stay inside their parent."""

    def __init__(self, data: memoryview, start: int = 0, end: int | None = None):
        self.data = data
        self.pos = start
        self.end = len(data) if end is None else end
        if not 0 <= start <= self.end <= len(data):
            raise _FormatError("Некорректные границы блока IPR.")

    @property
    def remaining(self) -> int:
        return self.end - self.pos

    def take(self, count: int) -> memoryview:
        if count < 0 or count > self.remaining:
            raise _FormatError("Блок IPR обрезан или его длина выходит за границы родителя.")
        start = self.pos
        self.pos += count
        return self.data[start:self.pos]

    def byte(self) -> int:
        return self.take(1)[0]

    def expect(self, expected: int) -> None:
        if self.byte() != expected:
            raise _FormatError("Не поддерживается структура этого блока IPR.")

    def field(self, expected_id: int | None = None) -> tuple[int, _Reader]:
        self.expect(0x64)
        field_id, size = struct.unpack("<II", self.take(8))
        if expected_id is not None and field_id != expected_id:
            raise _FormatError("Не поддерживается структура полей этой версии IPR.")
        start = self.pos
        self.take(size)
        return field_id, _Reader(self.data, start, self.pos)

    def length(self, maximum: int) -> int:
        size = self.byte()
        if size == 0xFE:
            size = struct.unpack("<I", self.take(4))[0]
        elif size == 0xFF:
            raise _FormatError("Не поддерживается кодировка длины значения IPR.")
        if size > maximum:
            raise _FormatError("Значение IPR превышает допустимый размер.")
        return size

    def text(self) -> str:
        self.expect(0x8C)
        raw = bytes(self.take(self.length(MAX_TEXT_BYTES)))
        try:
            value = raw.decode("cp1251")
        except UnicodeDecodeError as exc:
            raise _FormatError("Некорректная кодировка названия в IPR.") from exc
        if any(ord(char) < 32 for char in value):
            raise _FormatError("Название в IPR содержит управляющие символы.")
        return value

    def binary(self) -> memoryview:
        self.expect(0x96)
        return self.take(self.length(MAX_METADATA_BYTES))

    def count(self, maximum: int) -> int:
        marker = self.byte()
        if 0xAA <= marker <= 0xBD:
            value = marker - 0xAA
        elif marker == 0x6F:
            value = struct.unpack("<b", self.take(1))[0]
        elif marker == 0x70:
            value = struct.unpack("<h", self.take(2))[0]
        elif marker == 0x71:
            value = struct.unpack("<i", self.take(4))[0]
        else:
            raise _FormatError("Не поддерживается запись количества объектов в IPR.")
        if not 0 <= value <= maximum:
            raise _FormatError("Количество объектов IPR выходит за допустимые пределы.")
        return value


def _validate_layer_metadata(data: memoryview) -> None:
    reader = _Reader(data)
    if bytes(reader.take(len(_LSS_VERSION))) != _LSS_VERSION:
        raise _FormatError("Не поддерживается версия метаданных слоя IPR.")
    reader.field(_LAYER_METADATA)
    if reader.remaining:
        raise _FormatError("Некорректная длина метаданных слоя IPR.")


def _projection_name(reader: _Reader) -> str | None:
    name = reader.text().strip()
    # Projection parameters remain opaque. Validate only their TLV framing;
    # neither a name nor arbitrary Rect units establish a geographic CRS.
    count = 0
    while reader.remaining:
        reader.field()
        count += 1
        if count > 256:
            raise _FormatError("Слишком много полей описания проекции IPR.")
    return name or None


def _inventory_map(
    reader: _Reader,
    polygon_names: list[str],
    projections: list[str],
    external_files: list[str],
    existing_layer_count: int,
) -> int:
    reader.expect(0xAB)
    _, map_record = reader.field(_MAP)
    if reader.remaining:
        raise _FormatError("Некорректная длина записи карты IPR.")
    _, map_view = map_record.field(_MAP_VIEW)
    _, map_data = map_view.field(_MAP_DATA)

    map_data.expect(0x9A)
    map_data.take(16)  # Map identifier, not a coordinate reference system.
    map_data.expect(0x86)
    _, projection = map_data.field(_PROJECTION)
    name = _projection_name(projection)
    if name and name not in projections:
        projections.append(name)
    count = map_data.count(MAX_LAYERS - existing_layer_count)

    for number in range(count):
        _, layer = map_data.field(_LAYER)
        layer_class = layer.text()
        _validate_layer_metadata(layer.binary())
        layer_name = layer.text().strip() or f"Слой {existing_layer_count + number + 1}"
        if layer_class == "TPolygonsMapLayer":
            polygon_names.append(layer_name)
        elif layer_class == "TImageMapLayer":
            # This is the dedicated external-image filename field immediately
            # after the layer name. Do not scan history or opaque data for paths.
            external_path = layer.text().strip()
            if external_path and external_path not in external_files:
                external_files.append(external_path)
        # The rest of each layer contains styles and possibly packed geometry.
        # Its parent TLV length was checked; none of that payload is executed,
        # decompressed, interpreted as XY pairs, or followed as a filesystem path.
    return count


def _inspect(data: bytes, project_name: str) -> IsolineProjectInfo:
    reader = _Reader(memoryview(data))
    if bytes(reader.take(16)) != _IPR_MAGIC:
        raise _FormatError("Файл не является поддерживаемым проектом Isoline IPR.")
    if bytes(reader.take(4)) != _STRUCT_VERSION:
        raise _FormatError("Не поддерживается версия контейнера Isoline IPR.")
    section_start = reader.pos
    section_size = struct.unpack("<I", reader.take(4))[0]
    if section_size < 21 or section_size > len(data) - section_start:
        raise _FormatError("Некорректная длина основного раздела IPR.")
    section = _Reader(reader.data, reader.pos, section_start + section_size)
    section.take(8)  # Fixed container metadata preceding the first TLV field.
    _, project = section.field(_PROJECT)
    if section.remaining:
        raise _FormatError("Некорректная длина основного блока проекта IPR.")

    collection = None
    field_count = 0
    while project.remaining:
        field_id, value = project.field()
        if field_id == _MAP_COLLECTION:
            if collection is not None:
                raise _FormatError("В IPR неоднозначное описание списка карт.")
            collection = value
        field_count += 1
        if field_count > 256:
            raise _FormatError("Слишком много полей проекта IPR.")
    if collection is None:
        raise _FormatError("В проекте IPR не найден поддерживаемый список карт.")

    polygon_names: list[str] = []
    projections: list[str] = []
    external_files: list[str] = []
    layer_count = 0
    for _ in range(collection.count(MAX_MAPS)):
        _, slot = collection.field(_MAP_SLOT)
        if slot.remaining == 1 and slot.data[slot.pos] == 0xAA:
            continue  # An empty map slot is not a layer.
        layer_count += _inventory_map(
            slot, polygon_names, projections, external_files, layer_count
        )
    if collection.remaining:
        raise _FormatError("Длина списка карт IPR не совпадает с количеством записей.")
    # The file can also contain thumbnails and an object-tree index after its
    # primary section. They are not layer instances and must not be counted.
    return IsolineProjectInfo(
        project_name=project_name,
        polygon_layer_names=polygon_names,
        layer_count=layer_count,
        projection="; ".join(projections) or None,
        external_files=external_files,
    )


def inspect_isoline_project(path: str | Path) -> IsolineProjectInfo:
    """Inspect an IPR inventory without importing its polygon geometry.

    ``Rect`` means arbitrary rectangular project coordinates. This function
    deliberately makes no WGS84, EPSG, coordinate-axis or georeferencing guess.
    No referenced image, vendor library or vendor executable is opened.
    """
    source = Path(path)
    try:
        with source.open("rb") as stream:
            data = stream.read(MAX_PROJECT_BYTES + 1)
        if len(data) > MAX_PROJECT_BYTES:
            raise _FormatError("Размер проекта IPR превышает 60 МБ.")
        return _inspect(data, source.stem)
    except _FormatError as exc:
        raise ValueError(f"{source.name}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"{source.name}: не удалось прочитать проект IPR ({exc}).") from exc
