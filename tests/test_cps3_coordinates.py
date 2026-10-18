from pathlib import Path

import pytest

from cps3_convert import convert_cps3_file, read_cps3, to_wgs84_polygons
from paleo_coordinates import CoordinateSystemError, CoordinateTransformer, gauss_kruger_epsg
from geo_layers import load_polygon_layer


def sample_polygon(tmp_path: Path):
    file = tmp_path / "polygon.cps"
    file.write_text("""! WGS84 polygon
->Тестовый участок
72.0000 60.0000 150
72.0400 60.0000 150
72.0400 60.0200 150
72.0000 60.0200 150
72.0000 60.0000 150
""", encoding="utf-8")
    return file


def test_gk_code():
    assert gauss_kruger_epsg(13, "SK-42") == "EPSG:28413"
    assert gauss_kruger_epsg(13, "SK-95") == "EPSG:20013"
    with pytest.raises(CoordinateSystemError):
        gauss_kruger_epsg(1)


def test_convert_round_trip(tmp_path):
    src = sample_polygon(tmp_path)
    projected = tmp_path / "gk.cps"
    restored = tmp_path / "restored.cps"
    convert_cps3_file(src, projected, source_crs="EPSG:4326", target_crs="EPSG:28413")
    assert read_cps3(projected)[0].points[0][0] > 13_000_000
    convert_cps3_file(projected, restored, source_crs="EPSG:28413", target_crs="EPSG:4326")
    original = read_cps3(src)[0].points
    converted = read_cps3(restored)[0].points
    for (x,y,z), (cx,cy,cz) in zip(original, converted):
        assert cx == pytest.approx(x, abs=0.00002)
        assert cy == pytest.approx(y, abs=0.00002)
        assert cz == z


def test_northing_easting_order(tmp_path):
    source = sample_polygon(tmp_path)
    output = tmp_path / "yx.cps"
    convert_cps3_file(source, output,
                      source_crs="EPSG:4326", target_crs="EPSG:28413",
                      target_axis_order="yx")
    northing, easting, _ = read_cps3(output)[0].points[0]
    assert northing < 10_000_000 < easting
    lon,lat = CoordinateTransformer("EPSG:28413", "EPSG:4326",
                                    source_axis_order="yx").transform(northing,easting)
    assert lon == pytest.approx(72, abs=0.00002)
    assert lat == pytest.approx(60, abs=0.00002)


def test_import_projected_polygon(tmp_path):
    source = sample_polygon(tmp_path)
    output = tmp_path / "gk.cps"
    convert_cps3_file(source, output, source_crs="EPSG:4326", target_crs="EPSG:28413")
    item = load_polygon_layer(output, source_crs="EPSG:28413")
    assert item.features[0].name == "Тестовый участок"
    assert item.features[0].rings[0][0][0] == pytest.approx(72, abs=0.00002)
    assert item.features[0].rings[0][0][1] == pytest.approx(60, abs=0.00002)
    assert to_wgs84_polygons(output, "EPSG:28413")[0][1][0][0] == pytest.approx(72, abs=0.00002)


def test_wrong_crs_rejected(tmp_path):
    source = sample_polygon(tmp_path)
    output = tmp_path / "gk.cps"
    convert_cps3_file(source, output, source_crs="EPSG:4326", target_crs="EPSG:28413")
    with pytest.raises(CoordinateSystemError):
        load_polygon_layer(output)  # must explicitly declare GK source CRS


def test_grid_rejected(tmp_path):
    source = tmp_path / "grid.cps"
    source.write_text("@grid 100\n1 2 3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ZMAP"):
        read_cps3(source)


def test_source_file_not_overwritten(tmp_path):
    source = sample_polygon(tmp_path)
    with pytest.raises(ValueError, match="разными"):
        convert_cps3_file(source, source, source_crs="EPSG:4326", target_crs="EPSG:28413")
