"""Offline searchable city and settlement index built from GeoNames cities500."""
from __future__ import annotations

import re
import sqlite3
import zipfile
from pathlib import Path


_INSERT = """INSERT INTO places (
    rowid, name, ascii_name, aliases, country_code, latitude, longitude,
    population, feature_code
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""


def _build_index(archive_path: Path, database_path: Path) -> None:
    temporary = database_path.with_suffix(".building")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("""CREATE VIRTUAL TABLE places USING fts5(
            name, ascii_name, aliases,
            country_code UNINDEXED, latitude UNINDEXED, longitude UNINDEXED,
            population UNINDEXED, feature_code UNINDEXED,
            tokenize='unicode61 remove_diacritics 2', prefix='2 3 4'
        )""")
        with zipfile.ZipFile(archive_path) as archive:
            member = next(name for name in archive.namelist()
                          if name.lower().endswith("cities500.txt"))
            with archive.open(member) as source:
                batch = []
                for raw in source:
                    columns = raw.decode("utf-8").rstrip("\r\n").split("\t")
                    if len(columns) < 19 or not columns[1]:
                        continue
                    try:
                        place_id = int(columns[0])
                        latitude, longitude = float(columns[4]), float(columns[5])
                    except (TypeError, ValueError):
                        continue
                    batch.append((
                        place_id, columns[1], columns[2], columns[3], columns[8],
                        latitude, longitude, int(columns[14] or 0), columns[7],
                    ))
                    if len(batch) >= 4000:
                        connection.executemany(_INSERT, batch)
                        batch.clear()
                if batch:
                    connection.executemany(_INSERT, batch)
        connection.commit()
    finally:
        connection.close()
    temporary.replace(database_path)


class CityCatalog:
    """Small FTS index of GeoNames populated places, available without a server."""

    def __init__(self, directory: Path):
        self.database_path = directory / "cities500.sqlite"
        if not self.database_path.exists():
            source = directory / "cities500.zip"
            if not source.exists():
                raise FileNotFoundError(f"Нет офлайн-справочника городов: {source}")
            _build_index(source, self.database_path)
        self.connection = sqlite3.connect(
            f"file:{self.database_path.as_posix()}?mode=ro", uri=True
        )
        self.connection.execute("PRAGMA query_only=ON")
        self.count = self.connection.execute("SELECT count(*) FROM places").fetchone()[0]

    @staticmethod
    def _row(row):
        if not row:
            return None
        return (str(row[0]), str(row[1] or ""), float(row[2]), float(row[3]), int(row[4]))

    def by_id(self, place_id: int, display_name: str | None = None):
        row = self.connection.execute(
            "SELECT name, country_code, latitude, longitude, rowid "
            "FROM places WHERE rowid=?", (int(place_id),)
        ).fetchone()
        if row and display_name:
            row = (display_name, *row[1:])
        return self._row(row)

    def search(self, text: str, limit: int = 24):
        tokens = re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)[:8]
        if not tokens:
            return []
        query = " AND ".join(f'"{token}"*' for token in tokens)
        rows = self.connection.execute("""SELECT name, country_code, latitude,
                longitude, rowid, aliases FROM places WHERE places MATCH ?
                ORDER BY CASE feature_code WHEN 'PPLC' THEN 0
                    WHEN 'PPLA' THEN 1 WHEN 'PPLA2' THEN 2 ELSE 3 END,
                    CAST(population AS INTEGER) DESC, name COLLATE NOCASE
                LIMIT ?""", (query, max(1, min(int(limit), 100)))).fetchall()
        requested = " ".join(tokens)
        results = []
        for row in rows:
            name, country, latitude, longitude, place_id, aliases = row
            alternatives = [value.strip() for value in str(aliases or "").split(",")
                            if value.strip()]
            display_name = next((value for value in alternatives
                                 if value.casefold() == requested), None)
            if display_name is None:
                display_name = next((value for value in alternatives
                                     if value.casefold().startswith(requested)), name)
            results.append((str(display_name), str(country or ""), float(latitude),
                            float(longitude), int(place_id)))
        return results

    def close(self):
        self.connection.close()
