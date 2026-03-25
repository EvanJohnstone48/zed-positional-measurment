from __future__ import annotations

import bisect
import json
import logging
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import TelemetryConfig
from .models import FrameTelemetryRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelemetrySample:
    """A single timestamped telemetry snapshot combining all PX4 sources."""

    wall_time_ns: int
    px4_timestamp_us: int
    heading_rad: float | None
    heading_var: float | None
    heading_good_for_control: bool | None
    gps_lat_deg: float | None
    gps_lon_deg: float | None
    gps_alt_m: float | None
    gps_eph: float | None
    gps_epv: float | None
    gps_fix_type: int | None
    gps_hdop: float | None
    gps_satellites_used: int | None
    mag_x_gauss: float | None
    mag_y_gauss: float | None
    mag_z_gauss: float | None
    imu_gyro_rad: tuple[float, float, float] | None
    imu_accel_m_s2: tuple[float, float, float] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_time_ns": self.wall_time_ns,
            "px4_timestamp_us": self.px4_timestamp_us,
            "heading_rad": self.heading_rad,
            "heading_var": self.heading_var,
            "heading_good_for_control": self.heading_good_for_control,
            "gps_lat_deg": self.gps_lat_deg,
            "gps_lon_deg": self.gps_lon_deg,
            "gps_alt_m": self.gps_alt_m,
            "gps_eph": self.gps_eph,
            "gps_epv": self.gps_epv,
            "gps_fix_type": self.gps_fix_type,
            "gps_hdop": self.gps_hdop,
            "gps_satellites_used": self.gps_satellites_used,
            "mag_x_gauss": self.mag_x_gauss,
            "mag_y_gauss": self.mag_y_gauss,
            "mag_z_gauss": self.mag_z_gauss,
            "imu_gyro_rad": list(self.imu_gyro_rad) if self.imu_gyro_rad else None,
            "imu_accel_m_s2": list(self.imu_accel_m_s2) if self.imu_accel_m_s2 else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TelemetrySample":
        return cls(
            wall_time_ns=int(data["wall_time_ns"]),
            px4_timestamp_us=int(data["px4_timestamp_us"]),
            heading_rad=float(data["heading_rad"]) if data.get("heading_rad") is not None else None,
            heading_var=float(data["heading_var"]) if data.get("heading_var") is not None else None,
            heading_good_for_control=bool(data["heading_good_for_control"]) if data.get("heading_good_for_control") is not None else None,
            gps_lat_deg=float(data["gps_lat_deg"]) if data.get("gps_lat_deg") is not None else None,
            gps_lon_deg=float(data["gps_lon_deg"]) if data.get("gps_lon_deg") is not None else None,
            gps_alt_m=float(data["gps_alt_m"]) if data.get("gps_alt_m") is not None else None,
            gps_eph=float(data["gps_eph"]) if data.get("gps_eph") is not None else None,
            gps_epv=float(data["gps_epv"]) if data.get("gps_epv") is not None else None,
            gps_fix_type=int(data["gps_fix_type"]) if data.get("gps_fix_type") is not None else None,
            gps_hdop=float(data["gps_hdop"]) if data.get("gps_hdop") is not None else None,
            gps_satellites_used=int(data["gps_satellites_used"]) if data.get("gps_satellites_used") is not None else None,
            mag_x_gauss=float(data["mag_x_gauss"]) if data.get("mag_x_gauss") is not None else None,
            mag_y_gauss=float(data["mag_y_gauss"]) if data.get("mag_y_gauss") is not None else None,
            mag_z_gauss=float(data["mag_z_gauss"]) if data.get("mag_z_gauss") is not None else None,
            imu_gyro_rad=tuple(float(v) for v in data["imu_gyro_rad"]) if data.get("imu_gyro_rad") is not None else None,  # type: ignore[assignment]
            imu_accel_m_s2=tuple(float(v) for v in data["imu_accel_m_s2"]) if data.get("imu_accel_m_s2") is not None else None,  # type: ignore[assignment]
        )

    def to_frame_telemetry(self, alignment_offset_ns: int) -> FrameTelemetryRecord:
        mag_xyz = None
        if self.mag_x_gauss is not None and self.mag_y_gauss is not None and self.mag_z_gauss is not None:
            mag_xyz = (self.mag_x_gauss, self.mag_y_gauss, self.mag_z_gauss)
        return FrameTelemetryRecord(
            heading_rad=self.heading_rad,
            heading_var=self.heading_var,
            heading_good_for_control=self.heading_good_for_control,
            gps_lat_deg=self.gps_lat_deg,
            gps_lon_deg=self.gps_lon_deg,
            gps_alt_m=self.gps_alt_m,
            gps_eph=self.gps_eph,
            gps_epv=self.gps_epv,
            gps_fix_type=self.gps_fix_type,
            gps_hdop=self.gps_hdop,
            gps_satellites_used=self.gps_satellites_used,
            mag_xyz_gauss=mag_xyz,
            imu_gyro_rad=self.imu_gyro_rad,
            imu_accel_m_s2=self.imu_accel_m_s2,
            alignment_offset_ns=alignment_offset_ns,
        )


