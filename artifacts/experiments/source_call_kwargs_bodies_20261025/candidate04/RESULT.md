原窗口 `attempt04` 保持 **exit1**（launcher 52.886519649s）。两次 lower 和逐图检查已返回；失败位于终检工具：已批准的 `freeze.json` 自身不在运行时 read allowlist，`verify_freeze` 重读时被拒绝。旧 failure、launch、runner、freeze 均未改写。

独立 `postflight01` **exit0**（0.244573s）。新进程调用 approved `26b44d86…c976297` 的原 `verify_freeze`，核实352个源码/runner SHA及27个输入 stat；再核两份新图的存储 SHA、body-results 与原 failure 中相同记录，并对齐末 phase 和原机器计数。没有重新 lower、解码图、调用图 codec、读77MB composition roots 或执行目标。92图的资格复用原 candidate03 独立验证收据，本次未重读该图。

全部四个原 qualified subjects（原调用权重合计5）保留在 `selection.json` 和 postflight receipt；未完成项未删除。

| 原 sequence | 已返回结果 | 验证及当前边界 |
| --- | --- | --- |
| 4 | 92 ops；candidate02 原图，candidate03 独立复核 | 有限图结构、原 AST/CodeWitness、局部 pending 通过；本次沿准确旧收据复用 |
| 5 | 350 construction ops；无 program 图 | 原 kwargs 前沿已推进；下一 `JoinedStr` 在 eval.py 82:20–33，仍 `UNSUPPORTED_OPEN` |
| 10 | 85 ops；本窗口新图 | 结构 roundtrip、原 AST/CodeWitness、局部 pending 通过；1 kwargs call / 5 protocol ops / 4 invoke-failure checks |
| 12 | 217 ops；本窗口新图 | 同层验证通过；1 kwargs call / 4 protocol ops / 4 invoke-failure checks |

三个有限图92/85/217的接受仅覆盖各自已保存的验证范围。三者 CALL_EX unwind、outer pending prefix、完整 lifetime、runtime instance 和 world effects 均仍 **OPEN**；seq5 仍无图。整个程序未完成建模。结构验证使用准确 retained source text/AST/options 和原 validators，未冒称默认 filesystem source replay。

原窗口实际 retained input 为243336909B（stored60185367 + decoded183151542），output accounted69620414B，均在原256MB预算内；SELF/GNU max RSS581992KiB，GNU wall0:52.85。原机器收据的 target executable compile / target exec / prepare 均0；CodeWitness compile0、module loads1、descriptor matches2。另有 AST-only compile8、symtable2、analysis compile audit10，不能概括为所有 compile 都0。独立 postflight 的校验成本另计，未回填或改写原窗口预算。

新图存储文件分别为1602195B /1701646B，decoded14769551B /15974502B；保留本地而不 stage。`body-02-returned.json` 为1087656B，也不 stage。小文件清单严格每文件≤1000000B，不将大 decoded graph 放入提交。

12个生产源码保持冻结。只读比较 main 得2新增文件、10个准确匹配已审 baseline 的修改，无 divergence；精确新 SHA见 `postflight01/production-sha256.txt`，旧/新来源见 `receipt.json.production_sources` 与 `main_source_differences`。本次未写 main，未做 Git 操作，未触 native/Context 模块。高层 frontend capability 的显式 policy 接入仍是后续独立改口。

机器证据：`postflight01/receipt.json`（SHA256 `0687d1a6a75adc62dc1b937ec4dd858cf57fe7d8b9859cc243bc6ec8cb5ab85d`）。原终态：`attempt04/launch-result.json`、`failure.json`、`progress.jsonl`、`gnu-time.txt`。Stage入口：`postflight01/stage-paths.txt`；大小/SHA及排除理由：`postflight01/stage-manifest.json`。
