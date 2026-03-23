# zed-positional-measurement

ZED-first spatial measurement pipeline intended for:

- live ZED tracking while the drone is flying
- optional parallel SVO2 recording for audit/debugging/neural-net workflows
- live paper measurement from external detector center points
- live plane information and plane normals from the ZED SDK
- append-only per-frame JSON handoff to Lucas on the Jetson

The implementation should stay thin over the ZED SDK. ZED owns recording, pose, depth, and plane queries. This repo owns live measurement packaging and the handoff boundary to Lucas.

## Status

The runtime is still replay-first.

What is implemented now:

- processed and finalized frame outputs include top-level `planes[]`
- each paper output includes `plane_id`
- planes are built from paper-center plane queries plus a fixed 3x3 scene-probe grid
- floor-plane probing is configurable and off by default

What is still pending:

- live append-only frame emission during recording
- replacing the replay-first runtime path with the intended live-first service

## Docs

Detailed project docs live in [docs/README.md](docs/README.md):

- [docs/PRD.md](docs/PRD.md)
- [docs/Technical.md](docs/Technical.md)
- [docs/Operations.md](docs/Operations.md)
- [docs/Schema.md](docs/Schema.md)
- [docs/LucasHandoff.md](docs/LucasHandoff.md)
- [docs/Uncertainties.md](docs/Uncertainties.md)
- [docs/Validation.md](docs/Validation.md)

## Intended Layout

The target live-first layout is:

```text
runs/<session_id>/
  session.json
  capture/
    session.svo2
  stream/
    frames.jsonl
  logs/
    events.jsonl
```

`capture/session.svo2` is only written when `recording.enable_svo_recording` is `true`.

## Current Code Commands

These commands reflect the current replay-first code, not the intended final runtime:

Install in editable mode if you want the `zed-measure` command:

```bash
python -m pip install -e .
```

Record, process in the background, and finalize:

```bash
zed-measure run --config config.json
```

Record only:

```bash
zed-measure record --config config.json
```

Resume provisional processing:

```bash
zed-measure process runs/<session_id> --config config.json
```

Replay all segments with the final tracking mode and export:

```bash
zed-measure finalize runs/<session_id> --config config.json
```

Compute offline metrics:

```bash
zed-measure eval-tracking runs/<session_id>
zed-measure eval-measurements runs/<session_id> ground_truth.json
```

## Config

The config example below reflects the current code shape and will change during the live-first refactor.

Minimal external-detection config:

```json
{
  "recording": {
    "enable_svo_recording": true,
    "resolution": "HD1080",
    "fps": 30,
    "depth_mode": "NEURAL",
    "coordinate_system": "RIGHT_HANDED_Z_UP_X_FORWARD",
    "coordinate_units": "METER",
    "compression_mode": "H264",
    "segment_duration_s": 20
  },
  "tracking": {
    "mode": "vslam_map",
    "positional_tracking_mode": "GEN_3",
    "enable_imu_fusion": true,
    "set_gravity_as_origin": true,
    "set_floor_as_origin": false,
    "enable_pose_smoothing": false,
    "enable_2d_ground_mode": false
  },
  "paper": {
    "mode": "external_boxes",
    "external_detections_dir": "detections/papers"
  },
  "corners": {
    "detections_dir": "detections/corners",
    "patch_radius_px": 2
  },
  "plane_detection": {
    "enable_scene_probes": true,
    "scene_probe_points_normalized": [
      [0.1666666667, 0.1666666667],
      [0.5, 0.1666666667],
      [0.8333333333, 0.1666666667],
      [0.1666666667, 0.5],
      [0.5, 0.5],
      [0.8333333333, 0.5],
      [0.1666666667, 0.8333333333],
      [0.5, 0.8333333333],
      [0.8333333333, 0.8333333333]
    ],
    "include_floor_plane": false,
    "dedupe_normal_angle_deg": 10.0,
    "dedupe_center_distance_m": 0.4
  },
  "runtime": {
    "root_dir": "runs",
    "session_id": "demo-session",
    "detector_image_size": [640, 360]
  }
}
```

If you use `paper.mode = "native_yolo"`, set `paper.native_yolo_onnx_path`. The pipeline validates that before processing starts.

## Tests

The repo test suite uses a fake SDK adapter for deterministic non-hardware coverage:

```bash
python -m unittest discover -s tests -v
```

## Notes

- the docs in `docs/` should be treated as the source of truth for the upcoming live-first refactor
- replay processing now writes per-frame outputs with `planes[]` and `papers[].plane_id`
- finalized replay writes `runs/<session_id>/stream/frames.jsonl`
- Lucas's target runtime handoff is still one append-only JSON object per frame during flight
- this repo should emit paper measurements and plane information, not explicit corners
- `recording.enable_svo_recording` controls whether SVO capture is written; in the current replay-first code, `run/process/finalize` still require it to be `true`
