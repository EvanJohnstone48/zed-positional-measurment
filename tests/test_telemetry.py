from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from zed_positional_measurement.models import FrameTelemetryRecord
from zed_positional_measurement.telemetry import TelemetryProvider, TelemetrySample


def _make_sample(
    wall_time_ns: int = 1_000_000_000,
    heading_rad: float | None = 1.57,
    gps_lat_deg: float | None = 49.2,
    mag_x: float | None = 0.1,
) -> TelemetrySample:
    return TelemetrySample(
        wall_time_ns=wall_time_ns,
        px4_timestamp_us=wall_time_ns // 1000,
        heading_rad=heading_rad,
        heading_var=0.01,
        heading_good_for_control=True,
        gps_lat_deg=gps_lat_deg,
        gps_lon_deg=-123.1,
        gps_alt_m=100.0,
        gps_eph=1.2,
        gps_epv=2.3,
        gps_fix_type=3,
        gps_hdop=0.8,
        gps_satellites_used=12,
        mag_x_gauss=mag_x,
        mag_y_gauss=0.2,
        mag_z_gauss=0.3,
        imu_gyro_rad=(0.01, 0.02, 0.03),
        imu_accel_m_s2=(0.0, 0.0, -9.81),
    )


def _write_samples(path: Path, samples: list[TelemetrySample]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for sample in samples:
            handle.write(json.dumps(sample.to_dict(), sort_keys=True))
            handle.write("\n")


class TelemetrySampleTests(unittest.TestCase):
    def test_round_trip_full(self) -> None:
        sample = _make_sample()
        data = sample.to_dict()
        restored = TelemetrySample.from_dict(data)
        self.assertEqual(sample, restored)

    def test_round_trip_with_none_fields(self) -> None:
        sample = TelemetrySample(
            wall_time_ns=500,
            px4_timestamp_us=0,
            heading_rad=None,
            heading_var=None,
            heading_good_for_control=None,
            gps_lat_deg=None,
            gps_lon_deg=None,
            gps_alt_m=None,
            gps_eph=None,
            gps_epv=None,
            gps_fix_type=None,
            gps_hdop=None,
            gps_satellites_used=None,
            mag_x_gauss=None,
            mag_y_gauss=None,
            mag_z_gauss=None,
            imu_gyro_rad=None,
            imu_accel_m_s2=None,
        )
        data = sample.to_dict()
        restored = TelemetrySample.from_dict(data)
        self.assertEqual(sample, restored)

    def test_to_frame_telemetry(self) -> None:
        sample = _make_sample()
        record = sample.to_frame_telemetry(alignment_offset_ns=5000)
        self.assertEqual(record.heading_rad, sample.heading_rad)
        self.assertEqual(record.gps_lat_deg, sample.gps_lat_deg)
        self.assertEqual(record.mag_xyz_gauss, (0.1, 0.2, 0.3))
        self.assertEqual(record.imu_gyro_rad, sample.imu_gyro_rad)
        self.assertEqual(record.alignment_offset_ns, 5000)

    def test_to_frame_telemetry_with_partial_mag(self) -> None:
        sample = _make_sample(mag_x=None)
        record = sample.to_frame_telemetry(alignment_offset_ns=0)
        self.assertIsNone(record.mag_xyz_gauss)


class FrameTelemetryRecordTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        record = FrameTelemetryRecord(
            heading_rad=1.57,
            heading_var=0.01,
            heading_good_for_control=True,
            gps_lat_deg=49.2,
            gps_lon_deg=-123.1,
            gps_alt_m=100.0,
            gps_eph=1.2,
            gps_epv=2.3,
            gps_fix_type=3,
            gps_hdop=0.8,
            gps_satellites_used=12,
            mag_xyz_gauss=(0.1, 0.2, 0.3),
            imu_gyro_rad=(0.01, 0.02, 0.03),
            imu_accel_m_s2=(0.0, 0.0, -9.81),
            alignment_offset_ns=5000,
        )
        data = record.to_dict()
        restored = FrameTelemetryRecord.from_dict(data)
        self.assertEqual(record, restored)

    def test_round_trip_all_none(self) -> None:
        record = FrameTelemetryRecord(
            heading_rad=None,
            heading_var=None,
            heading_good_for_control=None,
            gps_lat_deg=None,
            gps_lon_deg=None,
            gps_alt_m=None,
            gps_eph=None,
            gps_epv=None,
            gps_fix_type=None,
            gps_hdop=None,
            gps_satellites_used=None,
            mag_xyz_gauss=None,
            imu_gyro_rad=None,
            imu_accel_m_s2=None,
            alignment_offset_ns=0,
        )
        data = record.to_dict()
        restored = FrameTelemetryRecord.from_dict(data)
        self.assertEqual(record, restored)


class TelemetryProviderTests(unittest.TestCase):
    def test_returns_none_when_path_is_none(self) -> None:
        provider = TelemetryProvider(None)
        self.assertIsNone(provider.get(1_000_000_000))

    def test_returns_none_when_file_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.jsonl"
            path.write_text("", encoding="utf-8")
            provider = TelemetryProvider(path, timeout_ms=0)
            self.assertIsNone(provider.get(1_000_000_000))

    def test_exact_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.jsonl"
            samples = [_make_sample(wall_time_ns=1000), _make_sample(wall_time_ns=2000), _make_sample(wall_time_ns=3000)]
            _write_samples(path, samples)
            provider = TelemetryProvider(path, timeout_ms=0)
            result = provider.get(2000)
            self.assertIsNotNone(result)
            self.assertEqual(result.alignment_offset_ns, 0)

    def test_nearest_match_between_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.jsonl"
            samples = [_make_sample(wall_time_ns=1000), _make_sample(wall_time_ns=3000)]
            _write_samples(path, samples)
            provider = TelemetryProvider(path, timeout_ms=0)
            # Closer to 1000
            result = provider.get(1400)
            self.assertIsNotNone(result)
            self.assertEqual(result.alignment_offset_ns, 400)
            # Closer to 3000
            result = provider.get(2600)
            self.assertIsNotNone(result)
            self.assertEqual(result.alignment_offset_ns, 400)

    def test_returns_none_when_offset_exceeds_max(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.jsonl"
            samples = [_make_sample(wall_time_ns=1000)]
            _write_samples(path, samples)
            provider = TelemetryProvider(path, timeout_ms=0, max_alignment_offset_ns=100)
            result = provider.get(5000)
            self.assertIsNone(result)

    def test_timestamp_before_all_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.jsonl"
            samples = [_make_sample(wall_time_ns=1000), _make_sample(wall_time_ns=2000)]
            _write_samples(path, samples)
            provider = TelemetryProvider(path, timeout_ms=0, max_alignment_offset_ns=1_000_000)
            result = provider.get(500)
            self.assertIsNotNone(result)
            self.assertEqual(result.alignment_offset_ns, 500)

    def test_timestamp_after_all_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.jsonl"
            samples = [_make_sample(wall_time_ns=1000), _make_sample(wall_time_ns=2000)]
            _write_samples(path, samples)
            provider = TelemetryProvider(path, timeout_ms=0, max_alignment_offset_ns=1_000_000)
            result = provider.get(2500)
            self.assertIsNotNone(result)
            self.assertEqual(result.alignment_offset_ns, 500)

    def test_single_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.jsonl"
            samples = [_make_sample(wall_time_ns=1000)]
            _write_samples(path, samples)
            provider = TelemetryProvider(path, timeout_ms=0, max_alignment_offset_ns=1_000_000)
            result = provider.get(1050)
            self.assertIsNotNone(result)
            self.assertEqual(result.alignment_offset_ns, 50)

    def test_returns_none_when_file_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonexistent.jsonl"
            provider = TelemetryProvider(path, timeout_ms=0)
            self.assertIsNone(provider.get(1000))


if __name__ == "__main__":
    unittest.main()
