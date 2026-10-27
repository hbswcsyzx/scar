# D1规范driver连接实施与验收证据

2026-10-18；设计基线 `306a789`，冻结实现
`382363c3a5e762b40a7b4bf0d47726a7bbbbe509`。本批范围是静态声明连接，
不是自动源码/运行时导入、D2生命周期或LeWM变换。

## 1. 实际交付

七表、RAW_DRIVER_REQUEST、专用BodyDrive、当前state/CFG/Use校验、v11严格wire、
输入/输出派生查询与CLI结构报告。Create→Start→Suspend、Resume→Return/Raise
都用真实canonical ports连接。没有新增permit或通用RequestGate历史状态机。
Start外部/多Create、extra state、request创建/association、多source及发散有正例。

## 2. 分开的证据分母

- `records/`：原38项owned record测试。首个37PASS/1FAIL是把正确ValueError误期望
  TypeError；改测试期望，不放松record。原尝试和终态均保留。
- `graph/`：最终52项owned graph测试；先前fixture构造错误与duplicate metadata
  被constructor正确拒绝的预期错误均保留。raw effect行为约束修前7FAIL/修后7PASS。
- `codec_queries/`：最终64项owned wire/query/CLI测试。初跑46PASS/9FAIL是historical
  capability诊断晚于旧record shape拒绝；以限定字段位置早扫修复，未弱化断言。
- `review/`：独立只读审查与有界畸形输入probe。发现raw标签遗漏并由owner修复。
  报告中的源码hash只绑定post-fix，不伪称能识别更早进程缓存的旧module代码；
  raw修前/修后的断言证据以graph的原始日志为准。82项focused回归与组件有重合。
- `component/initial.json`：首个671项/13标准PASS，9.408s；之后仅删除一个测试文件
  末尾多余空行。`component/final.json`为最终671项/13标准PASS，9.142s，415源文件
  指纹前后一致。两个通过记录不相加为1,342个独立测试。
- `historical/`：从immutable `306a789` git archive独立生成v10 golden的exact command、
  子进程输出和隔离源证明。不是使用当前v11 codec制造期望值；自建临时archive已清理。
- `full/`：冻结实现的单次全仓命令、环境、JUnit/cases、时间/内存及前后source/fixture
  fingerprint；终态计数与本批独立验收在`acceptance.json`记录。

终态：671项组件/13标准PASS；冻结全仓3,706 passed、零失败/错误/跳过，三条既有warning。
全仓外部计时457.563s、峰值RSS 1,025,620KiB；源码/fixture/HEAD/clean状态前后一致。

## 3. 规范来源及权限

最终源指纹：`4d1b28511b8005829d87349fd81a859ef4225af81c810f1641068fa3272066a4`，
415个source/gate/test文件；本门有29份fixture，历史前26份不改，新增D1工厂及v10
wire/proof。所有statement均按其实际范围：手工IR不算automatic decomposition。

查询返回原UseSite/当前instance capture recipe，不选择某个动态Create；saved/private
不重新物化为driver参数。finite outcomes不证明totality、真实分支、dead或无effects。
各source/runtime/instance/exclusivity/transform标志仍False；D2/D3及完整M0–M2开放。
没有本批LeWM profiling、optimization backend或clean A/B加速比；全仓旧测试的
执行范围以其原case记录为准，不把它们冒称新D1运行时adapter验证。

归档后只读复核，不重跑实验：

```bash
conda activate lewm
python artifacts/experiments/b1_call_operands/model_driver_implementation/check_evidence.py
```
