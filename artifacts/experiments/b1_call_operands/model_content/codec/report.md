# D shared snapshots 与 schema v4：有限实施报告

状态：Implemented；以下专属 CPU 定向测试 Verified。不是 D/P/V、ready 或 runtime/source 验收。

## 文件和接口

1. snapshot.py：`SnapshotError(ValueError).code` 和 `ExternalSnapshots(value_graphs=None, evidence_graphs=None, semantic_graphs=None).graph(artifact, kind)`。仅 exact ValueGraph、EvidenceGraph、SemanticGraph 闭合白名单；复用原 validate、canonical external_bytes 和 v2 values/evidence/semantic_from_dict，不新增 producer/解释器/任意插件执行。
2. 每个 resolver 首次访问核 hash/schema/size 后从已核 bytes strict decode 成 detached snapshot。缓存仅本 resolver；下一查询 new resolver 重新核可变 caller catalog。URI 不读；snapshot 验证成本不算 geometry 工作预算。
3. catalog exact dict、全部 key exact str。缺 key→None；已给 None/wrong family→external_graph_type；malformed graph→external_graph_invalid；hash/schema/size/artifact 不符→external_snapshot；catalog 类型不符→catalog_type。code 可供 root validator 精确映射，不把已知矛盾降 gap。
4. external_artifact 明确扩 exact SemanticGraph，原 ValueGraph/EEG bytes 算法不变。
5. coverage._ValueCatalog 薄委托 shared resolver，保持原函数签名与旧几何 catalog TypeError/缺 key None 行为。不复制 snapshot/geometry 逻辑。
6. schema v4：仅 denotations、work_evidence_bindings、observation_requirements、observation_roots、content_reads 任一非空才自动选 4。可显式 v4 空表，但全部字段必须存在；这只升级 wire，不填 runtime 证据。含 D capability 强制 v1/v2/v3 拒绝。
7. 原 v1/v2/v3 独立字段集和 reachable tagged vocabulary 保持；新 types 仅由 v4 新字段可达，不能借 old source union 夹带新 tag。ValueVersionID 按其原 dataclass/tag/logical-value namespace 编码，未伪装成 Identifier 或重命名 IDs。
8. codec 仅做 constructor/type/wire 校验，不解析 artifact、读 URI、校验整个 execution graph 或执行 provider。

## 有限旧测试调整与迁移

- 三个旧 codec 文件仅最大 SCHEMA_VERSION 断言改 4；原显式 wire1/2/3 与所有 golden byte 断言保持。原 version[4] case identity 保留并转支持，追加 version[5] 仍拒绝；原 version[3] 仍支持。
- 旧 coverage once-hash 用例计量点从 coverage.external_bytes 移到 shared snapshot.external_bytes；保留同一 case 身份、断言和调用计量。此改动已由 root 明确授权，未保留失真的伪 hook。

## 独立 v3 golden

生成器：codec/generate_v3.py；原 archive/子 Python 命令、stderr、stdout、result、full revision、source hashes 及 proof 保留 codec/v3_golden/。

- immutable revision：6efbe272bceb1036eba3725f11c47960fd5dd301。
- git archive 仅 scar 和 tests/fixtures；子 Python cwd/PYTHONPATH 指该独立目录，断言 codec max3 与所有导入 scar/tests.fixtures 模块位于 archive。
- factory：event_order_execution(same_queue=False, with_wait=True)，含完整既有 event/work declaration fixture；其 pending outcomes 不被伪造为 completed。
- fixture：tests/fixtures/execution_v3_frozen.json 及 .proof.json。
- 117878 bytes；SHA256 8551cd9043cf0d13d20da40a41a7541b5781d4896fa8ed8ee473058006184b3f。
- 生成首次成功；不依赖当前 v4 codec 作期望。当前同 factory 再输出与旧 bytes 直接相等，旧 v1/v2 未重生成。
- 临时 archive 为本任务 TemporaryDirectory，完成后已按 context 自动清理。

## 实际定向测试（均 conda lewm / Python 3.14.7）

环境 PYTHONDONTWRITEBYTECODE=1、PYTHONPATH=.。每个 attempt 保存原 argv/cwd/environment、stdout/stderr/result/source before-after hashes；无覆盖旧证据。

1. snapshots/attempt001：python -m pytest -q tests/unit/test_execution_external_snapshots.py tests/unit/test_execution_coverage.py；48 passed / 0.48s / exit0；源码前后 hash 一致。
2. codec/attempt001：python -m pytest -q tests/unit/test_execution_content_codec.py tests/unit/test_execution_codec.py tests/unit/test_execution_work_codec.py tests/unit/test_execution_order_codec.py；135 passed / 2.99s / exit0；包含当时 model/content/observations 的所记源码前后 hash 一致。

snapshot 覆盖三 family、detach、跨查询 mutation 重核、missing/presentNone 区分、exact catalogs/classes、malformed shape、digest/schema/size、URI 不读、同查询 once-hash、序列化后 caller 改动不污染被核 bytes。codec 覆盖五表单独 capability、降级拒绝、所有新表强制字段、旧版空字段/tag smuggling、VersionRef 原 typed namespace、深层 identity/basis/consumer/placement/Q 变体、nested tag/type/private mutation、无 resolver/file I/O、旧三版独立 byte equality。

没有运行 full、LeWM、GPU、capture、安装或推送。未编辑 model/ids/content/observations/validation/query/docs；这些接口的 graph/source 关系由 root 与其它 owner 单独验收。此报告不授 ready/runtime/transformation 权限。

## 最终 SHA256

- `scar/ir/execution/snapshot.py`: `e3b4e071a865f8cb94bcf732ae8b45688ee33243e03921c551dc76690621ed5b`
- `scar/ir/execution/coverage.py`: `edcdaacc661aaf1c712825efa202c2bc98554e6937304ab50169fe23acc89425`
- `scar/ir/execution/codec.py`: `97aab7e5cf736d8687f85236028294eeb23dd20504c1867ff68529261c14f90a`
- `tests/unit/test_execution_content_codec.py`: `11381df8cdd8a66de024d9a47a9c110b00dc9bf98b7009adf0c5c45a00022ba6`
- `tests/unit/test_execution_external_snapshots.py`: `9ac9520b84f4a7cb5b40a47f335ef04ed83ab72a0ca75aa70c5aad78bcbd0ee5`
- `tests/unit/test_execution_coverage.py`: `b01070fc3596c7120dfa437611f082fb9ab7d622f6becd7382d15817d93c465f`
- `tests/unit/test_execution_codec.py`: `5ba1e6a0e0e28f7fe824c4be4e1e71dbc960397a6a4a8654bc590c0e49a39b54`
- `tests/unit/test_execution_work_codec.py`: `e71126154a7538f6a55dc978dcfad2c38da8743cd45d0bf75fe7d4b7dd69e447`
- `tests/unit/test_execution_order_codec.py`: `a9a261f9ff8fde27fd9464cb78ba583423883283cd4bb02fe72cdaa49c05dc76`
- `tests/fixtures/execution_v3_frozen.json`: `8551cd9043cf0d13d20da40a41a7541b5781d4896fa8ed8ee473058006184b3f`
- `tests/fixtures/execution_v3_frozen.proof.json`: `7d206bc8b8094dc5848db960b9b034343f7b32038296143b5bea53a3e7d03eda`
