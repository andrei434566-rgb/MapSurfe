"""Modern geographic reference points for label tracking on the schematic atlas.

The names describe present-day places. Their plotted ancient positions are
modelled anchors, not claims that the modern landforms existed at every age.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class AtlasFeature:
    name: str
    kind: str
    lat: float
    lon: float
    plate: str


FEATURES = [
    AtlasFeature("Таймыр", "Полуостров", 74.0, 103.0, "Евразия"),
    AtlasFeature("Ямал", "Полуостров", 70.5, 70.0, "Евразия"),
    AtlasFeature("Камчатка", "Полуостров", 56.0, 160.0, "Евразия"),
    AtlasFeature("Чукотка", "Полуостров", 67.0, -173.0, "Евразия"),
    AtlasFeature("Скандинавский п-ов", "Полуостров", 63.0, 16.0, "Евразия"),
    AtlasFeature("Пиренейский п-ов", "Полуостров", 40.0, -4.0, "Евразия"),
    AtlasFeature("Аравийский п-ов", "Полуостров", 23.0, 45.0, "Аравия"),
    AtlasFeature("Индостан", "Полуостров", 17.0, 78.0, "Индия"),
    AtlasFeature("Урал", "Горная система", 60.0, 59.0, "Евразия"),
    AtlasFeature("Гималаи", "Горная система", 28.0, 85.0, "Индия"),
    AtlasFeature("Альпы", "Горная система", 46.5, 10.0, "Евразия"),
    AtlasFeature("Кавказ", "Горная система", 43.0, 44.0, "Евразия"),
    AtlasFeature("Анды", "Горная система", -18.0, -70.0, "Южная Америка"),
    AtlasFeature("Кордильеры", "Горная система", 43.0, -113.0, "Северная Америка"),
    AtlasFeature("Атлас", "Горная система", 32.0, -6.0, "Африка"),
    AtlasFeature("Большой Водораздельный хребет", "Горная система", -28.0, 151.0, "Австралия"),
    AtlasFeature("Гренландия", "Остров", 72.0, -42.0, "Северная Америка"),
    AtlasFeature("Мадагаскар", "Остров", -20.0, 47.0, "Африка"),
    AtlasFeature("Сахалин", "Остров", 50.0, 143.0, "Евразия"),
    AtlasFeature("Новая Земля", "Остров", 74.0, 58.0, "Евразия"),
    AtlasFeature("Исландия", "Остров", 65.0, -18.0, "Евразия"),
    AtlasFeature("Борнео", "Остров", 1.0, 114.0, "Евразия"),
    AtlasFeature("Новая Гвинея", "Остров", -5.0, 141.0, "Австралия"),
    AtlasFeature("Хонсю", "Остров", 37.0, 138.0, "Евразия"),
    AtlasFeature("Новая Зеландия", "Остров", -41.0, 173.0, "Австралия"),
]
