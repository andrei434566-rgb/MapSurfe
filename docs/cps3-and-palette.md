# CPS-3 → Gauss–Krüger and vivid PaleoDEM palette

## Scope

This update handles **CPS-3 ASCII XY polygon contours** with named records (`->NAME`),
not regular CPS-3/ZMAP grids. It adds CRS transformations using `pyproj` and changes
the *display palette* for PaleoDEM. It does **not** change heights, shorelines or
the tectonic reconstruction model. The main UI file `paleoatlas_qt.pyw` is not
currently in GitHub, so the import dialog must be integrated separately.

## Setup

```shell
python -m pip install -r requirements-geo.txt
```

## Export projected CPS-3 (WGS84 to Gauss–Krüger)

```shell
python cps3_convert.py contours.cps contours_gk.cps --from-crs EPSG:4326 --to-crs EPSG:28413
```

## Import projected CPS-3 into the paleo-globe

```python
from geo_layers import load_polygon_layer
layer = load_polygon_layer("contours_gk.cps", source_crs="EPSG:28413")
```

In many Russian geological files the first column X is **northing** and the
second column Y is **easting**: add `--from-order yx` to the converter, or
`axis_order="yx"` when loading a layer.

For example, `EPSG:28413` is **Pulkovo 1942 / Gauss–Krüger 6° zone 13**.
Do not assume this is your project's zone. `EPSG:20013` refers to Pulkovo
1995 / GK 6° zone 13. Other datums, 3° zones, MSK and GSK-2011 require
their real documented CRS definitions. PROJ transformation accuracy depends
on available grid shifts.

CPS-3 output is written to a **new** file; the input is never overwritten.
An optional third Z attribute is retained unchanged (no vertical conversion).

## Vivid atlas palette

`paleo_visual_data.py` now uses deeper cobalt-blue basins, cyan shelves,
turquoise shallows, bright greens and sand-ochre highlands. On first load a
new `paleodem_color_*_vivid_v1` cache is computed from the PaleoDEM grids.
The color scheme is inspired by the user's geological reference illustration,
but is not a byte-for-byte copy.

## Tests

```shell
python -m pip install pytest
python -m pytest -q tests/test_cps3_coordinates.py
```

## Important limits

The code requires an explicitly supplied source CRS for projected data and
does not attempt to infer it from numerical coordinate ranges. Multi-plate
tectonic reconstruction, polygon hole semantics and UI CRS selection remain
separate follow-up tasks.
