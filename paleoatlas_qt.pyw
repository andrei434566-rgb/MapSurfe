"""Native Windows paleogeographic atlas with an OpenGL globe."""
from __future__ import annotations

import ctypes
import json
import math
from pathlib import Path
import sys
from time import perf_counter
import traceback

from runtime_paths import (
    APP_NAME, APP_VERSION, error_log_path, is_frozen, resource_dir, session_path,
)


def _unhandled_exception(exc_type, exception, tb):
    """Report startup failures even when a bundled native import fails."""
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exception, tb)
        return
    detail = "".join(traceback.format_exception(exc_type, exception, tb))
    try:
        log = error_log_path()
        log.write_text(f"{APP_NAME} {APP_VERSION}\n\n{detail}", encoding="utf-8")
        location = f"Подробности записаны в файл:\n{log}"
    except OSError:
        location = "Не удалось сохранить журнал ошибки в папку приложения."
    if is_frozen():
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                f"Не удалось запустить или продолжить работу {APP_NAME}.\n\n"
                f"{exception}\n\n{location}",
                f"{APP_NAME} — ошибка",
                0x10,
            )
        except (AttributeError, OSError):
            pass
    else:
        sys.__excepthook__(exc_type, exception, tb)


if __name__ == "__main__":
    # Install before Qt, GDAL, and netCDF imports, so missing DLLs get a log too.
    sys.excepthook = _unhandled_exception

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QSurfaceFormat
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from atlas_features import AtlasFeature, FEATURES
from city_catalog import CityCatalog
from geo_layers import is_cps3_lines_file, load_polygon_layer
from paleo_coordinates import CoordinateTransformer, gauss_kruger_epsg
from cps3_convert import convert_cps3_file
from paleo_globe import DEFAULT_SHARPNESS, MAX_SHARPNESS, MAX_ZOOM, GlobeWidget
from paleo_model import MAX_AGE, PaleoModel
from paleogeography import UNITS, active_units, age_story
from paleo_visual_data import PaleoVisualData, relief_legend


BG = "#061322"
PANEL = "#0c2130"
SOFT = "#143347"
FG = "#f4f8ee"
MUTED = "#9ab9c5"
CYAN = "#62dbed"
GOLD = "#ffdc6d"

CITIES = [
    ("Тюмень", "Россия", 57.15, 65.53),
    ("Москва", "Россия", 55.75, 37.62),
    ("Екатеринбург", "Россия", 56.84, 60.61),
    ("Санкт-Петербург", "Россия", 59.94, 30.32),
    ("Новосибирск", "Россия", 55.01, 82.93),
    ("Владивосток", "Россия", 43.12, 131.89),
    ("Лондон", "Великобритания", 51.51, -0.12),
    ("Париж", "Франция", 48.86, 2.35),
    ("Токио", "Япония", 35.68, 139.69),
    ("Каир", "Египет", 30.04, 31.24),
    ("Кейптаун", "ЮАР", -33.92, 18.42),
    ("Дели", "Индия", 28.61, 77.21),
    ("Дубай", "ОАЭ", 25.20, 55.27),
    ("Сидней", "Австралия", -33.87, 151.21),
    ("Нью-Йорк", "США", 40.71, -74.01),
    ("Денвер", "США", 39.74, -104.99),
    ("Ванкувер", "Канада", 49.28, -123.12),
    ("Рио-де-Жанейро", "Бразилия", -22.91, -43.17),
    ("Буэнос-Айрес", "Аргентина", -34.60, -58.38),
]
PERIODS = [
    (2, "Четвертичный", "КАЙНОЗОЙ"), (23, "Неоген", "КАЙНОЗОЙ"),
    (66, "Палеоген", "КАЙНОЗОЙ"), (145, "Мел", "МЕЗОЗОЙ"),
    (201, "Юра", "МЕЗОЗОЙ"), (252, "Триас", "МЕЗОЗОЙ"),
    (299, "Пермь", "ПАЛЕОЗОЙ"), (359, "Карбон", "ПАЛЕОЗОЙ"),
    (419, "Девон", "ПАЛЕОЗОЙ"), (444, "Силур", "ПАЛЕОЗОЙ"),
    (485, "Ордовик", "ПАЛЕОЗОЙ"), (539, "Кембрий", "ПАЛЕОЗОЙ"),
    (635, "Эдиакарий", "ПРОТЕРОЗОЙ"),
    (720, "Криогений", "ПРОТЕРОЗОЙ"),
    (750, "Неопротерозой", "ПРОТЕРОЗОЙ"),
]
EPOCH_STOPS = (
    (750, "Родиния", "rodinia", None,
     "Суперконтинент Родиния и окружающий её предполагаемый океан Мировия."),
    (600, "Сборка Гондваны", "gondwana", None,
     "Южные континентальные блоки сближаются при сборке Гондваны; Лаврентия, Балтика и Сибирь остаются отдельными."),
    (360, "Сборка Пангеи", None, "Урал",
     "Материки сближаются, закрывая океанические бассейны."),
    (280, "Пангея", "pangaea", None,
     "Пангея окружена океаном Панталасса и бассейнами Тетиса."),
    (120, "Индия движется на север", None, "Индостан",
     "Индийский блок быстро смещается к Евразии; впереди столкновение и рост Гималаев."),
    (0, "Современная Земля", None, None,
     "Континенты близки к современным, хотя движение плит продолжается."),
)


def wrap(lon):
    return (lon + 180) % 360 - 180


def button(text, callback, primary=False):
    result = QPushButton(text)
    result.setProperty("primary", primary)
    result.clicked.connect(callback)
    return result


def label(text, color=FG, size=10, bold=False):
    result = QLabel(text)
    result.setStyleSheet(f"color:{color};font-size:{size}pt;"
                         + ("font-weight:700;" if bold else ""))
    result.setWordWrap(True)
    return result