class TelemetryCollector:
    """Subscribes to PX4 ROS2 topics and writes telemetry JSONL sidecar.

    Runs rclpy in a background thread. Resilient: if rclpy is unavailable
    or topics are not publishing, it produces an empty file and does not block.
    """

    def __init__(self, output_path: Path, config: TelemetryConfig) -> None:
        self.output_path = output_path
        self.config = config
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run(self) -> None:
        try:
            import rclpy
            from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
        except ImportError:
            logger.warning("rclpy not available — telemetry collector disabled")
            return

        try:
            from px4_msgs.msg import (
                VehicleLocalPosition,
                VehicleGlobalPosition,
                SensorGps,
                SensorMag,
                SensorCombined,
            )
        except ImportError:
            logger.warning("px4_msgs not available — telemetry collector disabled")
            return

        context = rclpy.Context()
        try:
            rclpy.init(context=context)
        except Exception:
            logger.warning("rclpy.init failed — telemetry collector disabled", exc_info=True)
            return

        try:
            node = rclpy.create_node("zed_telemetry_collector", context=context)
            qos = QoSProfile(
                reliability=ReliabilityPolicy.BEST_EFFORT,
                history=HistoryPolicy.KEEP_LAST,
                depth=1,
            )

            latest_local_pos = [None]
            latest_global_pos = [None]
            latest_sensor_gps = [None]
            latest_sensor_mag = [None]
            latest_sensor_combined = [None]

            topics = self.config.topics

            node.create_subscription(
                VehicleLocalPosition,
                topics.get("local_position", "/fmu/out/vehicle_local_position"),
                lambda msg: latest_local_pos.__setitem__(0, msg),
                qos,
            )
            node.create_subscription(
                VehicleGlobalPosition,
                topics.get("global_position", "/fmu/out/vehicle_global_position"),
                lambda msg: latest_global_pos.__setitem__(0, msg),
                qos,
            )
            node.create_subscription(
                SensorGps,
                topics.get("sensor_gps", "/fmu/out/sensor_gps"),
                lambda msg: latest_sensor_gps.__setitem__(0, msg),
                qos,
            )
            node.create_subscription(
                SensorMag,
                topics.get("sensor_mag", "/fmu/out/sensor_mag"),
                lambda msg: latest_sensor_mag.__setitem__(0, msg),
                qos,
            )
            node.create_subscription(
                SensorCombined,
                topics.get("sensor_combined", "/fmu/out/sensor_combined"),
                lambda msg: latest_sensor_combined.__setitem__(0, msg),
                qos,
            )

            period_s = 1.0 / max(1, self.config.snapshot_rate_hz)

            def snapshot_callback() -> None:
                wall_ns = time.time_ns()
                local_pos = latest_local_pos[0]
                global_pos = latest_global_pos[0]
                sensor_gps = latest_sensor_gps[0]
                sensor_mag = latest_sensor_mag[0]
                sensor_combined = latest_sensor_combined[0]

                px4_ts = 0
                heading_rad = None
                heading_var = None
                heading_good = None
                if local_pos is not None:
                    px4_ts = int(local_pos.timestamp)
                    heading_rad = float(local_pos.heading)
                    heading_var = float(local_pos.heading_var)
                    heading_good = bool(local_pos.heading_good_for_control)

                gps_lat = None
                gps_lon = None
                gps_alt = None
                gps_eph = None
                gps_epv = None
                if global_pos is not None:
                    gps_lat = float(global_pos.lat)
                    gps_lon = float(global_pos.lon)
                    gps_alt = float(global_pos.alt)
                    gps_eph = float(global_pos.eph)
                    gps_epv = float(global_pos.epv)

                gps_fix_type = None
                gps_hdop = None
                gps_satellites = None
                if sensor_gps is not None:
                    gps_fix_type = int(sensor_gps.fix_type)
                    gps_hdop = float(sensor_gps.hdop)
                    gps_satellites = int(sensor_gps.satellites_used)

                mag_x = None
                mag_y = None
                mag_z = None
                if sensor_mag is not None:
                    mag_x = float(sensor_mag.x)
                    mag_y = float(sensor_mag.y)
                    mag_z = float(sensor_mag.z)

                gyro = None
                accel = None
                if sensor_combined is not None:
                    gyro = (
                        float(sensor_combined.gyro_rad[0]),
                        float(sensor_combined.gyro_rad[1]),
                        float(sensor_combined.gyro_rad[2]),
                    )
                    accel = (
                        float(sensor_combined.accelerometer_m_s2[0]),
                        float(sensor_combined.accelerometer_m_s2[1]),
                        float(sensor_combined.accelerometer_m_s2[2]),
                    )

                sample = TelemetrySample(
                    wall_time_ns=wall_ns,
                    px4_timestamp_us=px4_ts,
                    heading_rad=heading_rad,
                    heading_var=heading_var,
                    heading_good_for_control=heading_good,
                    gps_lat_deg=gps_lat,
                    gps_lon_deg=gps_lon,
                    gps_alt_m=gps_alt,
                    gps_eph=gps_eph,
                    gps_epv=gps_epv,
                    gps_fix_type=gps_fix_type,
                    gps_hdop=gps_hdop,
                    gps_satellites_used=gps_satellites,
                    mag_x_gauss=mag_x,
                    mag_y_gauss=mag_y,
                    mag_z_gauss=mag_z,
                    imu_gyro_rad=gyro,
                    imu_accel_m_s2=accel,
                )
                line = json.dumps(sample.to_dict(), sort_keys=True) + "\n"
                with self.output_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line)
                    handle.flush()

            node.create_timer(period_s, snapshot_callback)

            while not self._stop_event.is_set():
                rclpy.spin_once(node, timeout_sec=0.1)

            node.destroy_node()
        finally:
            try:
                rclpy.shutdown(context=context)
            except Exception:
                pass


