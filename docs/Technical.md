# Technical Design

## Status

This document describes the SVO-first streaming architecture.

The pipeline records SVO2 segments live, then background workers replay them to produce streaming output:

- Worker 1 (external NN detector) replays SVO2 and writes detection JSONL
- Worker 2 (this repo) replays SVO2 for tracking/depth/planes, reads Worker 1's detections, and streams frame objects to `frames.jsonl`
- frame-level `planes[]`, per-paper `plane_id`, fixed 3x3 scene probes, configurable floor-plane inclusion (off by default)

## Architecture

The system is organized around a thin orchestration layer over the ZED SDK.

Core principle:

- ZED owns camera I/O, depth, pose estimation, and plane queries (all via SVO2 replay).
- The external detector (Worker 1) owns paper center inference, replaying SVO2 segments.
- This repo (Worker 2) owns session orchestration, frame-level plane discovery, paper-to-plane association, streaming append-only handoff to Lucas, and SVO recording.
- Lucas owns clustering, inferred corners, and final text-file generation.

## Runtime Topology

All major components run on the Jetson onboard the drone:

- ZED live capture (records SVO2 segments)
- Telemetry collector (background thread subscribing to PX4 ROS2 topics, writes `telemetry/telemetry.jsonl`)
- Worker 1: external YOLO + Roboflow detector (replays SVO2 for inference)
- Worker 2: this measurement pipeline (replays SVO2 for tracking/depth/planes, reads telemetry sidecar)
- Lucas's clustering code (tails streaming frames.jsonl)

## Main Modules

- `src/zed_positional_measurement/sdk.py`
  - ZED adapter
  - live camera open/close, SVO camera open/close
  - tracking enable/disable
  - SVO recording enable/disable
  - pose, point, depth, and plane extraction
- `src/zed_positional_measurement/pipeline.py`
  - SVO-first session orchestration
  - segment recording, background worker processing
  - per-frame streaming emission to `frames.jsonl`
  - frame packaging with planes and paper-to-plane association
- `src/zed_positional_measurement/providers.py`
  - `SegmentJsonlPaperProvider`: reads pre-existing detection JSONL (batch mode)
  - `TailingPaperProvider`: tails Worker 1's detection JSONL with poll/wait (streaming mode)
- `src/zed_positional_measurement/storage.py`
  - session directory creation
  - append-only stream persistence (`append_jsonl`)
  - batch JSONL writes and segment cache management
  - metadata writes
- `src/zed_positional_measurement/models.py`
  - frame payload and per-paper measurement types
- `src/zed_positional_measurement/telemetry.py`
  - PX4 telemetry collector (ROS2 subscriber → JSONL sidecar during recording)
  - telemetry provider (reads sidecar during SVO2 replay, binary-search time alignment)
- `src/zed_positional_measurement/metrics.py`
  - offline tracking and measurement metrics

## Session Layout

```text
runs/<session_id>/
  session.json
  capture/
    session.svo2
  stream/
    frames.jsonl
  telemetry/
    telemetry.jsonl
  logs/
    events.jsonl
```

Design intent:

- `capture/` stores the parallel SVO2 recording when `recording.enable_svo_recording` is enabled.
- `stream/frames.jsonl` is the live append-only handoff contract for Lucas.
- `logs/` stores operational events and errors for debugging.

## SVO-First Streaming Flow

### 1. Recording (Live Thread)

The recording thread:

- opens the ZED camera with:
  - `RIGHT_HANDED_Z_UP_X_FORWARD`
  - meter units
  - configured resolution/fps/depth mode
- enables SVO2 recording
- grabs frames and records to SVO2 in 20-second segments
- pushes closed segment IDs onto the processing queue
- does no measurement processing — all compute is deferred to workers

### 2. Worker 1 — NN Detector (External)

For each closed SVO2 segment:

1. replay the segment from the SVO2 file
2. run YOLO/Roboflow inference on each frame
3. write one JSONL line per frame with: frame_idx, paper center pixels, colors, confidences
4. output file: `<detector_output_dir>/<segment_id>.jsonl`

Worker 1 is external to this repo and processes segments at its own pace.

### 3. Worker 2 — Measurement Pipeline (This Repo)

For each closed SVO2 segment:

1. replay the segment from the SVO2 file
2. enable positional tracking on the SVO replay
3. for each frame:
   a. grab frame from the SVO replay
   b. get pose/tracking state from ZED
   c. read paper detections for this frame from Worker 1's JSONL (waits/polls if Worker 1 is still writing)
   d. for each paper detection:
      - use the detector center pixel
      - sample center-pixel depth
      - sample the world point at that center pixel
      - query `find_plane_at_hit` at the same pixel
   e. run additional `find_plane_at_hit` queries at 9 fixed scene probe pixels
   f. optionally run `find_floor_plane` if floor-plane context is needed
   g. deduplicate successful plane results into one frame-level `planes` list
   h. assign each paper a `plane_id` pointing at the matching plane
   i. package one frame object
   j. **immediately append** that frame object to `stream/frames.jsonl`
4. also write segment caches (poses, measurements, frames) for offline use

### 4. Stop Session

The session controller:

