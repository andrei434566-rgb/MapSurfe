# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os

from PyInstaller.utils.hooks import (
    collect_data_files, collect_delvewheel_libs_directory, copy_metadata, get_package_paths,
)

root = Path(SPECPATH).parent

# Native tools supplied by a host application must never satisfy application DLL
# dependencies. In particular, Poppler's ICU exports version-suffixed symbols;
# Qt 6 requires Windows' unsuffixed ICU API. Keep the Windows/system PATH intact.
def foreign_tool_path(value):
    path = str(value).replace("\\", "/").lower()
    return "/codex-runtimes/" in path and "/dependencies/native/" in path

os.environ["PATH"] = os.pathsep.join(
    entry for entry in os.environ.get("PATH", "").split(os.pathsep)
    if entry and not foreign_tool_path(entry)
)

qt_directory = Path(get_package_paths("PySide6")[1])
vc_runtime_names = ("VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "MSVCP140.dll",
                    "MSVCP140_1.dll", "MSVCP140_2.dll")
vc_runtime_sources = {name.lower(): qt_directory / name for name in vc_runtime_names}
resources = [
    "paleodem_2024.zip", "cities500.sqlite", "README.md", "THIRD_PARTY_NOTICES.md",
    "model/scotese2024.rot", "model/scotese2024_polygons.gpml",
    "model/SOURCE.md", "model/paleodem2024-source.json",
]
resources += [path.name for path in sorted(root.glob("*license*.txt"))]
resources += [path.name for path in sorted(root.glob("LICENSE*")) if path.is_file()]
datas = []
for relative in resources:
    source = root / relative
    if not source.is_file():
        raise FileNotFoundError(f"Required application resource is missing: {source}")
    datas.append((str(source), str(Path(relative).parent)))
datas.append((str(root / "packaging" / "licenses"), "licenses"))
datas += collect_data_files("pygplates")
datas, binaries = collect_delvewheel_libs_directory("pygplates", datas=datas)
binaries += [(str(source), ".") for source in vc_runtime_sources.values() if source.is_file()]
# The optional netCDF Blosc plugin asks for the unversioned zlib name. Reuse
# netCDF's own compatible zlib rather than a DLL found in an unrelated PATH.
netcdf_library_dir = Path(get_package_paths("netCDF4")[0]) / "netcdf4.libs"
zlib_sources = sorted(netcdf_library_dir.glob("zlib-*.dll"))
if len(zlib_sources) != 1:
    raise RuntimeError(f"Expected one netCDF zlib runtime in {netcdf_library_dir}")
binaries.append((str(zlib_sources[0]), "."))
for distribution in ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6",
                     "PyOpenGL", "numpy", "opencv-python", "netCDF4", "cftime",
                     "pygplates", "pyproj", "certifi", "packaging", "typing_extensions"):
    datas += copy_metadata(distribution)

a = Analysis(
    [str(root / "paleoatlas_qt.pyw")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["pygplates.pygplates", "OpenGL.platform.win32",
                   "OpenGL.arrays.numpymodule", "pyproj", "packaging", "packaging.version"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "matplotlib", "scipy",
              "pandas", "torch", "torchvision", "torchaudio", "tensorflow",
              "IPython", "jupyter", "notebook", "pytest", "ultralytics",
              "sympy", "numba", "sklearn", "PIL", "numpy.testing", "numpy.f2py",
              "numpy._core._multiarray_tests", "psutil", "charset_normalizer", "yaml"],
    noarchive=False,
    optimize=0,
)
# OpenGL's stock hook collects legacy GLUT/GLE DLLs, including 32-bit VC9 builds.
# MapSurfe renders inside Qt and uses only Windows' system OpenGL implementation.
def excluded_binary(entry):
    name = entry[0].replace("\\", "/").lower()
    return (name.startswith("opengl/dlls/")
            or foreign_tool_path(entry[1])
            or name.startswith(("api-ms-win-", "ext-ms-win-"))
            or name in ("ucrtbase.dll", "icuuc.dll", "icuin.dll", "icudt.dll"))

a.binaries = [entry for entry in a.binaries if not excluded_binary(entry)]
a.datas = [entry for entry in a.datas if not excluded_binary(entry)]
# Normalize the root runtime set even when Python itself ships an older MSVC
# redist. These Qt wheel copies are app-local; no administrator install is used.
a.binaries = [entry for entry in a.binaries
              if entry[0].lower() not in vc_runtime_sources and entry[0].lower() != "zlib.dll"]
a.binaries += [(name, str(source), "BINARY") for name, source in vc_runtime_sources.items()
               if source.is_file()]
a.binaries.append(("zlib.dll", str(zlib_sources[0]), "BINARY"))
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MapSurfe",
    debug=os.environ.get("MAPSURFE_DEBUG_BOOTLOADER") == "1",
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=os.environ.get("MAPSURFE_CONSOLE") == "1",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(root / "packaging" / "windows-version.txt"),
    uac_admin=False,
    uac_uiaccess=False,
)
