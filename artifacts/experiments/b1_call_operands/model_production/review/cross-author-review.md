# P 跨作者只读审查

结论：**PASS_WITH_SCOPE**。当前来源清单、精确跨图引用、schema v5 和来源查询的
声明接口范围内，未发现尚需阻断本门的具体问题。不等于完整模型、物理 writer
完备性、V/ready、runtime/source applicability 或转换权限通过。

本代理实施的 production_validation/produced fixture/test 不作为独立自审对象。
本轮仅读取其他作者的源码、文档、既有日志和 proof，并写本 ignored 报告；没有
运行测试、probe、fingerprint/gate 脚本、git、GPU 或 LeWM workload，没有改产品。
root 正在统一 component；本报告不预报该组件或后续 full 的结果。

## 1. 实质发现及本轮关闭

### A. 已供空 manifest 的 stream FK

初读 `_source` 把没有 resolution.sources 一律作为 pending，无法区分原 manifest
确实为空与尚未解析。确定的声明级机制是：合法 empty manifest +指向 ghost stream
的 RawRecordRef 应是已知不存在的成员，不能以“未知物理 writer”掩盖这个 FK。
本代理未运行复现。root 已在 manifest/index 解析之前保存 inventory_sources_empty
缺口，`_source` 用 known_empty 拒绝 ghost stream；即使 index bytes 缺失仍保留这项
已知成员事实。真实 source connections 测试有两种 index 情况。

### B. 已支持 raw profile 缺 schema 约束

原支持路径对 raw artifact 只核 hash/size 再按 JSONL 解析，没有核其 schema。
把准确 JSONL bytes 的 raw schema 改成 bundle，并重封 manifest/index，原路径无法
诊断 role/schema 矛盾。本代理从代码定位，未运行旧实现。root 已在受支持 recipe
路径要求 `scar.trace.raw-jsonl`；unknown recipe/profile 仍不执行，保留 pending gap。
真实 repack 反例已存在于 source connections 测试。

### C. ObjectRef 目标边界：最初窄分支已经扩为准确两 family

本代理指出 source bridge 最初只读 ValueGraph bindings，而同名 D ObjectRef 还可
引用 EEG object registry。曾讨论本门限 VG；**最终没有沿用这一限制**。
当前 target_original 支持 VG ObjectBinding 与精确 EvidenceGraph object registry，
missing target issue；同 EEG scope 的冲突按 source EEG artifact 比较，不拿 VG
artifact 与 EEG artifact 交叉。API §2 已同步两 family；跨 artifact 声明仍是条件关联。

### D. 其他作者/主代理发现的窄修复（本代理只作静态关闭）

- snapshot.graph 在查 catalog miss 前先核所请求 graph family 与 artifact.schema。
  已知错误 schema 不再因该 family catalog 没 key 而降成 unavailable gap。
- ExternalWorkSource 的 ResourceConsumer ticket 也必须与原 subject 同 run；不只
  检查 WithinOperation。不同 run 的真实 canonical 反例在 source connections。
- provider scope 下 raw PID 若不是 exact int/缺失，明确
  inventory_process_scope_unresolved，不 coercion，也不凭省略 PID 宣称 scope 匹配。

上述关闭是当前源码与具体测试文字的核对；本报告没有冒称本代理实跑这些反例。

## 2. 关键防线

### Source bytes 与固定重放

- payload 仅接受 exact bytes，missing key 与已供 None/bytearray/string 区分；
  核原 SHA/size，不打开 URI。JSON 拒重复 keys、非有限数、错误闭合字段/类型。
- 原 JSONL 以物理 LF 分行，保留含换行的原 line SHA；不重新序列化 raw 来冒充
  原字节。manifest/index 精确关联，stream key 唯一且 index 对给定集合逐项对账。
- 仅 fixed 本包 recipe：本包 normalizer 文件指纹、固定 profile/version、完整
  bundle/coverage strict replay。recipe 任意 path 不读/不执行，未知版本保留 gap。
- byte/artifact/line/line-size 截断仍返回已知 source placeholders/pending，未扫描
  范围不能当无写。预算是**每 inventory resolver**；不是全查询、全进程的总预算。
  同 resolver 按准确 artifact identity 去重复读取计量；不据同 hash 合并运行时 work。
- format_replayed、无丢弃计数或 normalizer 完成都不授完整捕获；capture、alias、
  window/外部写入缺口仍在。空来源集合也不作物理 writer 空集满足。

### Exact snapshots / bridge / 旧格式

- source bundle strict decoder 已检查 EEG observation/version/materialization/
  producer 和原 VG 结构，resolve_endpoint 只在其准确 artifact scope 内派生 facet。
- include 校验派生 component 并 detach，不遮盖调用方明确给出的 wrong family/
  wrong hash；fresh query 重新核 caller graphs 与 artifact_bytes。返回结果 deepcopy。
- 跨 artifact bridge 不比裸 ID，不从多目标中挑首项，保留未证明的内容/原生对应。
  同准确范围的明确 identity 冲突 issue；缺 supplied target FK 不伪造来源。
- model 四个新表默认空；schema v5 只在需要时升级，v1–v4 reachable vocabulary/
  字段隔离，有新 capability 不能降级隐藏。ProgramGraph schema/producer 不搬家。
- 实际读取 `execution_v4_frozen.json.proof.json`（注意 double-json 文件名）：
  immutable old revision `5ab22f8d8fcbabbc59d494b571651d480468f3d5` 的 codec4 archive
  隔离生成，29951 bytes，payload SHA
  `55ed3e05850fbcb30c44c1894feb81062fc8aaba6976b8d4b0048d44da4735af`。
  最初按另一 proof 名称未找到，随后按实际路径核对，不能据此声称 proof 未生成。