class TelemetryProvider:
    """Reads the telemetry JSONL sidecar and provides nearest-match lookup by timestamp.

    Supports both pre-existing files (batch replay) and tailing a growing file (streaming mode).
    """

    def __init__(
        self,
        telemetry_path: Path | None,
        *,
        poll_interval_ms: int = 100,
        timeout_ms: int = 10000,
        max_alignment_offset_ns: int = 100_000_000,
    ) -> None:
        self.telemetry_path = telemetry_path
        self.poll_interval_ms = poll_interval_ms
        self.timeout_ms = timeout_ms
        self.max_alignment_offset_ns = max_alignment_offset_ns
        self._timestamps: list[int] = []
        self._samples: list[TelemetrySample] = []
        self._file_offset: int = 0

    def get(self, timestamp_ns: int) -> FrameTelemetryRecord | None:
        if self.telemetry_path is None:
            return None

        # Try to find a match in already-loaded data
        result = self._lookup(timestamp_ns)
        if result is not None:
            return result

        # Poll for new lines (streaming mode)
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        while time.monotonic() < deadline:
            new_count = self._read_new_lines()
            if new_count > 0:
                result = self._lookup(timestamp_ns)
                if result is not None:
                    return result
            time.sleep(self.poll_interval_ms / 1000.0)

        # One final attempt after timeout
        self._read_new_lines()
        return self._lookup(timestamp_ns)

    def _lookup(self, timestamp_ns: int) -> FrameTelemetryRecord | None:
        if not self._timestamps:
            return None
        idx = bisect.bisect_left(self._timestamps, timestamp_ns)
        # Find nearest between idx-1 and idx
        best_idx = None
        best_offset = None
        for candidate in (idx - 1, idx):
            if 0 <= candidate < len(self._timestamps):
                offset = abs(self._timestamps[candidate] - timestamp_ns)
                if best_offset is None or offset < best_offset:
                    best_offset = offset
                    best_idx = candidate
        if best_idx is None or best_offset is None:
            return None
        if best_offset > self.max_alignment_offset_ns:
            return None
        return self._samples[best_idx].to_frame_telemetry(best_offset)

    def _read_new_lines(self) -> int:
        if self.telemetry_path is None or not self.telemetry_path.exists():
            return 0
        count = 0
        with self.telemetry_path.open("r", encoding="utf-8") as handle:
            handle.seek(self._file_offset)
            for line in handle:
                line = line.strip()
                if line:
                    sample = TelemetrySample.from_dict(json.loads(line))
                    self._timestamps.append(sample.wall_time_ns)
                    self._samples.append(sample)
                    count += 1
            self._file_offset = handle.tell()
        return count
