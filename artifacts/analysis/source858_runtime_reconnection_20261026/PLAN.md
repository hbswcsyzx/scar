# 正式 source858 → 原完整 LeWM runtime：单次 fresh 接线计划

**仅设计，未运行。** 目标是把已正式发布的858快照接回原369749 capture的全部100438 calls；最新实测runtime仍843/6699。复用已有公共 `connect_current_capture`，本轮未发现必须改生产API的确定阻断。通用 `model-run --from-capture` 当前bootstrap路线会重做native/OS和monolith来源，不能替代本门。拟新增一个实验入口，调用正常公共协调器，不加业务/后端规则。

## 准确输入与资格

路径以下均相对 `artifacts/experiments/`；完整URI、SHA与15个原SP5/CP2见 `RUNNER_INPUTS.json`。其大产物收据来自实际旧门，本设计未重新hash/解码它们。

| 角色 | 原件 |
|---|---|
| 正式858 composition3 | `source_frontend_remainder_composition_resume02_20261025/result/composition/index.json.gz`；stored17,109,069B，SHA45569e930c3fe03a6d2cf4c26a93491c7ce9b496d25aab5fae09767deb91fe9b |
| publication manifest2 | `source_frontend_remainder_publication_20261025/result/publication/manifest.json`；83,792B，SHA4959e7a58abe42415ad2a066f96572a83c83f5b4aaebe9462778d5569439ef5d |
| 原capture / trace | `first_stage_lewm_physical_20261023` / `trace`；原Run capture:1ddea1de4990462b59cf5dd24beb3f120156eb47bca68cfb3f1a63f9f73f2cf0 |
| 原坐标profile / dispatch bridge | `first_stage_current_source_gate_20261023/result/capture-coordinates.json` / `first_stage_joined_physical_20261023/result/native/dispatch-bridge.json.gz`；保持原URI和字节 |
| compiler/membership输入 | 严格仍用 `first_stage_current_source_gate_20261023/result/source/{report,bindings}.json` + 该门原freeze、participating receipt及archived source；不换843报告冒充原compiler origin |
| 源attachment / readonly witness | 原 `first_stage_dependency_continuation_20261023/result/continuation.json`；原 `first_stage_partitioned_operand_routes_20261023/result/code-witnesses`（20keys/41files），create=False/compile_missing=False |

858实际consumer20761 exit0/651.143247s，12普通reader返回；846原门exit1/FAILED_ENV_FREEZE、三reader PASS与metadata-postflight0分别保留。二者均未跑runtime。858/151/2217、NOT_ATTEMPTED590、UNSUPPORTED769保持；15个新图只是原件输入，不预写它们的动态参加数。12图179的旧调用权重不能加到6699。

## 能否只换 composition？

**公共调用主体可以，旧实验脚本不能原样复制。** 858仍是partitioned composition3/publication2/header2与原两能力；无external-entry overlay，不走v4/v5。`SourceBodyAccess.bundle`现已对CP2用readonly `CodeWitnessStore.text(snapshot)`提供单模块source_texts，随后走普通typed body、SourceCodeEvidence及structured/interface验证；不读live目标文本、不lower。

需改的仅是新runner侧：①目标与manifest pins换858；②旧audit.snapshot只识别65/218，改为从843→846的3项、846→858的12项准确qualified(fi,bi)+原namespace/CP2机械建表，并另保843前缀；③旧prepare把输入限制main/artifacts，三个kwargs SP5原URI在source-call-model隔离树，须仅按这三个准确原件放行，不迁移/改URI；④旧freeze钉旧ancestor源码SHA，改为当前consumer闭包哈希，历史producer只校原归档；⑤旧源码/运行时freeze资格不追补。新消费者不能被倒填为原publisher或原collector。

## 一次同进程入口与检查顺序

1. 新目录 `first_stage_source858_current_20261026`：`run.py` + `run.sh` + 小freeze准备；复用旧有界 `report_archive.py`（pin原字节），不用旧两图audit。输出不可覆盖。freeze仅准确SHA与输入目录成员，不复制大provider/数百源或新建图权威；同时固定当前Python/runtime实际闭包（含pickle/_compat_pickle），未知参与模块显式失败。
2. 同一进程先普通 `CompositionIndex(COMPOSITION858, source_attachments=((CONTINUATION, SHA),), attachment_budget=SourceAttachmentBudget(max_record_bytes=128000000,max_artifact_bytes=2200000000))`；核header全分母、原compiler inventory完整等式、15项当前CP2/namespace及snapshot/context。调用 `require_source_membership_ancestor(old_report.composition_canonical_sha256,old_report.inventory,max_depth=16,max_total_decoded_bytes=1000000000)`；预期链858→846→843→842→原comp2，实际depth/字节计数由API记录。失败即停在raw前，不继续盲跑。
3. 正常 `bind_capture_coordinates(CAPTURE,max_bytes=2000000000,max_lines=2000000,profile_uri=原PROFILE)`，核原Run及payload等于原profile；不是import_capture/nativeOS重建。
4. 唯一 `connect_current_capture(index,coordinates,CAPTURE/trace,new_connections,previous_source_directory=原OLD/source,previous_report_sha256=原SHA,previous_bindings_sha256=原SHA,previous_producer=(原freeze,SHA),previous_participating_producer=(原receipt,SHA),code_witnesses=readonly_store,dispatch_bridge=原BRIDGE,frame_budget=原预算,operand_budget=原预算,route_budget=原预算,include_environments=True,progress=...)`。三个resume参数全None；private owned raw/proof在同进程产生，不恢复JSON owner。
5. 统计新source/source-only/unresolved与每个15图的真实calls/activation/namespace，完整核855codes/817groups/100438entries+exits/312812operands/16403env/79592markers/109288slots、0重复/漏项。SBA引用核活跃namespace；不再次解图，不typed旧坏65。source旧未解析组、generator/handshake、route/env缺口原样保留，不用CPU新资格抹除。report仅to_dict一次，分chunk保存，失败保phase/traceback/progress/partial和源码/输入检查结果。

## 预算申请与可证边界

沿原fresh门40820实测24:18.35（协调器1384.868s、RSS2,226,076KiB），申请原5400s wall/CPU ceiling、12GiB AS、单文件2.2GB；不是24分钟预测。858多15个SP5声明stored24,253,406B/decoded223,927,277B，旧12图reader消费651s提示本门可能明显更慢。ancestor由depth2约154.44MB增至预计depth4约309MB，仍用1GB界。

保原frame256MB/300000lines/250000events，operand128MB/1000000lines/1000000events，route/template各100000；坐标2GB/2000000lines。输入声明4096files/单件2.2GB/unique stored8GB；旧1248件519,754,760B，新增两根+15SP5约58.4MB外加小metadata（并集freeze后报实数，非重复读取总量）。原trace15件45,868,154B、store676,743B。所有重复stored/decoded输入总计仍OPEN，不把unique物理输入界冒称累计I/O硬帽。报告16MB decoded/1000row chunks，heartbeat20s，审计输出流2GB/2000000rows；大raw与原图不重复归档。

拟由Root一次运行新入口，收actual exit/时间/RSS、精确producer与input pre/post、private ANCESTRY_V2、reader_counts(1/1/1与fresh binder1/resume0)、全分母/15图实测/原frontier。当前完整模型、实际formal/env/state/effects/ready、resource/content、旧collector准确SCAR执行字节与historical runtime缺证仍OPEN。没有重lower/prepare/compile/publication/capture/target；不授优化/后端资格。**请先审批以上输入、5400s ceiling及runner侧5点改动，再准备并持有唯一实门。**