### 来源查询与来源完整性边界

- production 从 ContentRead 与其 run 的独立 manifest/index 来源先枚举，再作可选
  Write/Produced/Work/bridge 关联。candidate ID 只含原 inventory/stream/edge 或
  raw line+SHA；删除 join 不能缩小已经扫描的来源前缀。
- 保留 PRODUCES/MATERIALIZES/OBSERVED_WRITE/OVERWRITES/ALIASES/USES_STORAGE/
  ESCAPES 及全部 raw rows。EEG 输出观察不自动成为物理写；ESCAPES 保留未决
  effect mapping，不冒作 writer。现 normalizer 不生成某些关系，并不假造捕获证据。
- 谱系只列 parent/provenance 前提；不会把祖先平铺成当前 AND writers。
  同 allocation 不同版本及 bbox 可能重叠只列潜在 invalidator，不填洞、不推 native 写。
- exact SourceEdgeRef/RawRecordRef 才接 join；缺关联继续 gap，多个 bridge 全保留，
  不凭 same host/ticket/EEG parent 自动补 pair。
- current_production 仅为准确 scoped version+Mat+selector 一致的**声明关联视图**。
  其余 write 仍在 candidate；同 raw stage/production/placement/writer 仅合并关联视图，
  不签发物理贡献去重或闭合 AND 结论。Outcome 的部分结果保持原对象及未证条件。
- 共享 traversal budget 对 lineage node、parent/provenance 引用、源行/边、端点、
  placement/bridge/write/produced/group 检查及 selector rank 计费。截断显式 unresolved。
  source replay/snapshot/deepcopy 成本另有范围，budget 不是总时间/总内存承诺。
- flags `source_runtime_verified/readiness_verified/transformation_authorized` 恒 False。
  未发现把缺来源、规范化输出或成功 kind 变成 authoritativeProduced/ready 的路径。

## 3. 已读取他人执行证据的界限

- query 最终 attempt004：26 passed in 2.27s，exit0；作者已冻结模块 SHA 与下表相同。
  attempt001 的五项新 fixture 坐标错误、后续修正及预算/ESCAPES 迭代均原样保留。
- codec attempt009 日志：150 passed in 3.31s；这是作者当时定向运行。
  root 后续仅恢复一项旧测试函数名以保 baseline case ID；最终组件另行绑定当前源。
- source connections 新案例文字已检查，最终统一执行由 root 完成；本报告不借未收到
  的组件结果授 Verified。也不将本人先前 owned41 cases 计作独立跨作者测试覆盖率。

## 4. 本次所审 SHA256

| 文件 | SHA256 |
| --- | --- |
| `scar/ir/execution/inventory.py` | `99ed4011ebd379cff8f9b8731b5fd5c2cf9611ff7865d1241dc83dfe67a9afb5` |
| `scar/ir/execution/snapshot.py` | `7757c299a965e37f5e73eeaa1f4ed304da6b7bfb970cded5d274fdc4e8483107` |
| `scar/ir/execution/source_validation.py` | `34f1f929dec9f55ae74913ff19ec23820e262433ed59340bf5b70c79fd91b1e2` |
| `scar/ir/execution/model.py` | `f5dac199ae412106b4f76edf6e6bf650828b6468b9e24c03eb12fe78e621affb` |
| `scar/ir/execution/codec.py` | `981ce8adbae591a9fea25534d9987923c901db8a2fb4861e20a52b5755057dc7` |
| `scar/ir/execution/production_query.py` | `3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab` |
| `scar/ir/execution/query.py` | `cb14eb5de94a93f11dd2c0bfd076b1cf1bb66d01cdd606b768447f0fa03213b1` |
| `scar/ir/execution/validation.py` | `a59db9e27b4eaa924c1b7973ac995a36cc59c3cfdd63c23d00832447b7d8c0ac` |
| `scar/ir/execution/content_validation.py` | `bd163c92244a06dae9e5756882124cab350ffeec09bbe22e3137278712f5b298` |
| `docs/M1_PRODUCTION_API.md` | `1c5c8125b0af07bd3253ff238e6afa77afcf0f51ffebb263792d73eb12ba600f` |
| `docs/M1_PRODUCTION_PLAN.md` | `6d5c2d5d24071532251d415a58b30cf1982ce0d3a690d45c84050e593f13a24f` |

**最终限定：** PASS_WITH_SCOPE 是这些声明/解析/连接/查询的源码审查结论。
完整 native writer universe、动态 identity、全读区间稳定/visibility、V/R3 与完整
M0–M2 仍未完成；不授 ready/free、transform authorization 或 LeWM 建模/加速结论。

## 追加：最终组件冻结 receipt

上文“root 正在统一 component / 不预报结果”保留为首稿时点记录。
随后实际读取 `model_production/component/final/report.json`：

- 状态 PASS，8 criteria；**477 passed, 1 warning in 10.88s**，exit0；
  gate duration 11.647s。
- 521 个注册 source 文件，fingerprint
  `66e35626809a14cde497346a97d56e94697958d4895bd253f48a1975e9662c10`。
- 对 report.tested_files 全部 521 项只读 `sha256sum --check --quiet`，exit0；
  没有重跑测试、fingerprint 脚本或修改 source。
- 唯一 warning 是 OS witness 的 record_property 与组件 runner 的 xunit2 输出模式
  不兼容；本代理的 owned attempt002–005 已使用 legacy JUnit 并保留真实 witness
  属性。该 warning 不改变 assertion/case/产品语义，未为其改动冻结源。
- root 的 29 个 source connections case 随该组件实际覆盖；本报告不把 29、41、26、
  150 等重叠子集与 477 累加。源码审查 PASS_WITH_SCOPE 的权限/完整性边界不变。
