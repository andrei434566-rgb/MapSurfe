"""Measure visible Qt/OpenGL animation at the demanding Cretaceous zoom."""
import importlib.machinery
import json
import sys
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

source = Path(__file__).with_name("paleoatlas_qt.pyw")
session = source.with_name("paleosloy_session.json")
session_snapshot = session.read_bytes() if session.exists() else None
module = importlib.machinery.SourceFileLoader("paleoatlas_qt", str(source)).load_module()
format = QSurfaceFormat()
format.setVersion(3, 3)
format.setProfile(QSurfaceFormat.CoreProfile)
QSurfaceFormat.setDefaultFormat(format)
app = QApplication([])
app.setStyleSheet(module.STYLE)
window = module.AtlasWindow()
window.showMaximized()
requested_age = next((float(arg.split("=", 1)[1]) for arg in sys.argv if arg.startswith("--age=")), 143.0)
window.set_age(requested_age)
window.globe.zoom = next((float(arg.split("=", 1)[1]) for arg in sys.argv if arg.startswith("--zoom=")), 2.66)
window.globe.camera_lon, window.globe.camera_lat = window.city_at(window.city)
static = "--static" in sys.argv
if not static:
    window.toggle_spin()
    window.toggle_play()
fps = []
window.globe.fps_changed.connect(fps.append)
started = perf_counter()


def snapshot():
    image = app.primaryScreen().grabWindow(int(window.winId()))
    image.save(str(source.with_name("gpu_preview_143.png")))


def done():
    print(json.dumps({"seconds": round(perf_counter()-started, 2),
                      "fps_samples": [round(value, 1) for value in fps],
                      "age": window.age, "zoom": window.globe.zoom}))
    window.timer.stop()
    window.globe.close_data()
    app.quit()


QTimer.singleShot(1800, snapshot)
QTimer.singleShot(2500 if static else 8500, done)
app.exec()
if session_snapshot is not None:
    session.write_bytes(session_snapshot)
