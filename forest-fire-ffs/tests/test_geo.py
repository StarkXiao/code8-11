import unittest

from ffs.geo import (
    BearingLine,
    bearing_deg,
    destination_point,
    haversine_m,
    triangulate,
)


class TestGeo(unittest.TestCase):
    def test_haversine_one_degree_latitude(self):
        d = haversine_m(24.0, 101.0, 25.0, 101.0)
        self.assertAlmostEqual(d, 111_195, delta=500)

    def test_destination_roundtrip(self):
        lat, lon = destination_point(24.8, 101.2, 63.0, 5000.0)
        self.assertAlmostEqual(bearing_deg(24.8, 101.2, lat, lon), 63.0, places=3)
        self.assertAlmostEqual(haversine_m(24.8, 101.2, lat, lon), 5000.0, delta=1.0)

    def test_triangulate_recovers_known_point(self):
        truth = (24.812, 101.215)
        t1, t2 = (24.835, 101.180), (24.790, 101.250)
        lines = [
            BearingLine(*t1, bearing_deg(*t1, *truth)),
            BearingLine(*t2, bearing_deg(*t2, *truth)),
        ]
        lat, lon = triangulate(lines)
        self.assertLess(haversine_m(lat, lon, *truth), 1.0)

    def test_triangulate_needs_two_lines(self):
        self.assertIsNone(triangulate([BearingLine(24.8, 101.2, 90.0)]))


if __name__ == "__main__":
    unittest.main()
