# P2 foundation：NoEntry publication / terminal history / frame-release 组合

## 初始范围（尚未运行）

仅新增 `tests/fixtures/program_protocol_release_graphs.py`、
`tests/unit/test_program_protocol_release_connections.py` 及本目录证据。
没有改产品、旧测试、旧fixture、主docs或此前archive。全P2与16格协议分母继续OPEN。

新factory `protocol_release_program(...)->(graph,details)` 复用
`no_entry_throw_program` 的原helper INVOKE、双completion、原packet/formal和全部state domain，
以及 `_Tail` 的真实StateAccess release。只在准确host终端前插入操作，原host RAISE ID保持。
NORMAL helper完成与RAISE helper完成各自拥有真实后态；不伪造BodyDrive或Work。

新测试包含：

1. 两INITIAL_THROW分支分别选edge，publication连接原instance Use、原result、原terminal、当前state与release；
2. 另一未选边release被F拒绝，PREENTRY_REJECT与普通READ-only均不种F；
3. 真实入站HOLD写后，原宽NoEntry INVOKE仍杀P；准确边F保留，且可支持条件release；
4. release换成另一个合法Reference owner、或回退helper旧输入state，分别必须拒绝；
5. 同helper有两INITIAL rows时逐edge F仍分离；静态publication可能源集合不是本次路径发生集合；
6. getter严格OperationID/已存在ID，以及普通无row操作返回空tuple。

普通READ反例是选中landing中的真实read operation，不是删除INVOKE后态/半CFG；
它保持selected input及host packet路径，却没有实际write transition。
HOLD前缀新增独立Reference entry参数，原helper state inputs更新到该metadata的真实后态；
未给NoEntry helper新增session/body-only白名单。

## 查询来源粒度的限定

`lifecycle_flow` 的T保存可解释seed operation ID，不存path-sensitive branch历史。
同helper的两INITIAL rows因此都可能出现在 `terminal_release_publication.sources`，
每条仍保留自己的准确selected edge。资格来自当前点F/E，不来自将这些来源union后交叉；
这些是静态可能解释，不能把两条都说成本次release之前已发生的事件。
本点已同步root；不要求第二套来源/许可图，不将它记作实测产品bug。

## 证据记录要求

等待root稳定窗口后仅首跑新unit文件。每次独立attempt保存准确command、
Python版本、stdout/stderr、JUnit、exit、wall time和16个相关源before/after SHA。
任何失败保留原件后再分类，不把fixture错误或诊断顺序说成native/runtime反例。

## 未证明的边界

夹具均为声明ProgramGraph，不是throw实现自动导入或Python native执行。
INITIAL_THROW/source适用、对象身份、frame仍持有哪些引用及实际释放、当前native状态均未获运行证明。
F是封闭profile条件下的历史事实；P是当前state支持，两者不能互换。
TerminalFrameRelease仍NOT_GUARANTEED，不授free、quiescence、设备完成、持久化或变换许可。
本批不关闭完整C2/D3、M0–M2、自动LeWM或性能目标。

## 首轮实际结果与冻结 receipt

root READY且暂停16文件变更后，只执行下列一次新单文件focused：

```bash
bash artifacts/experiments/b1_call_operands/model_protocol_implementation/release-focused/attempt001/command.sh
```

该script准确执行：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
python -m pytest -q tests/unit/test_program_protocol_release_connections.py --junitxml=artifacts/experiments/b1_call_operands/model_protocol_implementation/release-focused/attempt001/junit.xml
```

实际 **Python3.14.7；18 PASS；pytest 0.88s（JUnit 0.883s）；wall 1.52s；exit0**。
stdout为18个通过节点；stderr为空；没有失败被覆盖、没有修测试后重跑。
`source-before.sha256` 与 `source-after.sha256` 的16源清单经 `cmp` 一致。
所有command/环境/原始stdout/stderr/JUnit/exit/时间/前后SHA留在 `attempt001/`。

| 实际新增组合分母 | 节点数 | 结果 |
| --- | ---: | --- |
| INITIAL NORMAL/RAISE原post→publication→F→当前state release | 2 | PASS |
| 非selected分支release不能借另一边F | 2 | PASS |
| PREENTRY合法声明不publication/F，加入release拒绝 | 2 | PASS |
| 普通READ-only合法声明留effect gap/Ffalse，加入release拒绝 | 2 | PASS |
| 实际入站HOLD，经宽helper N/R均kill P，仅准确边F保留并可release | 2 | PASS |
| 另一合法Reference owner不是finished owner | 1 | PASS |
| N/R release回退原helper输入state被stale_state拒绝 | 2 | PASS |
| 同helper双INITIAL rows的逐edge F与possible静态source解释 | 2 | PASS |
| raw字符串/缺失OperationID getter分别TypeError/KeyError | 2 | PASS |
| 普通无NoEntry row操作getter返回空tuple | 1 | PASS |

这里READ-only与PREENTRY反例先对不带release版本 `require_valid`，再加入真实release验证拒绝；
wrongowner只替换原owned Reference Use的value，stale只将原state Use指回同location旧版本，
没有用缺ID/错类型作为这两个语义负例的替代。宽helper保持 `effects_complete=False` 与真实双completion，
没有在产品中新增session post、移除状态或降低原callback kill。

本轮关键受测源及owned文件SHA：

```text
3006e25f6820c04b3380e72c4d14065b8e0168409f1c358083525a15d3f73a4b  scar/ir/program/protocol_validation.py
fef982846cdff4cf88d2fc80e422d88190496a3b0bfb3fe674cf89e7d603b199  scar/ir/program/queries.py
9fc23f943b8389764876856579db2e82797b2fb375a8c9ecc701b785b094d7f7  scar/ir/program/lifecycle_flow.py
13e90d83f74bd46281a678c778c559ad1d6d52d3d5722137be38848f853a7387  scar/ir/program/session_flow.py
4c5c90cfefcaf098d174f3a3763d8b86a50311c2abac803bb2d78d2f257beeeb  tests/fixtures/program_protocol_release_graphs.py
048f4292b3b1e380df53532c98696a465ae30b9eb914a555c386dd7a30300fef  tests/unit/test_program_protocol_release_connections.py
781a2e0d1d2a9fc7fa0a9b60d8722b28888b0ca420f92d88dc74b0647a6cc161  release-focused/attempt001/command.sh
```

完整16源原hash在attempt中；旧fixture SHA保持原值。查询的possible-source语义已获root确认，
后续docstring措辞不在这次运行中冒称实测。没有新增产品修复、没有运行旧34case/组件/full，
所以18是本次独立新增路径，不与此前34重复计成同一结果。

**本任务结论：PASS_WITH_SCOPE，owned两文件冻结并停止写入。**
只确认本表声明级新组合与拒错，没有实测native throw/对象身份/frame实际释放；
完整P2/16格、C2/D3、M0–M2及源恢复仍OPEN，未授runtime/transform/LeWM性能结论。
