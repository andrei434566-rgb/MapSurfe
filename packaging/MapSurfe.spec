# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files, collect_delvewheel_libs_directory, copy_metadata,
)

root = Path(SPECPATH).parent
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
                   "OpenGL.arrays.numpymodule", "pyproj"],
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
def unused_opengl_dll(entry):
    return entry[0].replace("\\", "/").lower().startswith("opengl/dlls/")

a.binaries = [entry for entry in a.binaries if not unused_opengl_dll(entry)]
a.datas = [entry for entry in a.datas if not unused_opengl_dll(entry)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MapSurfe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(root / "packaging" / "windows-version.txt"),
    uac_admin=False,
    uac_uiaccess=False,
)
