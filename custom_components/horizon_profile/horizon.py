"""
Horizontprofil (Azimut, Höhenwinkel) für einen Standort aus Copernicus GLO-30,
OHNE rasterio/GDAL.

Die benötigten Kachelbereiche werden per HTTP-Range-Request direkt aus dem
öffentlichen AWS-Bucket "copernicus-dem-30m" gelesen (kein Account, kein
API-Key, kein Komplett-Download). Das GeoTIFF (COG) wird mit einem kleinen
eigenen Leser dekodiert (Deflate + Floating-Point-Predictor).

Azimut-Konvention der Ausgabe:
    Standard : 0° = Nord, 90° = Ost, 180° = Süd, 270° = West
    --pvgis  : 0° = Süd, +90° = West, -90° = Ost (wie PVGIS / pvlib)

Hinweis: GLO-30 ist ein Oberflächenmodell (DSM). Es enthält also auch
Bäume und Gebäude, soweit sie in den 30-m-Pixeln sichtbar sind.

Benötigt: numpy, scipy, pyproj
    pip install numpy scipy pyproj

Beispiel (Bad Reichenhall):
    python horizon.py 47.7231 12.8786 --max-dist 50000 --pvgis --out horizon.csv
"""
import argparse
import csv
import math
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass

import numpy as np
from pyproj import Geod
from scipy.ndimage import map_coordinates

R_EARTH = 6_371_000.0
K_REFRACTION = 0.13
M_PER_DEG = 111_320.0
AWS_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"


class _Source:
    def __init__(self, path):
        self.path = path
        self.remote = path.startswith(("http://", "https://"))

    def read(self, offset, length):
        if not self.remote:
            with open(self.path, "rb") as file:
                file.seek(offset)
                return file.read(length)

        request = urllib.request.Request(
            self.path,
            headers={"Range": f"bytes={offset}-{offset + length - 1}"},
        )
        last_error = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code in (403, 404):
                    raise FileNotFoundError(self.path) from error
                last_error = error
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last_error = error
            time.sleep(1 + attempt)
        raise RuntimeError(f"Download failed: {self.path}: {last_error}")


