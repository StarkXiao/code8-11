import unittest

from forest_fire.geo import bearing_deg, destination_point, haversine_km


class TestGeo(unittest.TestCase):
    def test_haversine_equator_degree(self):
        # 赤道上经度 1° ≈ 111.19 km
        self.assertAlmostEqual(haversine_km(0, 0, 0, 1), 111.19, places=1)

    def test_haversine_zero(self):
        self.assertEqual(haversine_km(42.1, 127.9, 42.1, 127.9), 0.0)

    def test_bearing_cardinal(self):
        self.assertAlmostEqual(bearing_deg(0, 0, 1, 0), 0.0, places=6)   # 正北
        self.assertAlmostEqual(bearing_deg(0, 0, 0, 1), 90.0, places=6)  # 正东

    def test_destination_roundtrip(self):
        lat1, lon1 = 42.15, 127.86
        lat2, lon2 = 42.10, 127.91
        d = haversine_km(lat1, lon1, lat2, lon2)
        b = bearing_deg(lat1, lon1, lat2, lon2)
        lat3, lon3 = destination_point(lat1, lon1, b, d)
        self.assertAlmostEqual(lat3, lat2, places=6)
        self.assertAlmostEqual(lon3, lon2, places=6)


if __name__ == "__main__":
    unittest.main()
