# Docs

This folder captures the intent, architecture, runtime behavior, and data contracts for the ZED spatial measurement pipeline.

Status:

- the pipeline uses an SVO-first streaming architecture
- the live thread records SVO2 segments; background workers replay them for processing
- Worker 1 (external NN detector) replays SVO2 and writes detection JSONL
- Worker 2 (this repo) replays SVO2 for tracking/depth/planes, reads Worker 1's detections, and streams frame objects to `frames.jsonl` per-frame
- frame-level `planes[]` and `papers[].plane_id` are emitted per frame during processing

## Files

- `PRD.md`: Product requirements and v1 scope.
- `Technical.md`: SVO-first streaming architecture, module responsibilities, frame-processing flow, operator runbook, and debugging guide.
- `Schema.md`: Per-frame handoff schema and session file layout.
- `Validation.md`: Primary metrics and recommended hardware validation flow.
- `LucasHandoff.md`: Exact JSONL handoff contract for Lucas's clustering step.
- `Uncertainties.md`: Open design questions.

## Read Order

If someone is new to the repo, the fastest useful order is:

1. `PRD.md`
2. `Technical.md`
3. `Schema.md`
4. `LucasHandoff.md`
5. `Uncertainties.md`
6. `Validation.md`
