"""One-time local compilation of PaleoDEM height grids into presentation tiles."""
from pathlib import Path
from time import perf_counter

import cv2

from paleo_model import PaleoModel
from paleo_visual_data import PaleoVisualData


def main():
    directory = Path(__file__).resolve().parent
    model = PaleoModel(directory / "model")
    atlas = PaleoVisualData(directory, model.rasters)
    atlas.color_cache.mkdir(exist_ok=True)
    started = perf_counter()
    for number, age in enumerate(atlas.ages, 1):
        target = atlas.color_cache / f"{age:g}.jpg"
        if target.exists():
            continue
        image = atlas._dem_image(age)
        ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
                                   [cv2.IMWRITE_JPEG_QUALITY, 96])
        if not ok:
            raise OSError(f"Не удалось сохранить карту {age:g} млн лет")
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(encoded.tobytes())
        temporary.replace(target)
        if number % 10 == 0 or number == len(atlas.ages):
            print(f"{number}/{len(atlas.ages)} · {perf_counter()-started:.1f} с", flush=True)


if __name__ == "__main__":
    main()