class CogTile:
    _FMT = {3: ("H", 2), 4: ("I", 4), 12: ("d", 8)}

    def __init__(self, path):
        self.src = _Source(path)
        self._head = self.src.read(0, 65536)
        head = self._head
        if head[:2] == b"II":
            endian = "<"
        elif head[:2] == b"MM":
            endian = ">"
        else:
            raise ValueError(f"{path}: not a TIFF file")
        self.endian = endian
        if struct.unpack(endian + "H", head[2:4])[0] != 42:
            raise ValueError(f"{path}: BigTIFF is not supported")
        ifd_offset = struct.unpack(endian + "I", head[4:8])[0]
        tag_count = struct.unpack(endian + "H", self._get(ifd_offset, 2))[0]
        raw_tags = self._get(ifd_offset + 2, 12 * tag_count)
        tags = {}
        for index in range(tag_count):
            tag, field_type, count = struct.unpack(
                endian + "HHI",
                raw_tags[12 * index:12 * index + 8],
            )
            if field_type in self._FMT:
                code, size = self._FMT[field_type]
                total = size * count
                value_raw = raw_tags[12 * index + 8:12 * index + 12]
                if total <= 4:
                    data = value_raw[:total]
                else:
                    value_offset = struct.unpack(endian + "I", value_raw)[0]
                    data = self._get(value_offset, total)
                tags[tag] = struct.unpack(f"{endian}{count}{code}", data)

        def need(tag, name):
            if tag not in tags:
                raise ValueError(f"{path}: missing TIFF tag {name}")
            return tags[tag]

        self.width = need(256, "ImageWidth")[0]
        self.height = need(257, "ImageLength")[0]
        self.tile_width = need(322, "TileWidth (image is not tiled)")[0]
        self.tile_height = need(323, "TileLength")[0]
        self.offsets = need(324, "TileOffsets")
        self.counts = need(325, "TileByteCounts")
        self.compression = tags.get(259, (1,))[0]
        self.predictor = tags.get(317, (1,))[0]
        if tags.get(258, (32,))[0] != 32 or tags.get(339, (1,))[0] != 3:
            raise ValueError(f"{path}: only float32 pixels are supported")
        if tags.get(277, (1,))[0] != 1:
            raise ValueError(f"{path}: only single-band images are supported")
        if self.compression not in (1, 8, 32946):
            raise ValueError(f"{path}: unsupported compression {self.compression}")
        if self.predictor not in (1, 3):
            raise ValueError(f"{path}: unsupported predictor {self.predictor}")
        self.tiles_across = -(-self.width // self.tile_width)

        scale_x, scale_y = need(33550, "ModelPixelScale")[:2]
        i, j, _, x, y, _ = need(33922, "ModelTiepoint")[:6]
        x0 = x - i * scale_x
        y0 = y + j * scale_y
        keys = tags.get(34735)
        if keys:
            for index in range(keys[3]):
                key, _, _, value = keys[4 + 4 * index:8 + 4 * index]
                if key == 1025 and value == 2:
                    x0 -= scale_x / 2
                    y0 += scale_y / 2
        self.x0, self.y0 = x0, y0
        self.dx, self.dy = scale_x, scale_y

    def _get(self, offset, length):
        if offset + length <= len(self._head):
            return self._head[offset:offset + length]
        return self.src.read(offset, length)

    def _decode_block(self, index):
        data = self.src.read(self.offsets[index], self.counts[index])
        if self.compression in (8, 32946):
            data = zlib.decompress(data)
        tile_height, tile_width = self.tile_height, self.tile_width
        if self.predictor == 3:
            array = np.frombuffer(data, dtype=np.uint8).reshape(tile_height, tile_width * 4)
            array = np.cumsum(array, axis=1, dtype=np.uint8)
            array = array.reshape(tile_height, 4, tile_width).swapaxes(1, 2)
            return (
                np.ascontiguousarray(array)
                .view(">f4")
                .reshape(tile_height, tile_width)
                .astype(np.float32)
            )
        return (
            np.frombuffer(data, dtype=self.endian + "f4")
            .reshape(tile_height, tile_width)
            .astype(np.float32)
        )

    def read_window(self, c0, c1, r0, r1):
        tile_width, tile_height = self.tile_width, self.tile_height
        tc0, tc1 = c0 // tile_width, (c1 - 1) // tile_width
        tr0, tr1 = r0 // tile_height, (r1 - 1) // tile_height
        output = np.empty(
            (
                (tr1 - tr0 + 1) * tile_height,
                (tc1 - tc0 + 1) * tile_width,
            ),
            np.float32,
        )
        for tr in range(tr0, tr1 + 1):
            for tc in range(tc0, tc1 + 1):
                block = self._decode_block(tr * self.tiles_across + tc)
                output[
                    (tr - tr0) * tile_height:(tr - tr0 + 1) * tile_height,
                    (tc - tc0) * tile_width:(tc - tc0 + 1) * tile_width,
                ] = block
        row_offset, col_offset = tr0 * tile_height, tc0 * tile_width
        output = output[:self.height - row_offset, :self.width - col_offset]
        output[~np.isfinite(output) | (output < -9000)] = 0.0
        return output, row_offset, col_offset


@dataclass
class _Win:
    arr: np.ndarray
    r0: int
    c0: int
    x0: float
    y0: float
    dx: float
    dy: float


class Dem:
    def __init__(self, windows):
        self.windows = windows

    def sample(self, lons, lats):
        lons = np.asarray(lons, dtype=float)
        lats = np.asarray(lats, dtype=float)
        output = np.zeros(lons.shape)
        lat_indices = np.floor(lats).astype(int)
        lon_indices = np.floor(lons).astype(int)
        for (lat_i, lon_i), window in self.windows.items():
            mask = (lat_indices == lat_i) & (lon_indices == lon_i)
            if not mask.any():
                continue
            cols = (lons[mask] - window.x0) / window.dx - 0.5 - window.c0
            rows = (window.y0 - lats[mask]) / window.dy - 0.5 - window.r0
            output[mask] = map_coordinates(
                window.arr,
                [rows, cols],
                order=1,
                mode="nearest",
            )
        return output


def tile_path(base, lat_i, lon_i):
    """Return the GLO-30 tile URL for its southwest corner."""
    ns = "N" if lat_i >= 0 else "S"
    ew = "E" if lon_i >= 0 else "W"
    name = (
        f"Copernicus_DSM_COG_10_{ns}{abs(lat_i):02d}_00_"
        f"{ew}{abs(lon_i):03d}_00_DEM"
    )
    return f"{base.rstrip('/')}/{name}/{name}.tif"


def load_dem(lat, lon, max_dist, base=AWS_BASE):
    dlat = max_dist / M_PER_DEG * 1.05
    dlon = dlat / max(math.cos(math.radians(lat)), 0.01)
    south, north = lat - dlat, lat + dlat
    west, east = lon - dlon, lon + dlon
    if west < -180 or east > 180 or south < -90 or north > 90:
        raise ValueError("Area extends across the date line or a pole; this is unsupported.")

    windows = {}
    for lat_i in range(math.floor(south), math.floor(north) + 1):
        for lon_i in range(math.floor(west), math.floor(east) + 1):
            path = tile_path(base, lat_i, lon_i)
            try:
                cog = CogTile(path)
            except FileNotFoundError:
                print(f"Notice: missing tile (possibly sea): {path}", file=sys.stderr)
                continue
            c0 = max(0, math.floor((west - cog.x0) / cog.dx) - 1)
            c1 = min(cog.width, math.ceil((east - cog.x0) / cog.dx) + 1)
            r0 = max(0, math.floor((cog.y0 - north) / cog.dy) - 1)
            r1 = min(cog.height, math.ceil((cog.y0 - south) / cog.dy) + 1)
            if c1 <= c0 or r1 <= r0:
                continue
            array, row_offset, col_offset = cog.read_window(c0, c1, r0, r1)
            windows[(lat_i, lon_i)] = _Win(
                array,
                row_offset,
                col_offset,
                cog.x0,
                cog.y0,
                cog.dx,
                cog.dy,
            )
    if not windows:
        raise RuntimeError("No DEM tiles could be read (network unavailable or location over sea).")
    return Dem(windows)


def horizon_from_dem(
    dem,
    lat,
    lon,
    max_dist=50_000.0,
    az_step=1.0,
    dist_step=30.0,
    observer_height=0.0,
):
    """Trace rays and return (azimuth, horizon elevation) pairs in degrees."""
    geod = Geod(ellps="WGS84")
    observer_height_m = float(dem.sample([lon], [lat])[0]) + observer_height
    distances = np.arange(dist_step, max_dist + dist_step, dist_step)
    curvature = distances**2 / (2 * R_EARTH) * (1 - K_REFRACTION)

    result = []
    for index in range(int(round(360.0 / az_step))):
        azimuth = round(index * az_step, 6)
        lons, lats, _ = geod.fwd(
            np.full_like(distances, lon),
            np.full_like(distances, lat),
            np.full_like(distances, azimuth),
            distances,
        )
        heights = dem.sample(lons, lats)
        angles = np.arctan2(heights - observer_height_m - curvature, distances)
        result.append((float(azimuth), float(np.degrees(angles.max()))))
    return result


def horizon_profile(
    lat,
    lon,
    max_dist=50_000.0,
    az_step=1.0,
    observer_height=0.0,
    base=AWS_BASE,
):
    dem = load_dem(lat, lon, max_dist, base)
    return horizon_from_dem(
        dem,
        lat,
        lon,
        max_dist,
        az_step,
        observer_height=observer_height,
    )


def to_pvgis_convention(profile):
    """Convert north-clockwise azimuth to PVGIS convention."""
    return sorted((azimuth - 180.0, height) for azimuth, height in profile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lat", type=float)
    parser.add_argument("lon", type=float)
    parser.add_argument("--max-dist", type=float, default=50_000)
    parser.add_argument("--az-step", type=float, default=1.0)
    parser.add_argument("--height", type=float, default=0.0)
    parser.add_argument("--pvgis", action="store_true")
    parser.add_argument("--tile-base", default=AWS_BASE)
    parser.add_argument("--out", default="horizon.csv")
    args = parser.parse_args()

    profile = horizon_profile(
        args.lat,
        args.lon,
        args.max_dist,
        args.az_step,
        args.height,
        args.tile_base,
    )
    if args.pvgis:
        profile = to_pvgis_convention(profile)

    with open(args.out, "w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["azimuth_deg", "horizon_elevation_deg"])
        writer.writerows(profile)
    print(f"Wrote {len(profile)} values to {args.out}")


if __name__ == "__main__":
    main()
