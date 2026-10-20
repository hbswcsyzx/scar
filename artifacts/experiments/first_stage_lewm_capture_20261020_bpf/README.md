# Completed LeWM collection, not complete program-model acceptance

Product revision: `1650431`; conda `lewm`, Python 3.14.7,
Torch `2.13.0+cu132`, CUDA build 13.2, NVIDIA GeForce RTX 4090.

`run.sh` executed the original pusht checkpoint command, one episode, evaluation
budget/goal offset 25, without an optimizer or target modification. Return code
0; success_rate 100.0. Instrumented target wall time: 302.04685678333044 seconds.
This includes collection overhead and is not a clean performance measurement.

The previous non-BPF attempt remains under `../first_stage_lewm_capture_20261020/`
as FAILED/INCOMPLETE. The local seccomp-BPF probe completed 100,000 unselected
getpid calls in 0.10293566528707743 seconds, command wall 0.20 seconds. This is
collector configuration validation, not a workload speedup.

## Observed original records

| Source | Result |
| --- | --- |
| Python call trace | 84,315 entries, 168,630 records, 851 code descriptors |
| Call/operand collection | zero dropped records/errors; 945 explicit operand gaps remain |
| Native ETO | 151,228 nodes, schema 1.1.1-chakra.0.0.4 |
| ETO/Kineto CPU relationship | 151,226 unique positive RF ID/name matches; no duplicate positive IDs |
| GPU | 22,457 kernel, 543 memcpy, 1,082 memset activities |
| GPU to runtime relationship | all these activities have one matching positive runtime correlation in this capture |
| Observed device/context/stream | (0,1,7), (0,1,13); not a global device topology |
| OS | 253 per-TID trace files, 705,569 lines; selected syscall families only |
| Target outputs | local pusht/env_0.mp4 and pusht_results.txt, plus Hydra metadata/log |
| Native shutdown | CLOSED, empty failures; target Git status before/after empty |

`capture-audit.json` contains machine-readable counts and original raw SHA256s.
The audit script lives in the previous attempt directory and takes this directory
as input; it has no workload-specific operation or optimization rules.
Raw IO arguments in the OS trace are pointers/counts, not Tensor/file payloads.
The ffmpeg/libx264 subprocess, mp4 creation/writes and termination are observed.

## Lossless retention

The 610,589,591 bytes of selected raw metadata were losslessly compressed to
41,097,195 bytes. Every gzip was decompressed and hashed before deleting its
generated raw duplicate. `archive-index.json` maps logical paths to actual gzip
paths. Existing SCAR readers resolve `path` to `path.gz`; collection manifests
retain their original close-time facts.

`archive-audit-check.json` checks 257 original/audited hashes, the operand byte
count, and all 258 compressed file hashes. The initial check only matched two
absolute paths; its receipt is retained. The corrected checker normalizes the
relative audit paths and verifies the full denominator. No target rerun was
needed for that reporting correction.

## Acceptance remains OPEN

RF/correlation matches are scoped provider relationships, not logical data
identity or source equivalence. Python-to-Torch occurrence, logical versions,
current state, alias/lifetime/ready, resource instances and the complete canonical
model still need automatic adapters. OS counts are not a resource lifecycle
graph; startup/collector and descendant activities are included. The 945 operand
gaps and 65 unknown call exits are not hidden by zero dropped records.

No backend/detector, transformation, clean A/B result or speedup is established.
