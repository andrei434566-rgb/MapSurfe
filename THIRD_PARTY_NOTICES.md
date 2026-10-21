# Third-party software and data

MapSurfe 1.1.0 is distributed with source code and its Windows build recipe in this repository. The application code is licensed under GNU GPL version 2. Data sets and third-party components retain their own copyrights and licenses.

The Windows executable embeds the applicable package notices collected from its build environment under `licenses/`. The build script regenerates that directory; the executable does not include personal sessions, imported user polygons or authentication information.

## Scientific data

- PALEOMAP PaleoDEM 2024 and its matching plate model: CC BY 4.0. Authors, DOI, original filenames and modifications are recorded in `paleodem2024-license.txt` and `model/SOURCE.md`.
- GeoNames cities500, data downloaded 2026-10-11: CC BY 4.0. See `geonames-license.txt`.
- Legacy PALEOMAP/PaleoDEM notices are preserved for source installations using the older fallback data. Those older maps and generated color caches are not required by the current standalone executable.

## Runtime libraries and upstream sources

Exact versions used for the Windows executable are recorded in `requirements-windows-lock.txt` and the generated build manifest.

| Component | License information | Upstream source |
| --- | --- | --- |
| Python | PSF license and included third-party notices | https://www.python.org/downloads/source/ |
| PySide6 / Qt / Shiboken | Qt's published open-source license options; individual modules retain their notices | https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://code.qt.io/cgit/qt/qtbase.git/ |
| PyGPlates 1.0.0 | GNU GPL version 2 only; see its bundled COPYING | https://github.com/GPlates/GPlates |
| NumPy | BSD and bundled dependency notices | https://github.com/numpy/numpy |
| OpenCV | Apache 2.0 and bundled third-party notices | https://github.com/opencv/opencv and https://github.com/opencv/opencv-python |
| PyOpenGL | BSD-style notices | https://github.com/mcfletch/pyopengl |
| netCDF4-Python / cftime | MIT and bundled native dependency notices | https://github.com/Unidata/netcdf4-python and https://github.com/Unidata/cftime |
| PyProj / PROJ | MIT-style notices and native dependency notices | https://github.com/pyproj4/pyproj and https://github.com/OSGeo/PROJ |
| PyInstaller | GPL with its bootloader distribution exception | https://github.com/pyinstaller/pyinstaller |

PyGPlates also contains native dependencies, including GDAL, PROJ, HDF5, Qt 5 and their dependent libraries. Their original accompanying notices are retained when collected into the executable. Qt 5 components used internally by PyGPlates are distinct from the Qt 6 application interface.

This software and the scientific reconstructions are supplied without warranty. The interpolation used for intermediate ages is a MapSurfe visualization, not an independently published geological reconstruction.
