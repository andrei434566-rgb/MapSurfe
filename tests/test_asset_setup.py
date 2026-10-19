from pathlib import Path
import zipfile

from tools.prepare_assets import _target_for_member, assets_ready, extract_data


def test_detect_wrapped_release_paths():
    assert _target_for_member("foo/MapSurfe/model/scotese.rot") == Path("model/scotese.rot")
    assert _target_for_member("foo/paleoatlas_rasters/atlas_750.jpg") == Path("paleoatlas_rasters/atlas_750.jpg")
    assert _target_for_member("foo/cities500.zip") == Path("cities500.zip")
    assert _target_for_member("foo/paleodem_01deg.zip") == Path("paleodem_01deg.zip")


def test_refuse_non_data_paths():
    assert _target_for_member("foo/paleoatlas_qt.pyw") is None
    assert _target_for_member("foo/model/../paleoatlas_qt.pyw") is None


def test_extract_whitelisted_only_and_preserve_existing(tmp_path):
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("MapSurfe/model/scotese.rot", "rotation")
        z.writestr("MapSurfe/paleoatlas_qt.pyw", "MALICIOUS CODE")
        z.writestr("MapSurfe/cities500.zip", "cities")
    target = tmp_path / "app"
    target.mkdir()
    (target / "cities500.zip").write_text("saved")
    count = extract_data(archive, target)
    assert count == 1
    assert (target / "model/scotese.rot").read_text() == "rotation"
    assert (target / "cities500.zip").read_text() == "saved"
    assert not (target / "paleoatlas_qt.pyw").exists()
    assert not assets_ready(target)