- stops SVO2 recording
- closes the camera
- signals the background worker to finish remaining segments
- the streaming `frames.jsonl` is already populated by the time all segments are processed

## Tracking Modes

Recommended live default:

- `vslam_map`

Reason:

- it uses live visual SLAM with area memory and best matches the need for minimizing drift over the flight
- `GEN_3` is the recommended ZED tracking mode for modern use

Other modes:

- `vio`
  - fallback if mapping behavior is not wanted
- `gnss_fusion`
  - reserved for future RTK/GNSS integration

Recommended settings:

- positional tracking mode: `GEN_3`
- `enable_imu_fusion = true`
- `set_gravity_as_origin = true`
- `set_floor_as_origin = false`
- `enable_pose_smoothing = false`
- `enable_2d_ground_mode = false`

## Detector Boundary

The detector (Worker 1) is intentionally outside this repo.

Integration method: **JSONL file handoff**. Worker 1 writes one JSONL file per segment to a configured output directory. Worker 2 tails those files using `TailingPaperProvider`, polling for new lines when it is ahead of Worker 1.

Worker 1 output per frame:

- frame_idx
- paper center pixel (bbox_xyxy)
- paper color/class
- confidence

Configuration: `streaming.detector_output_dir`, `streaming.detector_poll_interval_ms`, `streaming.detector_timeout_ms`.

## Measurement Flow

### Plane Discovery

The official ZED plane-detection API is hit-based, not full-scene enumeration.

That means:

- `find_plane_at_hit` returns the support plane for a specific target pixel
- `find_floor_plane` is a separate floor-specific query
- the SDK does not expose a native "return all visible planes in this frame" call

So the feasible design for multiple planes per frame is:

1. query each paper center with `find_plane_at_hit`
2. query a small fixed set of additional scene probe pixels each frame
3. optionally query the floor plane
4. deduplicate successful results into a frame-level `planes` array

Implemented default:

- 9 extra scene probes
- fixed 3x3 grid using normalized image-space probe centers
- `include_floor_plane = false`
- simple dedupe using plane-normal angle and plane-center distance thresholds

Consequence:

- if no probe lands on a visible wall, that wall will not appear in the frame payload
- getting multiple walls per frame is feasible, but it depends on the probe policy this repo chooses

### Paper Measurements

For each detected paper center:

1. read the detector center pixel
2. sample center-pixel depth from ZED
3. sample center-pixel world point from ZED
4. run `find_plane_at_hit` at that pixel
5. if the plane query succeeds, associate the result with one item in the frame-level `planes` array
6. store that plane link as `plane_id` in the paper measurement
7. emit the per-paper measurement inside the frame payload

### Corners

This repo does not calculate corners.

Instead:

- this repo emits paper measurements, frame-level planes, and paper-to-plane links
- Lucas infers corners downstream from repeated measurements and plane normals

## Output Contract

Primary live contract:

```text
runs/<session_id>/stream/frames.jsonl
```

Rules:

- append-only
- one JSON object per frame
- Lucas reads this file live on the same Jetson

## Quality Model

Each per-paper measurement carries quality flags.

Current intended flags:

- `pose_invalid`
- `point_invalid`
- `plane_unavailable`
- `depth_invalid`
- `clean`

`clean` means:

- pose is valid
- a world point exists
- depth exists

## Failure Strategy

- if tracking is not `OK`, still emit the frame with explicit invalid/weak quality flags
- if a paper-center plane query fails, still emit the paper measurement with `plane_unavailable` and no `plane_id`
- if the extra scene probes fail to find other walls, still emit the frame with whatever planes were found
- if the detector returns no papers for a frame, still emit the frame object with an empty papers list
- if the detector boundary stalls, the live ZED loop should not block indefinitely

## Recommended Operator Flow

1. Prepare `config.json` with `streaming.detector_output_dir` pointing to where Worker 1 will write.
2. Start the external detector process (Worker 1).
3. Start the measurement session from the button/UI or service boundary.
4. Let the drone fly while the system:
   - records SVO2 segments (live thread)
   - Worker 1 replays segments and writes detection JSONL
   - Worker 2 replays segments for tracking/depth/planes, reads detections, streams `frames.jsonl`
5. Stop the session from the same control boundary.
6. Inspect:
   - `runs/<session_id>/stream/frames.jsonl` (streaming output, populated during flight)
   - `runs/<session_id>/segments/` (SVO2 recordings)
   - `runs/<session_id>/cache/` (segment-level caches)
   - `runs/<session_id>/logs/`

## What To Inspect First When Results Look Wrong

- `tracking_state`
- `tracking_confidence`
- `planes`
- `papers[].plane_id`
- `point_world_xyz`
- `depth_m`
- `plane_query_status`
- `planes[].normal_world_xyz`
- `quality_flags`
- frame-to-detector alignment issues

## Known Limitations

- the ZED SDK plane API does not natively enumerate every visible plane in a frame
- the current 3x3 probe grid and dedupe thresholds are configurable but still need hardware tuning
- the exact JSON payload may be refined after confirming the minimum fields Lucas needs
- `gnss_fusion` is not yet wired (GNSS data can be stored as SVO2 sidecar for future replay)