class CitySearchDialog(QDialog):
    def __init__(self, catalog, title, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.place = None
        self.setWindowTitle(title)
        self.setMinimumSize(500, 500)
        layout = QVBoxLayout(self)
        layout.addWidget(label("ПОИСК ПО ВСЕМУ МИРУ", CYAN, 9, True))
        layout.addWidget(label("Введите название города или населённого пункта",
                              FG, 14, True))
        self.query = QLineEdit()
        self.query.setPlaceholderText("Например: Тюмень, Moscow, São Paulo…")
        self.query.textChanged.connect(self.search)
        layout.addWidget(self.query)
        self.status = label("", MUTED, 9)
        layout.addWidget(self.status)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda _item: self.accept_selected())
        layout.addWidget(self.results, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Отмена", self.reject))
        self.accept_button = button("Выбрать место", self.accept_selected, True)
        self.accept_button.setEnabled(False)
        buttons.addWidget(self.accept_button)
        layout.addLayout(buttons)
        self.query.setFocus()

    def search(self, text):
        self.results.clear()
        if len(text.strip()) < 2:
            self.status.setText("GeoNames · населённые пункты мира · CC BY 4.0")
            self.accept_button.setEnabled(False)
            return
        places = self.catalog.search(text)
        for place in places:
            name, country, _lat, _lon, place_id = place
            item = QListWidgetItem(f"{name}  ·  {country or 'без страны'}")
            item.setData(Qt.UserRole, place_id)
            item.setData(Qt.UserRole + 1, name)
            self.results.addItem(item)
        if places:
            self.results.setCurrentRow(0)
        count = f"{self.catalog.count:,}".replace(",", " ")
        self.status.setText(
            f"Показано до {len(places)} совпадений · в справочнике {count} мест"
            if places else "Совпадений нет — попробуйте другое написание"
        )
        self.accept_button.setEnabled(bool(places))

    def accept_selected(self):
        item = self.results.currentItem()
        if item is None:
            return
        self.place = self.catalog.by_id(item.data(Qt.UserRole),
                                        item.data(Qt.UserRole + 1))
        if self.place:
            self.accept()


class CPS3CoordinateDialog(QDialog):
    """Explicitly select CRS and axis order; never guess a survey projection."""
    def __init__(self, parent=None, *, exporting=False, source_path=None,
                 lines_export=False):
        super().__init__(parent)
        self.exporting = exporting
        self.setWindowTitle("Координаты CPS-3 / Гаусс — Крюгер")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.addWidget(label("СИСТЕМА КООРДИНАТ", CYAN, 9, True))
        if source_path is not None:
            layout.addWidget(label(Path(source_path).name, FG, 11, True))
        if lines_export:
            layout.addWidget(label(
                "Распознан текстовый экспорт CPS-3 LINES. Обозначение «ПНО-14» "
                "не задаёт EPSG и не означает зону 14. В заголовке файла нет "
                "параметров географической привязки: укажите исходную СК "
                "и порядок колонок по данным проекта.", GOLD, 9))
        layout.addWidget(label(
            "Выберите подтверждённую исходную СК. Нельзя надёжно определять "
            "СК и зону только по числам координат.", MUTED, 9))
        form = QFormLayout()
        self.crs_form = form
        self.source_mode = QComboBox()
        self.source_mode.addItem("EPSG / WKT вручную", None)
        self.source_mode.addItem("Гаусс — Крюгер 6° · СК-42", "SK-42")
        self.source_mode.addItem("Гаусс — Крюгер 6° · СК-95", "SK-95")
        form.addRow("Как задать исходную СК", self.source_mode)
        self.source = QComboBox()
        self.source.setEditable(True)
        self.source.addItems([
            "EPSG:4326", "EPSG:28413", "EPSG:28412", "EPSG:28414",
            "EPSG:20013",
        ])
        self.source.setCurrentText("")
        self.source.lineEdit().setPlaceholderText("Укажите подтверждённый EPSG или WKT")
        form.addRow("Исходная СК (EPSG / WKT)", self.source)
        self.zone = QComboBox()
        self.zone.addItem("Выберите свою зону", None)
        for zone in range(2, 32):
            self.zone.addItem(str(zone), zone)
        form.addRow("Номер шестиградусной зоны", self.zone)
        self.gk_source_label = label("Выберите номер зоны", FG, 9)
        form.addRow("Исходная СК", self.gk_source_label)
        self.axis = QComboBox()
        self.axis.addItem("Выберите порядок колонок", None)
        self.axis.addItem("1-я колонка — восток, 2-я — север (XY)", "xy")
        self.axis.addItem("1-я колонка — север, 2-я — восток (YX)", "yx")
        form.addRow("Порядок координат", self.axis)
        if exporting:
            self.target = QComboBox()
            self.target.setEditable(True)
            self.target.addItems(["EPSG:28413", "EPSG:28412", "EPSG:28414", "EPSG:20013", "EPSG:4326"])
            form.addRow("Целевая СК (EPSG)", self.target)
            self.target_axis = QComboBox()
            self.target_axis.addItem("X — восток, Y — север (XY)", "xy")
            self.target_axis.addItem("X — север, Y — восток (YX)", "yx")
            form.addRow("Порядок на выходе", self.target_axis)
        else:
            self.target = None
            self.target_axis = None
            form.addRow("На глобусе", label("WGS84 / EPSG:4326", FG, 9))
        layout.addLayout(form)
        layout.addWidget(label(
            "Готовые режимы ГК 6° рассчитаны на восточную координату с номером зоны. "
            "Для записи без номера зоны, трёхградусной зоны, МСК или другой СК "
            "укажите точный EPSG / WKT вручную. Порядок колонок выберите отдельно.", GOLD, 9))
        self.source_mode.currentIndexChanged.connect(self._source_mode_changed)
        self.zone.currentIndexChanged.connect(self._source_mode_changed)
        self._source_mode_changed()
        controls = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        controls.accepted.connect(self.validate_and_accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def _source_mode_changed(self, _index=None):
        manual = self.source_mode.currentData() is None
        self.crs_form.setRowVisible(self.source, manual)
        self.crs_form.setRowVisible(self.zone, not manual)
        self.crs_form.setRowVisible(self.gk_source_label, not manual)
        if not manual:
            if self.zone.currentData() is None:
                self.gk_source_label.setText("Выберите номер зоны")
            else:
                try:
                    self.gk_source_label.setText(self.crs)
                except ValueError as exc:
                    self.gk_source_label.setText(str(exc))

    def validate_and_accept(self):
        try:
            CoordinateTransformer(self.crs,
                                  self.target.currentText().strip() if self.exporting else "EPSG:4326",
                                  source_axis_order=self.order,
                                  target_axis_order=self.target_axis.currentData() if self.exporting else "xy")
        except Exception as exc:
            QMessageBox.warning(self, "Неверная система координат", str(exc))
            return
        self.accept()

    @property
    def crs(self):
        datum = self.source_mode.currentData()
        if datum is not None:
            zone = self.zone.currentData()
            if zone is None:
                raise ValueError("Выберите подтверждённый номер шестиградусной зоны Гаусса — Крюгера.")
            return gauss_kruger_epsg(zone, datum)
        crs = self.source.currentText().strip()
        if not crs:
            raise ValueError("Укажите подтверждённую исходную СК (EPSG / WKT) или выберите режим Гаусса — Крюгера и зону.")
        return crs

    @property
    def order(self):
        order = self.axis.currentData()
        if order is None:
            raise ValueError("Выберите порядок колонок координат: восток / север или север / восток.")
        return order


class AtlasWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} · Земля сквозь время")
        self.resize(1380, 820)
        self.setMinimumSize(1040, 660)
        self.directory = resource_dir()
        self.city_catalog = CityCatalog(self.directory)
        self.model = PaleoModel(self.directory / "model")
        self.data = PaleoVisualData(self.directory, self.model.rasters)
        self.session_path = session_path()
        self.age = 140.0
        self.city = CITIES[0]
        self.compare_city = CITIES[1]
        self.reference_age = 0
        self.selected_features = {"Таймыр", "Урал", "Гималаи"}
        self.selected_paleo_units = set()
        self.custom_features = []
        self.layers = []
        self.layer_restore_errors = []
        self._ring_cache = {}
        self._paleo_context_signature = None
        self.playing = False
        self.spinning = False
        self.tracks = False
        self.speed = 7.0
        self._last_tick = perf_counter()
        self._last_labels = 0.0
        self._build_ui()
        self._restore_session()
        mode, younger, older, _ = self.data.frames(self.age)
        for published_age in {younger, older}:
            self.globe._decoded[(mode, published_age)] = self.data.texture(mode, published_age)
        self.set_age(self.age)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        if self.layer_restore_errors:
            QTimer.singleShot(0, self._show_layer_restore_errors)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        full = QVBoxLayout(root)
        full.setContentsMargins(18, 13, 18, 16)
        full.setSpacing(12)
        header = QHBoxLayout()
        title = label("◉  ПАЛЕОАТЛАС", CYAN, 20, True)
        header.addWidget(title)
        header.addWidget(label("Живая Земля · 0–750 млн лет", MUTED, 10))
        header.addStretch()
        header.addWidget(label("ЛОКАЛЬНО  ·  GPU", CYAN, 9, True))
        full.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.tabs = QTabWidget()
        self.tabs.setFixedWidth(326)
        self._make_places_tab()
        self._make_polygon_tab()
        self._make_labels_tab()
        self._make_epochs_tab()
        body.addWidget(self.tabs)
        right = QVBoxLayout()
        right.setSpacing(10)
        globe_card = QFrame()
        globe_card.setObjectName("card")
        globe_layout = QVBoxLayout(globe_card)
        globe_layout.setContentsMargins(13, 10, 13, 8)
        top = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(0)
        self.era_label = label("МЕЗОЗОЙ", CYAN, 9, True)
        self.period_label = label("Мел", FG, 23, True)
        self.period_label.setWordWrap(False)
        names.addWidget(self.era_label)
        names.addWidget(self.period_label)
        top.addLayout(names, 1)
        self.spin_button = button("⟳ Вращать", self.toggle_spin)
        top.addWidget(self.spin_button)
        top.addWidget(button("−", lambda: self.change_zoom(1/1.5)))
        self.zoom_label = label("100%", CYAN, 9, True)
        top.addWidget(self.zoom_label)
        top.addWidget(button("+", lambda: self.change_zoom(1.5)))
        globe_layout.addLayout(top)
        self.globe = GlobeWidget(self.data)
        self.globe.overlay = self.draw_overlay
        self.globe.camera_changed = self._camera_changed
        self.globe.zoom_changed = self._zoom_changed
        self.globe.fps_changed.connect(self._fps_changed)
        self.globe.show_error = self.show_error
        globe_layout.addWidget(self.globe, 1)
        hint = QHBoxLayout()
        hint.addWidget(label("Перетащи глобус  ·  колесо: масштаб  ·  слои слева", MUTED, 9))
        hint.addStretch()
        hint.addWidget(label("Чёткость", MUTED, 9))
        self.sharpness_slider = QSlider(Qt.Horizontal)
        self.sharpness_slider.setRange(0, MAX_SHARPNESS)
        self.sharpness_slider.setFixedWidth(132)
        self.sharpness_slider.setSingleStep(5)
        self.sharpness_slider.setPageStep(25)
        self.sharpness_slider.setValue(round(self.globe.sharpness * 100))
        self.sharpness_slider.setToolTip(
            "0% — мягкий рельеф, 100% — выраженные детали, 200% — максимальное усиление. "
            "Положение берегов и исходные высоты не меняются.")
        self.sharpness_slider.valueChanged.connect(self.change_sharpness)
        hint.addWidget(self.sharpness_slider)
        self.sharpness_label = label(f"{self.sharpness_slider.value()}%", CYAN, 9)
        self.sharpness_label.setMinimumWidth(40)
        hint.addWidget(self.sharpness_label)
        self.sharpness_compare = QPushButton("Сравнить")
        self.sharpness_compare.setToolTip("Удерживай, чтобы увидеть карту без усиления чёткости")
        self.sharpness_compare.pressed.connect(lambda: self.preview_sharpness(True))
        self.sharpness_compare.released.connect(lambda: self.preview_sharpness(False))
        hint.addWidget(self.sharpness_compare)
        self.fps_label = label("GPU", CYAN, 9, True)
        hint.addWidget(self.fps_label)
        globe_layout.addLayout(hint)
        right.addWidget(globe_card, 1)

        time_card = QFrame()
        time_card.setObjectName("card")
        tl = QVBoxLayout(time_card)
        tl.setContentsMargins(20, 12, 20, 12)
        time_row = QHBoxLayout()
        self.age_label = label("140", FG, 27, True)
        time_row.addWidget(self.age_label)
        time_row.addWidget(label("млн лет назад", MUTED, 10))
        self.source_label = label("", GOLD, 9)
        self.globe.frame_changed.connect(self.update_map_source)
        time_row.addWidget(self.source_label, 1)
        self.play_button = button("▶ Воспроизвести", self.toggle_play, True)
        time_row.addWidget(self.play_button)
        time_row.addWidget(button("− 1", lambda: self.set_age(round(self.age)-1)))
        time_row.addWidget(button("+ 1", lambda: self.set_age(round(self.age)+1)))
        tl.addLayout(time_row)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, MAX_AGE)
        self.slider.setInvertedAppearance(True)
        self.slider.valueChanged.connect(lambda v: self.set_age(float(v), slider=True))
        tl.addWidget(self.slider)
        ticks = QHBoxLayout()
        for tick in (750, 600, 450, 300, 150, 0):
            ticks.addWidget(label(str(tick), MUTED, 9))
            if tick:
                ticks.addStretch()
        tl.addLayout(ticks)

        paleo_context = QWidget()
        paleo_context_layout = QVBoxLayout(paleo_context)
        paleo_context_layout.setContentsMargins(0, 3, 0, 1)
        paleo_context_layout.setSpacing(2)
        self.paleo_context_heading = label("ДРЕВНЯЯ ГЕОГРАФИЯ", CYAN, 8, True)
        paleo_context_layout.addWidget(self.paleo_context_heading)
        self.paleo_context_text = label("", MUTED, 8)
        paleo_context_layout.addWidget(self.paleo_context_text)
        self.paleo_unit_rows = {}
        for group in ("Материки", "Океаны"):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            self.paleo_unit_rows[group] = row
            paleo_context_layout.addLayout(row)
        self.paleo_context_note = label(
            "Флажок ставит точку и центрирует глобус; наведи на название для пояснения. Точки примерные, это не границы.",
            MUTED, 7)
        paleo_context_layout.addWidget(self.paleo_context_note)
        tl.addWidget(paleo_context)

        legend = QHBoxLayout()
        legend.addWidget(label("ШКАЛА РЕЛЬЕФА", MUTED, 8, True))
        for name, color in relief_legend():
            legend.addWidget(label(f"<span style='color:{color};'>■</span> {name}", FG, 8))
        legend.addStretch()
        self.legend_holder = QWidget()
        self.legend_holder.setLayout(legend)
        tl.addWidget(self.legend_holder)
        self.legacy_legend = label("PaleoAtlas 2016: цветная иллюстрация без числовой шкалы высот", MUTED, 8)
        self.legacy_legend.hide()
        tl.addWidget(self.legacy_legend)
        right.addWidget(time_card)
        body.addLayout(right, 1)
        full.addLayout(body, 1)

    def _tab(self, name):
        outer = QWidget()
        self.tabs.addTab(outer, name)
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)
        return layout

    def _make_places_tab(self):
        layout = self._tab("Места")
        layout.addWidget(label("ОПОРНЫЕ ТОЧКИ", CYAN, 9, True))
        layout.addWidget(label("Путешествие города", FG, 16, True))
        layout.addWidget(label("Первый город", MUTED, 9))
        self.city_button = button(self.city_label(self.city), self.search_city)
        self.city_button.setToolTip("Нажмите, чтобы найти город в офлайн-справочнике GeoNames")
        layout.addWidget(self.city_button)
        layout.addWidget(label("Сравнить с", MUTED, 9))
        self.compare_button = button(self.city_label(self.compare_city),
                                     lambda: self.search_city(compare=True))
        self.compare_button.setToolTip("Нажмите, чтобы выбрать второй город для сравнения")
        layout.addWidget(self.compare_button)
        self.now_label = label("", MUTED, 9)
        self.then_label = label("", CYAN, 9)
        self.distance_label = label("", GOLD, 9)
        self.reference_label = label("", MUTED, 9)
        for item in (self.now_label, self.then_label, self.distance_label, self.reference_label):
            layout.addWidget(item)
        layout.addWidget(button("Закрепить эпоху для сравнения", self.pin_age))
        self.track_box = QCheckBox("Показать траектории")
        self.track_box.toggled.connect(self.toggle_tracks)
        layout.addWidget(self.track_box)
        layout.addWidget(button("Центрировать на городе", self.center_city))
        layout.addStretch()
        place_count = f"{self.city_catalog.count:,}".replace(",", " ")
        layout.addWidget(label("Древнее положение рассчитано по модели плит. "
                              f"Офлайн-справочник GeoNames: {place_count} мест · CC BY 4.0.",
                              MUTED, 8))

    def _make_polygon_tab(self):
        layout = self._tab("Полигоны")
        layout.addWidget(label("ЛИЦЕНЗИОННЫЕ УЧАСТКИ", CYAN, 9, True))
        layout.addWidget(label("Слои полигонов", FG, 16, True))
        layout.addWidget(label("CPS-3 XY / LINES (.shp) · GeoJSON · KML · Shapefile ZIP\nПроекционные координаты → WGS84 по указанной СК", MUTED, 9))
        layout.addWidget(button("＋ Добавить слой", self.add_layer, True))
        layout.addWidget(button("Проверить проект Isoline (.ipr)", self.inspect_isoline_project))
        layout.addWidget(button("⇄ Конвертировать CPS-3 в другую СК", self.convert_cps3))
        self.layer_list = QListWidget()
        self.layer_list.currentRowChanged.connect(self.layer_selected)
        layout.addWidget(self.layer_list, 1)
        self.layer_info = label("Слои не загружены", MUTED, 9)
        layout.addWidget(self.layer_info)
        layout.addWidget(label("Участок", MUTED, 9))
        self.parcel_box = QComboBox()
        self.parcel_box.currentIndexChanged.connect(lambda _: self.focus_layer())
        layout.addWidget(self.parcel_box)
        self.layer_visible = QCheckBox("Показывать выбранный слой")
        self.layer_visible.toggled.connect(self.change_layer_visibility)
        layout.addWidget(self.layer_visible)
        layout.addWidget(button("Найти участок на глобусе", self.focus_layer))
        layout.addWidget(label("Древний контур — перенос современной лицензии по плите её центра; для крупных участков нужна геологическая проверка.", GOLD, 9))

    def _make_labels_tab(self):
        layout = self._tab("Подписи")
        layout.addWidget(label("ГЕОГРАФИЧЕСКИЕ ОРИЕНТИРЫ", CYAN, 9, True))
        layout.addWidget(label("Настройка подписей", FG, 16, True))
        layout.addWidget(label("Таймыр, горные системы, острова и полуострова можно включать по отдельности.", MUTED, 9))
        self.feature_search = QLineEdit()
        self.feature_search.setPlaceholderText("Поиск подписи")
        self.feature_search.textChanged.connect(self.render_features)
        layout.addWidget(self.feature_search)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.feature_body = QWidget()
        self.feature_layout = QVBoxLayout(self.feature_body)
        self.feature_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.feature_body)
        layout.addWidget(scroll, 1)
        layout.addWidget(button("＋ Своя точка", self.add_custom_feature))
        layout.addWidget(label("Названия описывают современные ориентиры, а не возраст образования объектов.", MUTED, 9))
        self.render_features()

    def _make_epochs_tab(self):
        layout = self._tab("Эпохи")
        layout.addWidget(label("ЭТАПЫ ИСТОРИИ ЗЕМЛИ", CYAN, 9, True))
        layout.addWidget(label("Карты по эпохам", FG, 16, True))
        layout.addWidget(label(
            "Выбери эпоху, чтобы перейти к нужному моменту и посмотреть, "
            "какие материки и океаны существовали в это время.",
            MUTED, 9))
        self.epoch_context_label = label("", GOLD, 9, True)
        layout.addWidget(self.epoch_context_label)
        layout.addWidget(label("ОПОРНЫЕ ДАТЫ КАРТ", CYAN, 9, True))
        self.published_age_box = QComboBox()
        published_ages = set(self.data.ages)
        if not self.data.has_precambrian_dem:
            published_ages.update(self.data.old_ages)
        for age in sorted(published_ages, reverse=True):
            self.published_age_box.addItem(f"{age:g} млн лет", float(age))
        self.published_age_box.setPlaceholderText("Расчётная карта")
        self.published_age_box.setCurrentIndex(-1)
        self.published_age_box.setToolTip(
            "Выбери опубликованную опорную дату. Между этими датами "
            "приложение рассчитывает единую поверхность высот для выбранного возраста.")
        self.published_age_box.activated.connect(self.show_published_age)
        layout.addWidget(self.published_age_box)
        layout.addWidget(label("ОСНОВНЫЕ ЭПОХИ", CYAN, 9, True))
        stop_scroll = QScrollArea()
        stop_scroll.setWidgetResizable(True)
        stop_body = QWidget()
        stop_body.setObjectName("epochStops")
        stop_layout = QVBoxLayout(stop_body)
        stop_layout.setContentsMargins(0, 0, 0, 0)
        stop_layout.setSpacing(8)
        for age, title, unit_key, focus_feature, description in EPOCH_STOPS:
            stop_button = button(f"{age:>3} млн лет  ·  {title}",
                                 lambda _=False, a=age, k=unit_key, f=focus_feature,
                                     d=description: self.jump_to_epoch(a, k, d, f))
            stop_button.setMinimumHeight(36)
            stop_button.setToolTip(description)
            stop_layout.addWidget(stop_button)
        stop_layout.addStretch()
        stop_scroll.setWidget(stop_body)
        layout.addWidget(stop_scroll, 1)
        if self.data.has_precambrian_dem:
            source_note = (
                "Единая палитра числового рельефа 0–750 млн лет. Древние опорные "
                "карты: 600, 630, 690 и 750 млн лет. Между опорными датами "
                "высоты рассчитываются для каждого миллиона лет, затем "
                "окрашиваются как одна поверхность с единым берегом."
            )
        else:
            source_note = (
                f"Числовой рельеф до {self.data.dem_max_age:g} млн лет; глубже в прошлом "
                "показаны иллюстрированные карты PALEOMAP 2016. Между числовыми "
                "сетками рассчитывается одна поверхность высот."
            )
        self.epoch_source_note = label(source_note, GOLD, 8)
        self.epoch_source_note.setToolTip(self.data.source_description)
        layout.addWidget(self.epoch_source_note)

    def show_published_age(self, index):
        age = self.published_age_box.itemData(index)
        if age is None:
            return
        self.playing = False
        self.play_button.setText("▶ Воспроизвести")
        self.set_age(age)

    def jump_to_epoch(self, age, unit_key=None, description="", focus_feature_name=None):
        if self.playing:
            self.playing = False
            self.play_button.setText("▶ Воспроизвести")
        self.set_age(float(age))
        unit = next((item for item in UNITS if item.key == unit_key), None)
        if unit and unit.active(age):
            self.selected_paleo_units.add(unit.key)
            self.globe.camera_lon, self.globe.camera_lat = self.paleo_unit_position(unit, age)
            self.globe.zoom = max(1.2, self.globe.zoom)
        elif focus_feature_name:
            feature = next((item for item in FEATURES + self.custom_features
                            if item.name == focus_feature_name), None)
            if feature:
                self.selected_features.add(feature.name)
                self.globe.camera_lon, self.globe.camera_lat = self.model.point(
                    feature.lon, feature.lat, round(age))
                self.globe.zoom = max(1.2, self.globe.zoom)
        elif age == 0:
            self.globe.camera_lon, self.globe.camera_lat = self.city[3], self.city[2]
        else:
            self.globe.camera_lon, self.globe.camera_lat = self.city_at(self.city, age)
        self._zoom_changed()
        self.epoch_context_label.setText(f"{age} млн лет · {description}")
        self.globe.update()

    def render_features(self):
        while self.feature_layout.count():
            item = self.feature_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = self.feature_search.text().casefold().strip()
        last_kind = None
        for feature in sorted(FEATURES + self.custom_features, key=lambda x: (x.kind, x.name)):
            if query and query not in (feature.name + feature.kind).casefold():
                continue
            if feature.kind != last_kind:
                self.feature_layout.addWidget(label(feature.kind.upper(), CYAN, 9, True))
                last_kind = feature.kind
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            box = QCheckBox(feature.name)
            box.setChecked(feature.name in self.selected_features)
            box.toggled.connect(lambda enabled, f=feature: self.toggle_feature(f, enabled))
            h.addWidget(box, 1)
            h.addWidget(button("◎", lambda _=False, f=feature: self.focus_feature(f)))
            self.feature_layout.addWidget(row)
        self.feature_layout.addStretch()

    def city_at(self, city, age=None):
        return self.model.point(city[3], city[2], round(self.age if age is None else age))

    @staticmethod
    def city_label(city):
        country = city[1] or "без страны"
        return f"⌕  {city[0]} · {country}"

    def search_city(self, compare=False):
        title = "Выбрать город для сравнения" if compare else "Выбрать город"
        dialog = CitySearchDialog(self.city_catalog, title, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.place:
            return
        if compare:
            self.compare_city = dialog.place
            self.compare_button.setText(self.city_label(self.compare_city))
            self.update_location()
            self.globe.update()
        else:
            self.city = dialog.place
            self.city_button.setText(self.city_label(self.city))
            self.center_city()
            self.update_location()

    def center_city(self):
        self.globe.camera_lon, self.globe.camera_lat = self.city_at(self.city)
        self.globe.update()

    def pin_age(self):
        self.reference_age = round(self.age)
        self.update_location()
        self.globe.update()

    def toggle_tracks(self, enabled):
        self.tracks = enabled
        self.globe.update()

    def _distance(self, lon1, lat1, lon2, lat2):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dlat, dlon = p2-p1, math.radians(wrap(lon2-lon1))
        a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
        return 12742 * math.asin(min(1, math.sqrt(a)))

    def update_location(self):
        lon, lat = self.city_at(self.city)
        lon2, lat2 = self.city_at(self.compare_city)
        dist_now = self._distance(self.city[3], self.city[2], self.compare_city[3], self.compare_city[2])
        dist_then = self._distance(lon, lat, lon2, lat2)
        self.now_label.setText(f"Сегодня: {self.city[2]:.1f}° с. ш. · {self.city[3]:.1f}° в. д.")
        self.then_label.setText(f"В модели: {lat:.1f}° ш. · {lon:.1f}° д.")
        self.distance_label.setText(f"{self.city[0]} ↔ {self.compare_city[0]}\nСегодня: {dist_now:,.0f} км · тогда: {dist_then:,.0f} км".replace(",", " "))
        ref_lon, ref_lat = self.city_at(self.city, self.reference_age)
        displacement = self._distance(lon, lat, ref_lon, ref_lat)
        self.reference_label.setText(f"От эпохи {self.reference_age} млн лет: {displacement:,.0f} км в модели".replace(",", " "))

    def set_age(self, age, slider=False):
        self.age = max(0.0, min(float(MAX_AGE), float(age)))
        self.globe.set_age(self.age)
        tick = round(self.age)
        self.slider.blockSignals(True)
        self.slider.setValue(tick)
        self.slider.blockSignals(False)
        self.age_label.setText(f"{self.age:.1f}" if self.playing else str(tick))
        mode, published_age, _, _ = self.data.frames(self.age)
        displayed = self.globe.displayed_frame or (mode, published_age)
        self.update_map_source(*displayed)
        period = next(period for period in PERIODS if self.age <= period[0])
        self.era_label.setText(period[2])
        self.period_label.setText(period[1])
        self.update_paleo_context()
        if hasattr(self, "epoch_context_label"):
            story = age_story(tick)
            self.epoch_context_label.setText(f"{story.heading} · {story.text}")
        now = perf_counter()
        if now - self._last_labels > .09 or not self.playing:
            self.update_location()
            self._last_labels = now

    def update_map_source(self, mode, displayed_age):
        target_mode, target_young, _, _ = self.data.frames(self.age)
        target_age = self.age if target_mode == "dem" else target_young
        pending = mode != target_mode or abs(displayed_age - target_age) > 0.001
        _, younger, older, fraction = self.data.frames(displayed_age)
        calculated = mode == "dem" and younger != older and 0.0 < fraction < 1.0
        if calculated:
            note = f" · расчёт по картам {younger:g}–{older:g} млн"
        elif mode == "dem":
            note = " · опорная карта"
        else:
            note = " · опорная иллюстрация"
        if pending:
            note += f" · загружается {self.age:g} млн"
        source = (f"{self.data.source_name} · сетка {self.data.resolution}" if mode == "dem" else
                  "PALEOMAP 2016 · иллюстрированная карта")
        self.source_label.setText(f"{source} · {displayed_age:g} млн лет{note}")
        self.source_label.setToolTip(
            self.data.source_description + "\nПромежуточная карта — расчётная визуализация "
            "между опубликованными сетками, а не самостоятельная научная реконструкция. "
            "Положения городов и полигонов "
            "рассчитываются для возраста на шкале времени.")
        self.published_age_box.blockSignals(True)
        self.published_age_box.setCurrentIndex(
            -1 if calculated else self.published_age_box.findData(displayed_age))
        self.published_age_box.blockSignals(False)
        self.legend_holder.setVisible(mode == "dem")
        self.legacy_legend.setVisible(mode == "atlas")

    def tick(self):
        now = perf_counter()
        dt = min(.1, now - self._last_tick)
        self._last_tick = now
        if self.playing:
            target = self.age + self.speed * dt
            if target > MAX_AGE:
                target = 0
            self.set_age(target)
        if self.spinning:
            self.globe.camera_lon = wrap(self.globe.camera_lon + 22.0*dt)
            self.globe.update()

    def toggle_play(self):
        self.playing = not self.playing
        self.play_button.setText("❚❚ Пауза" if self.playing else "▶ Воспроизвести")
        self._last_tick = perf_counter()

    def toggle_spin(self):
        self.spinning = not self.spinning
        self.spin_button.setText("❚❚ Стоп" if self.spinning else "⟳ Вращать")
        self._last_tick = perf_counter()

    def change_zoom(self, factor):
        self.globe.zoom = max(.7, min(MAX_ZOOM, self.globe.zoom*factor))
        self._zoom_changed()
        self.globe.update()

    def change_sharpness(self, value):
        self.globe.sharpness = value / 100.0
        self.sharpness_label.setText(f"{value}%")
        self.globe.update()

    def preview_sharpness(self, original):
        if original:
            self.globe.sharpness = 0.0
            self.sharpness_label.setText("0%")
            self.globe.update()
        else:
            self.change_sharpness(self.sharpness_slider.value())

    def _zoom_changed(self):
        self.zoom_label.setText(f"{self.globe.zoom*100:.0f}%")

    def update_paleo_context(self):
        age = round(self.age)
        story = age_story(age)
        units = active_units(age)
        heading = f"ДРЕВНЯЯ ГЕОГРАФИЯ · {story.heading.upper()} · {age} МЛН ЛЕТ"
        if self.paleo_context_heading.text() != heading:
            self.paleo_context_heading.setText(heading)
        if self.paleo_context_text.text() != story.text:
            self.paleo_context_text.setText(story.text)
        signature = (story, tuple((unit.group, unit.key) for unit in units))
        if signature == self._paleo_context_signature:
            return
        for group, row in self.paleo_unit_rows.items():
            while row.count():
                item = row.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            row.addWidget(label(group.upper(), CYAN, 8, True))
            group_units = [unit for unit in units if unit.group == group]
            if not group_units:
                row.addWidget(label("—", MUTED, 8))
            for unit in group_units:
                checkbox = QCheckBox(unit.name)
                checkbox.setChecked(unit.key in self.selected_paleo_units)
                checkbox.setToolTip(unit.description + "\nОтметьте, чтобы показать точку и перейти к ней.")
                checkbox.toggled.connect(
                    lambda enabled, key=unit.key: self.toggle_paleo_marker(key, enabled))
                row.addWidget(checkbox)
            row.addStretch()
        self._paleo_context_signature = signature

    def paleo_unit_position(self, unit, age=None):
        reconstruction_age = round(self.age if age is None else age)
        points = [self.model.point(lon, lat, reconstruction_age)
                  for lon, lat in unit.anchors]
        vectors = []
        for lon, lat in points:
            lon_r, lat_r = math.radians(lon), math.radians(lat)
            vectors.append((math.cos(lat_r)*math.cos(lon_r),
                            math.cos(lat_r)*math.sin(lon_r), math.sin(lat_r)))
        x = sum(point[0] for point in vectors)
        y = sum(point[1] for point in vectors)
        z = sum(point[2] for point in vectors)
        length = math.sqrt(x*x + y*y + z*z)
        if length < 1e-8:
            lon, lat = points[0]
        else:
            lon = math.degrees(math.atan2(y, x))
            lat = math.degrees(math.atan2(z, math.hypot(x, y)))
        if unit.marker_mode == "antipode":
            lon, lat = wrap(lon+180), -lat
        return wrap(lon), lat

    def toggle_paleo_marker(self, key, enabled):
        unit = next((item for item in UNITS if item.key == key), None)
        if enabled:
            self.selected_paleo_units.add(key)
            if unit:
                self.globe.camera_lon, self.globe.camera_lat = self.paleo_unit_position(unit)
                self.globe.zoom = max(1.6, self.globe.zoom)
                self._zoom_changed()
        else:
            self.selected_paleo_units.discard(key)
        self.globe.update()

    def _camera_changed(self):
        pass

    def _fps_changed(self, fps):
        self.fps_label.setText(f"{fps:.0f} кадр/с" if self.playing or self.spinning or self.globe._drag else "GPU")

    def _chosen_layer(self):
        index = self.layer_list.currentRow()
        return self.layers[index] if 0 <= index < len(self.layers) else None

    def add_layer(self):
        path, _ = QFileDialog.getOpenFileName(self, "Полигоны лицензионных участков", "",
                  "Геоданные (*.cps *.cps3 *.dat *.pol *.txt *.shp *.geojson *.json *.kml *.zip);;CPS-3 XY / LINES (*.cps *.cps3 *.dat *.pol *.txt *.shp);;Проект Isoline — проверка (*.ipr);;Все файлы (*.*)")
        if not path:
            return
        if Path(path).suffix.lower() == ".ipr":
            self.inspect_isoline_project(path)
            return
        opts = {"source_crs": "EPSG:4326", "axis_order": "xy"}
        if Path(path).suffix.lower() in (".cps", ".cps3", ".dat", ".pol", ".txt", ".shp"):
            try:
                lines_export = is_cps3_lines_file(path)
                if Path(path).suffix.lower() == ".shp" and not lines_export:
                    raise ValueError(
                        "Этот .shp не содержит текстовый заголовок CPS-3 #FSASCI … LINES. "
                        "Для ESRI Shapefile загрузите ZIP с .shp, .shx, .dbf и .prj.")
            except (OSError, ValueError) as exc:
                self.show_error(str(exc))
                return
            dialog = CPS3CoordinateDialog(self, source_path=path, lines_export=lines_export)
            if dialog.exec() != QDialog.Accepted:
                return
            opts = {"source_crs": dialog.crs, "axis_order": dialog.order}
        try:
            layer = load_polygon_layer(path, **opts)
        except Exception as exc:
            self.show_error(str(exc))
            return
        self.layers.append(layer)
        self.layer_list.addItem(f"●  {layer.name} ({len(layer.features)})")
        self.layer_list.setCurrentRow(len(self.layers)-1)
        self.focus_layer()

    def inspect_isoline_project(self, path=None):
        if not isinstance(path, (str, Path)):
            path, _ = QFileDialog.getOpenFileName(
                self, "Проверка проекта Isoline", "", "Проект Isoline (*.ipr)")
        if not path:
            return
        from isoline_project import inspect_isoline_project
        try:
            info = inspect_isoline_project(path)
        except (OSError, ValueError) as exc:
            self.show_error(str(exc))
            return
        names = "\n".join(f"• {name}" for name in info.polygon_layer_names[:12])
        projection = info.projection or "не определена"
        details = (
            f"Проект: {info.project_name}\nСлоёв: {info.layer_count}\n"
            f"Полигонных слоёв: {len(info.polygon_layer_names)}\n"
            f"Проекция: {projection}\n\n"
            + (f"Полигонные слои:\n{names}\n\n" if names else "")
        )
        if info.projection == "Rect":
            details += (
                "Rect — прямоугольные координаты без заданной геодезической системы. "
                "Для положения на глобусе нужны подтверждённая исходная СК "
                "либо географическая привязка по контрольным точкам.\n\n"
            )
        if info.external_files:
            details += "Внешние ссылки проекта:\n" + "\n".join(
                f"• {value}" for value in info.external_files[:8]) + "\n\n"
        details += (
            "Это проверка структуры проекта, а не импорт его геометрии. "
            "Сжатые контуры IPR пока не поддерживаются. Для загрузки участка "
            "используйте CPS-3 XY / LINES, GeoJSON, KML или Shapefile ZIP с известной СК. "
            "Картинка без координатной привязки не задаёт географическое положение."
        )
        QMessageBox.information(self, "Проект Isoline: данные и привязка", details)

    def convert_cps3(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите CPS-3 ASCII XY / LINES", "",
            "CPS-3 XY / LINES (*.cps *.cps3 *.dat *.pol *.txt *.shp);;Все файлы (*.*)")
        if not path:
            return
        try:
            lines_export = is_cps3_lines_file(path)
            if Path(path).suffix.lower() == ".shp" and not lines_export:
                raise ValueError(
                    "Этот .shp не содержит текстовый заголовок CPS-3 #FSASCI … LINES. "
                    "Конвертер принимает текст CPS-3, а ESRI Shapefile загружается "
                    "как слой через ZIP с .prj.")
        except (OSError, ValueError) as exc:
            self.show_error(str(exc))
            return
        dialog = CPS3CoordinateDialog(self, exporting=True, source_path=path,
                                      lines_export=lines_export)
        if dialog.exec() != QDialog.Accepted:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Сохранить преобразованный CPS-3",
            str(Path(path).with_name(Path(path).stem + "_converted.cps")),
            "CPS-3 (*.cps *.cps3);;Все файлы (*.*)")
        if not destination:
            return
        try:
            output = convert_cps3_file(
                path, destination,
                source_crs=dialog.crs,
                target_crs=dialog.target.currentText().strip(),
                source_axis_order=dialog.order,
                target_axis_order=dialog.target_axis.currentData())
            QMessageBox.information(self, "Координаты преобразованы",
                                    f"Файл сохранён:\n{output}")
        except Exception as exc:
            self.show_error(str(exc))

    def layer_selected(self, index):
        layer = self._chosen_layer()
        if not layer:
            return
        self.layer_visible.blockSignals(True)
        self.layer_visible.setChecked(layer.visible)
        self.layer_visible.blockSignals(False)
        self.parcel_box.blockSignals(True)
        self.parcel_box.clear()
        self.parcel_box.addItems([f.name for f in layer.features])
        self.parcel_box.blockSignals(False)
        vertices = sum(len(r) for f in layer.features for r in f.rings)
        self.layer_info.setText(f"{layer.name}\n{len(layer.features)} полигонов · {vertices} вершин\n{layer.path.name}")
        self.globe.update()

    def change_layer_visibility(self, enabled):
        layer = self._chosen_layer()
        if layer:
            layer.visible = enabled
            index = self.layer_list.currentRow()
            self.layer_list.item(index).setText(f"{'●' if enabled else '○'}  {layer.name} ({len(layer.features)})")
            self.globe.update()

    def focus_layer(self):
        layer = self._chosen_layer()
        if not layer or not layer.features:
            return
        index = max(0, self.parcel_box.currentIndex())
        feature = layer.features[index]
        lon, lat = feature.center
        self.globe.camera_lon, self.globe.camera_lat = self.model.point(lon, lat, round(self.age))
        phi = math.radians(lat)
        extent = 0.0
        for ring in feature.rings:
            for point_lon, point_lat in ring:
                point_phi = math.radians(point_lat)
                cosine = (math.sin(phi) * math.sin(point_phi)
                          + math.cos(phi) * math.cos(point_phi)
                          * math.cos(math.radians(wrap(point_lon - lon))))
                extent = max(extent, math.acos(max(-1.0, min(1.0, cosine))))
        width, height = max(1, self.globe.width()), max(1, self.globe.height())
        base_radius = min(width * .39, height * .48)
        fitted_zoom = min(width, height) * .38 / (
            base_radius * max(.001, math.sin(min(extent, math.pi / 2))))
        self.globe.zoom = max(.7, min(MAX_ZOOM, fitted_zoom))
        self._zoom_changed()
        self.globe.update()

    def toggle_feature(self, feature, enabled):
        if enabled:
            self.selected_features.add(feature.name)
        else:
            self.selected_features.discard(feature.name)
        self.globe.update()

    def focus_feature(self, feature):
        self.globe.camera_lon, self.globe.camera_lat = self.model.point(feature.lon, feature.lat, round(self.age))
        self.globe.zoom = max(1.6, self.globe.zoom)
        self._zoom_changed()
        self.globe.update()

    def add_custom_feature(self):
        name, okay = QInputDialog.getText(self, "Своя точка", "Название ориентира:")
        if not okay or not name.strip():
            return
        lat, okay = QInputDialog.getDouble(self, "Широта", "Широта:", 0, -90, 90, 4)
        if not okay:
            return
        lon, okay = QInputDialog.getDouble(self, "Долгота", "Долгота:", 0, -180, 180, 4)
        if not okay:
            return
        feature = AtlasFeature(name.strip(), "Своя точка", lat, lon, "Авто")
        self.custom_features.append(feature)
        self.selected_features.add(feature.name)
        self.render_features()
        self.focus_feature(feature)

    def project(self, lon, lat, cx, cy, radius):
        phi, lam, phi0 = map(math.radians, (lat, wrap(lon-self.globe.camera_lon), self.globe.camera_lat))
        z = math.sin(phi0)*math.sin(phi) + math.cos(phi0)*math.cos(phi)*math.cos(lam)
        x = cx + radius*math.cos(phi)*math.sin(lam)
        y = cy - radius*(math.cos(phi0)*math.sin(phi)-math.sin(phi0)*math.cos(phi)*math.cos(lam))
        return x, y, z

    def _marker(self, painter, x, y, color, text, strong=False):
        painter.setPen(QPen(QColor(color), 2.4 if strong else 1.8))
        painter.setBrush(Qt.NoBrush)
        radius = 12 if strong else 9
        painter.drawEllipse(int(x-radius), int(y-radius), radius*2, radius*2)
        painter.setBrush(QColor(color))
        painter.drawEllipse(int(x-3), int(y-3), 6, 6)
        painter.setFont(QFont("Segoe UI", 10 if strong else 9, QFont.Bold))
        painter.drawText(int(x+radius+6), int(y-7), text)

    def draw_overlay(self, painter, cx, cy, radius):
        if radius <= 0:
            return
        age = round(self.age)
        if self.tracks:
            for city, color in ((self.city, GOLD), (self.compare_city, CYAN)):
                painter.setPen(QPen(QColor(color), 1.6))
                path = QPainterPath()
                active = False
                for time in range(0, MAX_AGE+1, 10):
                    x, y, z = self.project(*self.city_at(city, time), cx, cy, radius)
                    if z >= 0:
                        if not active:
                            path.moveTo(x, y)
                        else:
                            path.lineTo(x, y)
                        active = True
                    else:
                        active = False
                painter.drawPath(path)
        painter.setPen(QPen(QColor("#ff4c5b"), 2.4))
        for layer in self.layers:
            if not layer.visible:
                continue
            for feature in layer.features:
                plate = self.model.plate_id(*feature.center)
                for ring in feature.rings:
                    # Screen rendering is decimated, source polygon remains intact.
                    step = max(1, len(ring)//3000)
                    cache_key = (id(ring), age, step)
                    moving = self._ring_cache.get(cache_key)
                    if moving is None:
                        moving = self.model.ring(ring[::step], age, plate)
                        self._ring_cache[cache_key] = moving
                        if len(self._ring_cache) > 150:
                            self._ring_cache.clear()
                    path = QPainterPath()
                    active = False
                    first_visible = None
                    all_visible = True
                    for lon, lat in moving:
                        x, y, z = self.project(lon, lat, cx, cy, radius)
                        if z >= 0:
                            if not active:
                                path.moveTo(x, y)
                                if first_visible is None:
                                    first_visible = (x, y)
                            else:
                                path.lineTo(x, y)
                            active = True
                        else:
                            active = False
                            all_visible = False
                    if all_visible and first_visible:
                        path.lineTo(*first_visible)
                    painter.drawPath(path)
        occupied = []
        for city, color, strong in ((self.city, GOLD, True), (self.compare_city, CYAN, False)):
            x, y, z = self.project(*self.city_at(city), cx, cy, radius)
            if z >= 0 and -30 < x < self.globe.width()+30 and -30 < y < self.globe.height()+30:
                self._marker(painter, x, y, color, city[0], strong)
                occupied.append((x, y))
        for unit in active_units(age):
            if unit.key not in self.selected_paleo_units:
                continue
            lon, lat = self.paleo_unit_position(unit, age)
            x, y, z = self.project(lon, lat, cx, cy, radius)
            if z < 0 or not (8 < x < self.globe.width()-12 and 8 < y < self.globe.height()-8):
                continue
            overlaps = any(abs(x-a) < 90 and abs(y-b) < 18 for a, b in occupied)
            color = CYAN if unit.group == "Океаны" else "#f7d772"
            painter.setPen(QPen(QColor(color), 1.6))
            painter.setBrush(QColor("#0c2130"))
            painter.drawEllipse(int(x-5), int(y-5), 10, 10)
            painter.setBrush(QColor(color))
            painter.drawEllipse(int(x-2), int(y-2), 4, 4)
            if not overlaps:
                painter.setPen(QColor("#f8f1ce"))
                painter.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
                painter.drawText(int(x+8), int(y-5), unit.name)
            occupied.append((x, y))
        for feature in FEATURES + self.custom_features:
            if feature.name not in self.selected_features:
                continue
            lon, lat = self.model.point(feature.lon, feature.lat, age)
            x, y, z = self.project(lon, lat, cx, cy, radius)
            if z < 0 or not (8 < x < self.globe.width()-80 and 8 < y < self.globe.height()-8):
                continue
            if any(abs(x-a)<90 and abs(y-b)<18 for a,b in occupied):
                continue
            painter.setPen(QColor("#f8f1ce"))
            painter.setBrush(QColor("#ffe372"))
            painter.drawEllipse(int(x-3), int(y-3), 6, 6)
            painter.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
            painter.drawText(int(x+8), int(y-6), feature.name)
            occupied.append((x,y))

    def _restore_session(self):
        if not self.session_path.exists():
            self.globe.camera_lon, self.globe.camera_lat = self.city_at(self.city)
            return
        try:
            state = json.loads(self.session_path.read_text(encoding="utf-8"))
            self.age = max(0, min(MAX_AGE, float(state.get("age", 140))))
            self.reference_age = max(0, min(MAX_AGE, int(state.get("reference_age", 0))))
            self.globe.zoom = max(.7, min(MAX_ZOOM, float(state.get("zoom", 1))))
            self.sharpness_slider.setValue(max(0, min(MAX_SHARPNESS, int(state.get("sharpness", DEFAULT_SHARPNESS)))))
            self.selected_features = set(state.get("selected_features", []))
            self.selected_paleo_units = set(state.get("selected_paleo_units", []))
            self.custom_features = [AtlasFeature(str(v["name"]), "Своя точка", float(v["lat"]),
                                                 float(v["lon"]), str(v.get("plate", "Авто")))
                                    for v in state.get("custom_features", [])]
            self.city = self._saved_city(state, "city", CITIES[0])
            self.compare_city = self._saved_city(state, "compare_city", CITIES[1])
            self.city_button.setText(self.city_label(self.city))
            self.compare_button.setText(self.city_label(self.compare_city))
            self.render_features()
            for item in state.get("layers", []):
                path = Path(item["path"])
                if path.exists():
                    try:
                        layer = load_polygon_layer(path,
                            source_crs=str(item.get("source_crs", "EPSG:4326")),
                            axis_order=str(item.get("axis_order", "xy")))
                    except Exception as exc:
                        self.layer_restore_errors.append(f"{path.name}: {exc}")
                        continue
                    layer.visible = bool(item.get("visible", True))
                    self.layers.append(layer)
                    self.layer_list.addItem(f"{'●' if layer.visible else '○'}  {layer.name} ({len(layer.features)})")
                else:
                    self.layer_restore_errors.append(f"{path.name}: исходный файл не найден ({path})")
            if self.layers:
                self.layer_list.setCurrentRow(0)
            self._zoom_changed()
        except (OSError, ValueError, TypeError, KeyError):
            pass
        self.globe.camera_lon, self.globe.camera_lat = self.city_at(self.city)

    def _show_layer_restore_errors(self):
        details = "\n\n".join(self.layer_restore_errors[:8])
        if len(self.layer_restore_errors) > 8:
            details += f"\n\nИ ещё {len(self.layer_restore_errors) - 8} файлов."
        QMessageBox.warning(
            self, "Часть слоёв не восстановлена",
            "Не удалось восстановить некоторые полигоны:\n\n" + details
            + "\n\nЕсли файл перемещён, выберите его снова через «Добавить слой».")

    def _saved_city(self, state, prefix, fallback):
        place_id = state.get(f"{prefix}_id")
        if place_id:
            try:
                place = self.city_catalog.by_id(place_id, state.get(prefix))
                if place:
                    return place
            except (TypeError, ValueError):
                pass
        name = state.get(prefix)
        country = state.get(f"{prefix}_country")
        if not name:
            return fallback
        match = next((city for city in CITIES if city[0] == name and
                      (not country or city[1] == country)), None)
        if match:
            return match
        return next((place for place in self.city_catalog.search(name, 50)
                     if place[0] == name and (not country or place[1] == country)), fallback)

    def closeEvent(self, event):
        state = {
            "age": round(self.age), "reference_age": self.reference_age,
            "city": self.city[0], "city_country": self.city[1],
            "city_id": self.city[4] if len(self.city) > 4 else None,
            "compare_city": self.compare_city[0], "compare_city_country": self.compare_city[1],
            "compare_city_id": self.compare_city[4] if len(self.compare_city) > 4 else None,
            "zoom": self.globe.zoom, "sharpness": self.sharpness_slider.value(),
            "selected_features": sorted(self.selected_features),
            "selected_paleo_units": sorted(self.selected_paleo_units),
            "custom_features": [{"name": f.name, "lat": f.lat, "lon": f.lon, "plate": f.plate}
                                for f in self.custom_features],
            "layers": [{"path": str(layer.path), "visible": layer.visible,
                        "source_crs": layer.source_crs, "axis_order": layer.axis_order}
                       for layer in self.layers],
        }
        try:
            temp = self.session_path.with_suffix(".tmp")
            temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.session_path)
        except OSError:
            pass
        self.globe.close_data()
        super().closeEvent(event)

    def show_error(self, detail):
        QMessageBox.warning(self, "Ошибка Палеоатласа", detail)


