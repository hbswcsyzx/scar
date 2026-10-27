正常 CapturedSourceOwner + 显式 CodeWitness 准入已实现并实际通过；自动 model_run / _Sources 消费尚待后继接线。

独立树 `captured-source-owner`，branch `codex/captured-source-owner`。从 main43385889 窄合依赖14cbaf51+9fc397d0（本地 commits623a86b1/e64a5eb3）；本功能只新增 `analysis/captured_source_owner.py`、在 `analysis/code_witness.py` 增加 `admit_captured_source`。没有修改 main、另一 agent 的八源、native/201快照、旧 admit_archived_source/text/resolve 合同。实际字段/接线见 `HANDOFF.md`。

正常 owner 核原 metadata SHA、闭合 call-meta.captured_sources、完整 CodeCapture/CodeID→filename 成员、原 source rows 原始/规范字节与encoding/EOF SHA。按原 filename+fingerprint 返回归档 text 与 ProviderFactReference，不读/改 live 源文件、不伪装 SourceAttachments、不从 JSON 恢复 proof owner。source provenance 按原 row/file 共享，单个 CodeID membership 另附原 locator；没有新建 source graph/节点/CodeID/identity 权威。

SourceSnapshot 沿生成 source layer 的规范 UTF8 文本和 major.minor 约定；原 raw encoding、raw SHA/bytes 另保，Python 版本从原采集 metadata 导出。CodeWitness 新准入只记录 CAPTURED_SOURCE_OBSERVATION、NOT_CHECKED 与 loader_bytes_observed=false。实际 compile→完整 descriptor match→独立 readonly resolve 才构成新编译见证；原 capture 不改为 VERIFIED，更不证明 loader 当时读取了这些字节。

唯一原 CPU 输入：`program-ports-capture/artifacts/experiments/program_ports_cpu_20261027/capture/trace`，PID2026697，metadata69521cb317c57b9bed3087c5f36d0385e760146c8c5c672c0ad532bc876692e4。正常读取99 captured descriptors、10 source rows / 137000 normalized bytes。机械按原 project_root 限定、filename/first_line/qualname/key 排序选中原 `project/main.py` 的 `<module>`：192 raw B，snapshot4ff684ac74c395a2de4aabca9c6b1d6872bcad26bc7b3c40c6947eea6209926c，CodeID3f6cc46b687b8317a2aa121648ef35211d8b0e8b4025b149864f59fa7c38d6ec。没有重新采集、执行 target、lower body 或读取大图。

当前实际窗口 `attempt02` 自持handle19742 exit0，GNU-time0.86s、主体0.077923s、RSS32104KiB。writer compile1/full descriptor match1；普通 readonly load1/match1/compile0，readonly text() 也从新归档校验。写出的 source192B / marshal643B，manifest6876B（准确 receipt 以 RESULT.json 为准）。writer/readonly 的 source_bytes_read0 表示没有 live text() 读取；owner 的归档读取成本另列，不把它说成零读取。

审计钩子在正常 owner/compile 开始前禁止 open 全部10个原 filesystem 源filename，实际尝试=[]；没有移动或修改任何项目/用户文件。原 source raw/normalized/snapshot refs、字节、版本、CodeID 和新 archive 原 proof/receipt 见 `attempt02/RESULT.json`。正常 owner 自身98179 stored / 237561 decoded B；内部普通 frame scan 另30711 stored / 242538 decoded B，合128890 stored / 480099 decoded B；其中 code/meta 复核确有重复，未隐藏。若已有同 fresh normal scan 可显式复用，免去第二次 frame events 扫描。

`attempt01` 原首窗也真实 compile/readonly通过（GNU0.82s/主体0.07955s），但自审核出 code-member ProviderArtifact schema 标签临时写为 scar.call-codes/1。原窗口/两源字节完整保留，未覆写。当前窗口改用既有 `scar.call-edge-codes.v1`，并保持原 source row 精确整数类型守卫；只重核同一小输入，不是另一次 capture 或扩测试矩阵。

五个原 non-filesystem filename（frozen runpy、string、frozen importlib._bootstrap、frozen importlib._bootstrap_external、frozen posixpath）均保 NON_FILESYSTEM_CODE_FILENAME；没有编造文本/SourceSnapshot。其他9个源未编译；未选择的CodeID没有执行本轮独立 descriptor 匹配，不授匹配资格。本轮仅验证这一源码的编译对应，不授动态 callable/closure/environment、actual/formal、内容/状态/资源、完整程序或优化资格。V2新 profile 明确待适配，不冒用V1成功。原 metadata/rows、source files 与采集原件未改。
