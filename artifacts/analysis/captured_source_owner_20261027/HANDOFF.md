本交付提供正常归档 owner 与 CodeWitness 准入口；尚未接入 model_run / _Sources。

```python
from scar.analysis.captured_source_owner import CapturedSourceOwner
from scar.analysis.code_witness import CodeWitnessStore

with CapturedSourceOwner(trace_directory, project_root=original_project_root,
                         metadata=captured_source_metadata_artifact,
                         frame_scan=original_normal_frame_scan) as owner:
    # frame_scan 可省略，此时内部运行普通 scan_call_trace；给出的 scan 必须是
    # 同 trace 的正常 typed 结果，不能从 JSON 构造 owner。code/meta 仍核原 SHA。
    captured = selected_original_captured_code
    snapshot = owner.snapshot(captured)
    original = owner.archived_source(snapshot)
    # original.text / source / declaration / original_encoding / raw_sha256
    # 分别是规范文本、原 rows SourceFact、metadata 成员和原 raw 解码来源。
    # 用原 filename + fingerprint + namespace 进入现 source 构造；禁止转向
    # tokenize.open(snapshot.path) / prepare_source(path) 的 live 路径。
    writer.admit_captured_source(snapshot, captured=captured, source_owner=owner)
    code, proof = writer.resolve(captured, snapshot, optimize_candidates,
                                 allow_compile=True)
    # 按既有 CodeWitnessStore 普通 read-only archive + resolve 再核完整 descriptor。
```

metadata 参数是原 call-meta.captured_sources 的 ProviderArtifact。owner 普通检查该闭合成员、原完整 CodeCapture、SourceMeta/code_sources 一致、rows EOF SHA、raw/base64/encoding/normalized hash；支持原 logical JSONL 的 lossless gzip，文件名/namespace 不迁移。snapshot 的 UTF8 text fingerprint/major.minor 沿生成 source layers 的约定；原 raw encoding/hash 单独保留，版本取原 call-meta.python。

正常同 session 已有 CallTraceScan 时可显式传 frame_scan，避免再扫 frame events；owner 仍普通核 code/meta 原字节与 CodeID/anchor，来源 rows 也总要读取。无 scan 时内部 normal scanner 的费用另记 frame_scan_*，不伪作零成本。owner 只私有保不可变文本与原 refs，不返回 live graph/serialized seal；close 后拒绝读取。

同 file 多 code 使用同一 snapshot/source provenance；逐 code 的原 membership refs 单独返回。原 capture 的 compiler_match 永远仍 NOT_CHECKED；只有 resolve 的实际完整 descriptor 匹配才产新编译见证。runtime optimize 不是 per-code optimize 证据；调用者显式给候选，匹配失败保原 frontier/错误，不能用 __file__/filename 猜成 VERIFIED。new admission 同时要求原 observed interpreter build 与此 CodeWitness runtime 一致。

后继 _Sources.context 应显式接 normal owner，使用 owner 的归档 text 构造现有 source context，并保原 path/fingerprint/namespace；model_run witness 阶段应在 resolve 前 admit_captured_source。不能把 owner 伪装 SourceAttachments，不能靠读回 JSON 宣称恢复 owner、call binding 或执行环境。本交付未改这两处，旧 live 路径还须后继接入。

当前封闭 SCAR_PROGRAM_PORTS_V1 / captured-python-sources schema1。另一 agent 的 V2 仍同 rows/hash 形态但 metadata.profile 改变，必须在后继按父 call-meta/profile 精确扩展，当前不猜 V2 资格。
