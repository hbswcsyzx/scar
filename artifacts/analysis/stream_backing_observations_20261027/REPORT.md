Stream receiver backing observations 已实现并在唯一 CPU file+pipe 样例普通读回；不是资源身份或内容模型完成。

独立树 `stream-backing-observations` / `codex/stream-backing-observations`，base `18be4ffd`。仅三源：`trace/stream_interfaces.py`、新增 `trace/stream_backing.py`、`analysis/source_stream_interfaces.py`。未编辑 main、同事拥有的七源、LeWM、GPU 或运行中的分析。精确 SHA 与基线 SHA 在 `PREPARATION.json`；生产补丁 `PRODUCTION.diff.gz`。

API 与身份边界：

- `StreamInterfaceObserver(operand, *, backing_observations=None)` 接显式 bool；None 才读 `SCAR_STREAM_BACKING_OBSERVATIONS=0/1`，缺省0。旧 interface-only V1 header/BEGIN 字段保留；开启才发同一 sidecar schema2 / `SCAR_BUILTIN_STREAM_BACKING_OBSERVATIONS_V1`。文件名、原 CALL attempt/site/InvocationKey(pid/thread)/receiver token 与 C completion 均沿用。Root/source_revision_current 的 program-ports/CLI/coordinates 接线另行提交，不在本三源。
- 每个原 BEGIN 附 typed `StreamBackingObservation`：CALL-before-invoke、MONOTONIC_NS 起止、builtin chain、fd、fstat(device/inode/mode/rdev/size_bytes)，或独立失败阶段/type/errno。闭合 metadata 的 backing_counts 与 BEGIN 守恒；普通 reader 严格 decode，并核原 CALL 身份/位置、sidecar/operand EOF SHA、completion 和 receiver。失败探测与后续 C_RETURN/C_RAISE 分开。
- exact Buffered*/TextIOWrapper 仍可能包 custom raw。只经保存的 builtin buffer/raw descriptors，确认 exact FileIO 后直接调用保存的 C FileIO.fileno descriptor，再用保存的 os.fstat。绕过实例 shadow；遇 custom subclass、不透明 RWPair/非 builtin 链明确不支持，不调用任意 fileno；未知对象/类型不做用户回调式 introspection。memory 流单列无 descriptor。无 tell/flush/内容/路径读取，无 FD 全表或内部 OS 模型；只在原 CALL 观察点按需探测。
- `read_stream_interfaces` V2 calls 保原 observation，并提供 `ProviderFactReference(events artifact, #/lines/N/backing_observation)`。`stream_resource_interface(row)` 返回现有 `StreamResourceInterface` 的可选 typed backing/backing_source；原 `read_source_stream_interfaces` 自动保留该附属事实，不复制 Operation/Use/StateLocation/资源图，不 mint ResourceID。
- fd/dev/inode/size/receiver token 都不是逻辑内容、永久/跨调用资源身份。fileno→fstat 不是原子操作，可能与其他线程 close/reuse 竞争；本次 backing 观察不证明后续 lifetime、cursor、可见性/persistence/ready 或完整效果。原 source/core CALL 与粗 world 仍是唯一程序依赖载体；receiver→source Value 绑定未由此新增。

唯一实际样例与普通 reader：

source_revision_current 自持 session9810 的同一次 program-ports CPU file+pipe（另含已有小 Torch CPU op，仅为正常 native/OS 坐标接口）actual exit0，owner 报33.73s，CLI archive/coordinates 正常完成。没有本线第二次 capture。原 trace 根为 `/home/zyf/AAA/scar-worktrees/program-ports-capture/artifacts/experiments/program_ports_cpu_20261027/capture/trace`，PID2026697。

本线正常读回 handle41251 actual exit0：7 BEGIN，6 C_RETURN、1 C_RAISE；backing 6 OBSERVED（4 regular-file、2 FIFO）、1 FILENO_FAILED（closed FileIO，ValueError/errno=None）。errors=[] / stopped=false。每条构成 typed StreamResourceInterface，SourceFact 仍定位原 sidecar/BEGIN；原 CALL attempt 的 pid/thread/invocation/site/source-line-SHA 由普通 reader 精确核回。`READBACK.json` 保留全部查询端点。参与采集的同事树三源与本 reader 三源逐 SHA 相同，见 `PRODUCER_SOURCE_MATCH.json`。

reader 主体0.013522s（不含 imports）；进程 max RSS36072KiB。实际读入 metadata2952B + sidecar8199 decoded B + 原 operands216015 decoded B，合227166 decoded B / 25738 stored B，原 retained gzip 正常消费。stream events 原 stored/decoded身份由原 metadata 与 `READBACK.json` 定位；原始 stream meta/events 小字节副本保留，原 logical URI 不迁移。其余原 capture closure由同事实验保留，不复制整个报告/raw。

此一次实际检查覆盖普通文件、FIFO、closed-fileno failure；没有额外运行 MEMORY_STREAM、UNSUPPORTED_CHAIN、CHAIN_FAILED、FSTAT_FAILED 矩阵。旧 V1 本轮未重新采集/回放，默认与 reader 分支保留，不冒用 joint03 旧 GPU 样例的资源/进程资格。`ORIGINAL_JOINT03_VERIFICATION.json` 仅是 base Git blob 报告，显示其旧7条只有接口而无 backing 身份；本轮未查询或重跑该 GPU capture。整程序及流内容/状态/生命周期/ready 仍 OPEN。
