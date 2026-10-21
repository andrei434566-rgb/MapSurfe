"""Build a self-contained Windows x64 MapSurfe.exe with PyInstaller.

Run with the pinned requirements-windows-lock.txt and requirements-build.txt.
No personal sessions, generated caches, or validation files are bundled.
"""
from __future__ import annotations

import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
RUNTIME_DISTRIBUTIONS = (
    "PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6",
    "PyOpenGL", "numpy", "opencv-python", "netCDF4", "cftime", "pygplates",
    "pyproj", "certifi", "packaging", "typing_extensions",
)
BUILD_DISTRIBUTIONS = (
    "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes",
)
LICENSE_PATTERN = re.compile(r"(?:^|[/_-])(license|licence|copying|notice|copyright)", re.I)


def collect_licenses() -> None:
    """Preserve installed wheel notices and metadata alongside extra license texts."""
    target = ROOT / "packaging" / "licenses"
    target.mkdir(parents=True, exist_ok=True)
    index = []
    for name in RUNTIME_DISTRIBUTIONS + BUILD_DISTRIBUTIONS:
        distribution = metadata.distribution(name)
        package_dir = target / name
        package_dir.mkdir(exist_ok=True)
        copied = []
        for member in distribution.files or ():
            relative = Path(str(member))
            if (".." in relative.parts or relative.suffix in (".py", ".pyc", ".pyd")
                    or not LICENSE_PATTERN.search(relative.as_posix())):
                continue
            source = Path(distribution.locate_file(member))
            if not source.is_file():
                continue
            destination = package_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(relative.as_posix())
        package_metadata = distribution.read_text("METADATA") or ""
        (package_dir / "METADATA.txt").write_text(package_metadata, encoding="utf-8")
        index.append({
            "name": name, "version": distribution.version,
            "license_expression": distribution.metadata.get("License-Expression"),
            "license": distribution.metadata.get("License"),
            "project_urls": distribution.metadata.get_all("Project-URL", []),
            "bundled_license_files": copied,
            "build_tool": name in BUILD_DISTRIBUTIONS,
        })
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise FileNotFoundError(f"Python license not found: {python_license}")
    shutil.copy2(python_license, target / "Python-LICENSE.txt")
    (target / "DEPENDENCIES.json").write_text(json.dumps({
        "python": platform.python_version(), "architecture": platform.machine(),
        "distributions": index,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "README.txt").write_text(
        "MapSurfe dependency licenses\n\n"
        "DEPENDENCIES.json records exact package versions and upstream metadata.\n"
        "Each package directory preserves its installed notices and METADATA.\n"
        "The upstream/ directory contains additional upstream license texts,\n"
        "including the Qt/PySide licensing alternatives and PyOpenGL notices.\n"
        "pygplates is GPL version 2 only; its complete COPYING is preserved.\n"
        "PyInstaller is a build tool with a bootloader distribution exception.\n"
        "Dataset attribution is in the root *license.txt files and model/SOURCE.md.\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT.parent / "MapSurfe-release")
    parser.add_argument("--licenses-only", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.architecture()[0] != "64bit":
        parser.error("Build this release using 64-bit Python on Windows.")
    collect_licenses()
    if args.licenses_only:
        return 0
    args.dist_dir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--distpath", str(args.dist_dir.resolve()),
               "--workpath", str(ROOT / ".build" / "windows"),
               str(ROOT / "packaging" / "MapSurfe.spec")]
    build_environment = os.environ.copy()
    build_environment["PATH"] = os.pathsep.join(
        entry for entry in build_environment.get("PATH", "").split(os.pathsep)
        if entry and not (
            "/codex-runtimes/" in entry.replace("\\", "/").lower()
            and "/dependencies/native/" in entry.replace("\\", "/").lower()
        )
    )
    subprocess.run(command, cwd=ROOT, env=build_environment, check=True)
    executable = args.dist_dir / "MapSurfe.exe"
    print(f"Built {executable.resolve()} ({executable.stat().st_size:,} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
