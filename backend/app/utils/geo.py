"""Monocular ground-plane projection: place a detected vehicle on the map.

Given a camera's geo-position + orientation and where the vehicle's wheels sit
in the frame, estimate the vehicle's lat/lon. This is an approximation (no per-
camera calibration), but it synchronizes video detections with geo-coordinates
well enough to render live vehicle placement on the 3D map.

  img_x in [0,1]  left -> right across the frame
  img_y in [0,1]  top -> bottom; bottom of frame = nearest the camera
"""

import math

EARTH_R = 6_378_137.0  # metres
MIN_RANGE_M = 6.0      # a vehicle at the very bottom of frame is ~this close


def project(lat: float, lon: float, heading_deg: float, fov_deg: float,
            range_m: float, img_x: float, img_y: float) -> tuple[float, float]:
    # lateral angle within the FOV, relative to the camera's heading
    lateral = (img_x - 0.5) * fov_deg
    bearing = math.radians(heading_deg + lateral)
    # depth: bottom of frame (img_y≈1) is near, top (img_y≈0) is far.
    # square-ish falloff approximates perspective foreshortening.
    depth = MIN_RANGE_M + (1.0 - img_y) ** 1.6 * (range_m - MIN_RANGE_M)

    d = depth / EARTH_R
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(d) +
                     math.cos(lat1) * math.sin(d) * math.cos(bearing))
    lon2 = lon1 + math.atan2(math.sin(bearing) * math.sin(d) * math.cos(lat1),
                             math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


def fov_polygon(lat: float, lon: float, heading_deg: float, fov_deg: float,
                range_m: float, steps: int = 8) -> list[list[float]]:
    """[[lon,lat], ...] ring of the camera's coverage wedge, for the map."""
    ring = [[lon, lat]]
    half = fov_deg / 2
    for i in range(steps + 1):
        ang = heading_deg - half + fov_deg * i / steps
        b = math.radians(ang)
        d = range_m / EARTH_R
        lat1, lon1 = math.radians(lat), math.radians(lon)
        la = math.asin(math.sin(lat1) * math.cos(d) +
                       math.cos(lat1) * math.sin(d) * math.cos(b))
        lo = lon1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(lat1),
                               math.cos(d) - math.sin(lat1) * math.sin(la))
        ring.append([math.degrees(lo), math.degrees(la)])
    ring.append([lon, lat])
    return ring
