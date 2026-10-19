"""Download and extract only the large scientific data assets from MapSurfe v1.0.0.

The repository stores application sources. The release archive holds bulky local
model/raster/geonames data. This utility NEVER replaces existing source files or
nonempty local assets. It checks the official SHA-256 before extraction.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
RELEASE_URL = (
    "https://github.com/andrei434566-rgb/MapSurfe/releases/download/"
    "v1.0.0/MapSurfe-source.zip"
)
RELEASE_SHA256 = "992da00315eaa3cbbde7f27921c4e98c1d70495673cbc3dec33d466ea202e779"
DOWNLOAD_DIR = ROOT / ".downloads"
DOWNLOAD_FILE = DOWNLOAD_DIR / "MapSurfe-source.zip"
CHUNK = 1024 * 1024


def assets_ready(base: Path = ROOT) -> bool:
    model = base / "model"
    raster = base / "paleoatlas_rasters"
    if not (model / "scotese.rot").is_file() or not (model / "scotese_polygons.gpml").is_file():
        return False
    if not (base / "cities500.zip").is_file():
        return False
    if not any((base / n).is_file() for n in ("paleodem_01deg.zip", "paleodem_02deg.zip")):
        return False
    ages = set()
    if raster.is_dir():
        for filename in raster.glob("*.jpg"):
            try:
                ages.add(int(filename.stem.rsplit("_", 1)[-1]))
            except ValueError:
                continue
    return 0 in ages and 750 in ages


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as inp:
        while chunk := inp.read(8 * CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def download_release(destination: Path = DOWNLOAD_FILE) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".zip.part")
    if destination.exists():
        print("Архив уже скачан, проверяю SHA-256...", flush=True)
        if sha256_file(destination) != RELEASE_SHA256:
            raise RuntimeError(
                f"Файл {destination} не прошёл проверку SHA-256. "
                "Удалите повреждённую копию, прежде чем повторять установку."
            )
        return destination

    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "MapSurfe-Windows-Installer/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    print("Скачивание официального релиза (примерно 1.13 ГБ). "
          "Можно прервать и возобновить.", flush=True)
    try:
        with urllib.request.urlopen(urllib.request.Request(RELEASE_URL, headers=headers), timeout=90) as reply:
            code = reply.status
            if offset and code != 206:
                print("Сервер не поддержал докачку, начинаю сначала...", flush=True)
                offset = 0
            total = reply.headers.get("Content-Length")
            full_size = (int(total) + offset) if total and total.isdigit() else None
            with partial.open("ab" if offset else "wb") as outfile:
                received = offset
                milestone = received // (25 * CHUNK)
                while chunk := reply.read(CHUNK):
                    outfile.write(chunk)
                    received += len(chunk)
                    new_milestone = received // (25 * CHUNK)
                    if new_milestone > milestone:
                        milestone = new_milestone
                        msg = f"  {received / (1024**3):.2f} ГБ"
                        if full_size:
                            msg += f" / {full_size / (1024**3):.2f} ГБ"
                        print(msg, flush=True)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(
            "Не удалось скачать архив с GitHub. Скачайте вручную: "
            f"{RELEASE_URL}\n"
            f"Положите MapSurfe-source.zip в {ROOT} и запустите установку снова."
        ) from exc

    print("Проверка контрольной суммы...", flush=True)
    if sha256_file(partial) != RELEASE_SHA256:
        raise RuntimeError("SHA-256 скачанного файла не совпадает. Архив повреждён. "
                           f"Удалите {partial} и повторите.")
    partial.replace(destination)
    return destination


def _target_for_member(name: str) -> Path | None:
    """Whitelist data paths even if the release archive has a wrapper directory."""
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if ".." in parts or not parts:
        return None
    for marker in ("model", "paleoatlas_rasters"):
        if marker in parts:
            index = parts.index(marker)
            rel = parts[index:]
            if len(rel) > 1 and all(s not in (".", "..") for s in rel):
                if marker == "paleoatlas_rasters" and not rel[-1].lower().endswith(".jpg"):
                    return None
                return Path(*rel)
    if parts[-1] in {"cities500.zip", "paleodem_01deg.zip", "paleodem_02deg.zip"}:
        return Path(parts[-1])
    return None


def extract_data(archive: Path, base: Path = ROOT) -> int:
    extracted = 0
    print(f"Распаковка геоданных из {archive.name}...", flush=True)
    with zipfile.ZipFile(archive) as zf:
        entries: dict[Path, zipfile.ZipInfo] = {}
        for member in zf.infolist():
            if member.is_dir():
                continue
            relpath = _target_for_member(member.filename)
            if relpath is None:
                continue
            if member.file_size > 3 * 1024**3:
                raise RuntimeError(f"Слишком большой элемент архива: {member.filename}")
            if relpath in entries:
                raise RuntimeError(f"Повторяющийся путь данных в архиве: {relpath}")
            entries[relpath] = member
        if not entries:
            raise RuntimeError("В архиве не найдены папки model / paleoatlas_rasters и пакеты данных.")
        for relpath, member in entries.items():
            target = base / relpath
            if target.exists():
                continue  # never overwrite existing models, assets or personal files
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".installing")
            try:
                with zf.open(member) as source, temp.open("wb") as dest:
                    shutil.copyfileobj(source, dest, 8 * CHUNK)
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
            extracted += 1
            if extracted % 30 == 0:
                print(f"  Распаковано {extracted} файлов", flush=True)
    return extracted


def main() -> int:
    parser = argparse.ArgumentParser(description="Подготовка локальных карт MapSurfe")
    parser.add_argument("--archive", type=Path, help="Путь к скачанному MapSurfe-source.zip")
    args = parser.parse_args()
    if assets_ready():
        print("Карты и тектоническая модель на месте. Скачивание не требуется.")
        return 0

    if args.archive:
        archive = args.archive.expanduser().resolve()
    elif (ROOT / "MapSurfe-source.zip").is_file():
        archive = ROOT / "MapSurfe-source.zip"
    elif (Path.home() / "Downloads" / "MapSurfe-source.zip").is_file():
        archive = Path.home() / "Downloads" / "MapSurfe-source.zip"
    else:
        archive = download_release()

    if sha256_file(archive) != RELEASE_SHA256:
        raise RuntimeError(f"Архив {archive} не прошёл проверку SHA-256.")
    count = extract_data(archive)
    if not assets_ready():
        raise RuntimeError(
            "Распаковка закончилась, но отсутствуют необходимые карты или модель. "
            "Проверьте структуру архива и содержимое каталога model."
        )
    print(f"Геологические данные готовы ({count} новых файлов).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"\nОШИБКА ПОДГОТОВКИ ДАННЫХ: {exc}", file=sys.stderr)
        sys.exit(1)