STYLE = """
QWidget#root {background:#061322; color:#f4f8ee; font-family:'Segoe UI'; font-size:10pt;}
QWidget#epochStops {background:#0c2130;}
QFrame#card, QTabWidget::pane {background:#0c2130; border:1px solid #29506a; border-radius:8px;}
QTabWidget::tab-bar {alignment:center;}
QTabBar::tab {background:#143347; color:#a2bdc5; padding:10px 14px; border-radius:4px;}
QTabBar::tab:selected {background:#1e5a70; color:#ffffff;}
QPushButton {background:#17445a; color:#f4f8ee; border:1px solid #27637c; border-radius:6px;
             padding:8px 10px; font-weight:600;}
QPushButton:hover {background:#246780;}
QPushButton[primary="true"] {background:#26aecd; color:#04202c; border:0;}
QPushButton[primary="true"]:hover {background:#55cde5;}
QComboBox, QLineEdit, QListWidget {background:#102a3b; color:#f4f8ee; border:1px solid #2b5769;
             border-radius:5px; padding:7px;}
QComboBox QAbstractItemView {background:#102a3b; color:#f4f8ee; selection-background-color:#25637a;}
QCheckBox {color:#e8f6f4; spacing:7px;}
QCheckBox::indicator {width:17px; height:17px;}
QSlider::groove:horizontal {height:6px; background:#24495b; border-radius:3px;}
QSlider::sub-page:horizontal {background:#2cd0ec; border-radius:3px;}
QSlider::handle:horizontal {background:#f5e17c; width:18px; margin:-6px 0; border-radius:9px;}
QScrollArea {border:0; background:transparent;}
"""


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyleSheet(STYLE)
    window = AtlasWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
