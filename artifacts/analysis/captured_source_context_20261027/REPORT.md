归档源已进入正常 SourceLayer/AST/signature/_Sources CodeLink 与 CodeWitness 链；整程序与自动 model_run 尚 OPEN。

独立 `captured-source-context` 分支基于 main7a4fcb2a，仅四源：`program_lowering.py`、`analysis/call_edges.py`、`control_flow_v2.py`、`ir/frontend_v2.py`。未改主树、另一 agent 的 V2/forward 源、owner.py 或 native/201快照。接口与下一接点见 HANDOFF.md，精确四 SHA 见 SOURCE_RECEIPTS.json。

实际改动：既有 prepare_source 的 text→SG/semantics/CFG/AST/symtable 拆为纯 text 构造；旧 live API 在边界保持原读法和 namespace 策略。归档入口只收正常 owner，保原 filename/fingerprint/namespace/encoding/version，不 open/stat/resolve 原源文件。原 frontend 即使 supplied text 仍会 resolve/is_file、探测 root/__init__.py，现仅新纯 text 路径绕开这些 filesystem 前提并显式接 root_is_package；旧 frontend 默认不放宽。_Sources 与正常 call-link factory/reader 显式接 owner，有档案走档案，缺档/缺 namespace policy/旧 workspace 或 bound-source 接口尚无适配时明确拒绝，不静默回 live。没有新 wire/节点/producer/def-use 图。

_source_witness_projection 另由每个 definition 重新 ast.walk 改为一次 BFS，按 span 用 setdefault 保原 next 首匹配，再查 signature。仅消除该已知重复遍历；没有新性能门、加速比或解释整个旧78分钟 reader 的声称。

单次实际离线门：handle48468 actual exit0，GNU-time1.46s，主体0.514757s，RSS52340KiB。原 CPU trace PID2026697 的177 entry/177 exit 全留，读取99 descriptors；只构造1份原192B project/main.py，48 AST nodes、1 definition、5 source calls、1 signature。main 函数 CodeID `pycode-v2:9cc3b9dbd412e1d45e98679410f76c9edf3dcc6134104367112f42b1cdb7ad8c` 正常 CodeLink VERIFIED，连接到原 namespace 下的 `opdef:op:12b35a09c8b8bcee5522919b` 与原 SourceReference。项目内2个 CodeID VERIFIED；其余97个保持 INCOMPLETE（外部 namespace/非文件等边界），没有扩大 scope。正常 matcher 实际编译3个 optimize 候选，另 CodeWitness compile1/fullmatch1，独立 readonly load1/match1/compile0。不能把这些说成总 compile0。

审计禁止打开全部10个原 filesystem source filename，实际 attempts=[]；没有移动/改写源文件，没有 capture、target execution 或 body lower。静态 namespace policyFalse 沿原 CPU script root 显式输入，不据没捕获 __init__ 推断不存在；它不是 loaded/import 证据。五个 non-filesystem filename 原前沿保留。原 raw encoding/hash 与规范 UTF8 SourceSnapshot、原 SourceFact、CodeLink、normal proof/原件均在 RESULT.json。owner 准入 provenance 仍 NOT_CHECKED/loader_bytes_observed=false，实际完整 descriptor 匹配另成见证，不授运行 FunctionObject/closure、内容/状态/资源/优化资格。

原 frame scan 已在同 session 正常取得并传入 owner/factory复用；owner 自身另98179 stored / 237561 decoded B，frame scan成本不在owner的0计数中。新小 witness archive 保 source192B、marshal643B、manifest6875B。call-model 为原 scar.call-edge-links/1 普通输出；其 gzip 与准确 stored/decoded receipt保留，不新增图格式或复制大数据。全 model-run、call-source seed、inventory discovery/扩展、dependency admission 自动 owner detect尚待接；本次只证明上述正常入口已真正消费归档内容，不把静态构造或177原记录当全调用图完成。
