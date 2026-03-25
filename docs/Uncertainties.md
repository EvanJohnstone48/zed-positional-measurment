# Uncertainties

## Purpose

This document captures the remaining design questions for the ZED pipeline.

## Already Decided

- The system uses SVO-first streaming: live thread records SVO2, workers replay for processing.
- SVO recording is required for the pipeline to function.
- Lucas's code will run on the same Jetson on the drone.
- The external detector (Worker 1) is a YOLO + Roboflow process that is not part of this repo.
- This repo should not calculate corners itself.
- This repo should pass plane information and plane normals to Lucas.
- Use the detector center pixel for measurement.
- The handoff should be append-only, streaming per-frame to `frames.jsonl`.
- The handoff should be one JSON object per frame.
- Frame-level plane discovery should use:
  - `find_plane_at_hit` at each paper center
  - 9 extra fixed scene probes in a 3x3 normalized image grid
  - simple plane dedupe
  - `include_floor_plane = false` by default
- **Detector integration: JSONL file handoff.** Worker 1 writes one JSONL file per segment to a configured directory. Worker 2 tails those files with poll/wait via `TailingPaperProvider`.
- **GNSS fusion is compatible** with this architecture — GNSS data stored as SVO2 sidecar for future replay.
- **PX4 telemetry integration: decided.** A `TelemetryCollector` subscribes to existing ROS2 PX4 topics during recording and writes a per-session JSONL sidecar. Worker 2 reads the sidecar during SVO2 replay and attaches heading, GPS, magnetometer, and IMU data to each frame. Data source: existing AEAC2026 ROS2 workspace topics. Topic names are configurable via `telemetry.topics`.

## Open Questions For Matt

### 1. ~~Detector Integration Boundary~~ (Resolved)

Decided: JSONL file handoff between Worker 1 and Worker 2. Configured via `streaming.detector_output_dir`.

### 2. Detector Output Contract

Current uncertainty:

- We are assuming the detector returns all of the following, but this still needs confirmation:
  - frame id or timestamp
  - center pixel
  - paper color/class
  - confidence

Need to confirm:

- exact field names
- whether frame id and timestamp are both available
- whether the detector output is synchronized to the exact ZED frame grab

### 3. ~~Live Handoff File Contract~~ (Resolved)

Decided: one append-only per-session `frames.jsonl`, one JSON object per frame, streamed per-frame during processing.

Remaining optional question:

- whether a rolling `latest_frame.json` snapshot is also useful later

### 4. Exact Payload Lucas Needs

Current uncertainty:

- The instruction is that Lucas needs "all the info outlined earlier," but the exact minimum required payload is not locked.

Need to confirm whether Lucas needs:

- ZED pose for every frame
- paper center pixel for every detection
- per-paper depth
- per-paper world point
- per-paper plane normal
- full plane data beyond just normals
- tracking confidence / status
- camera timestamp

Important note:

- Full frame depth should not be passed as JSON unless Matt explicitly wants that. It is too heavy for the live append-only contract.

### 5. Ownership Of Revised World State

Current uncertainty:

- The system can revise estimates over time, but it is not yet locked whether this repo should maintain a live best-estimate world state or whether Lucas should own all revision/clustering state.

Recommended assumption:

- this repo emits raw per-frame observations
- Lucas owns clustering, revision, and final text-file generation

### 6. Start / Stop Control Interface

Current uncertainty:

- The user confirmed a start/stop button model, but the immediate software interface is not defined.

Need to confirm:

- simple service API with `start_session()` / `stop_session()`
- CLI wrapper for testing only
- actual UI/process that will invoke those controls on the Jetson

Recommended assumption:

- implement a service class with explicit `start_session()` and `stop_session()`
- keep a thin CLI wrapper for local testing

## Architecture Summary

The pipeline uses SVO-first streaming:

- live ZED capture records SVO2 segments
- Worker 1 (external) replays segments for NN detection, writes detection JSONL
- Worker 2 (this repo) replays segments for tracking/depth/planes, reads Worker 1's detections, streams frame objects to `frames.jsonl`
- Lucas tails `frames.jsonl` on the same Jetson

The detector boundary is decided (JSONL file handoff). The exact minimum payload still needs confirmation with Lucas.
