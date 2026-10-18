# R3.3 同一跨函数 buffered IO 模型实施与 focused 记录

**Implemented / focused Verified（有限范围）**。仅新增 `tests/fixtures/execution_io_pipeline.py`、`tests/integration/test_execution_io_pipeline.py`；没有改旧 fixture、产品/validator、wire/backend/collector。本文不宣称 R3.3 总门或 M0–M2 完成，没有运行 LeWM/GPU/full，没有工作负载加速比。

## 1. 一个规范模型，逐原端口连接

`io_pipeline_execution(...)` 返回 `(program, model, catalogs, details)`。同一个 ProgramGraph：root+C1 cleanup、workflow、load/prepare/run/save/close 共7 Regions；同一 ExecutionModel、run/process/thread；6个真实声明的 CallActivation 逐原 caller/child entry/RETURN或RAISE/actual edge 连接。复用 C1 和动态坐标构造规则，没有把多个独立 factory 的图拼成流水线，没有 FakeContext。

所有共享状态由原两类 Location 域保守承载：coarse world、handled-context。引用身份/当前内容分开，reference read 的未知 effect 显式 Unresolved；Data byte read 可 effect=None，仍有准确 current support。省略精细selector不等于 NONE/无alias；本模型没有声称模型/RNG/文件/内存所有状态都已细分。

load/read → prepare/represent → prepare/materialize → run/submit/wait/consume → save/serialize/write → close/buffer_read/flush/close 的操作都保留原 Uses/StateAccess。静态未执行 helper/branch 的原 ports、resource interfaces仍保留；动态早异常不假造其发生。

- CPU/GPU逻辑物化与读写stage引用 exact ValueGraph artifact/Mat/Region；LogicalVersion/provenance ancestry与当前physical writer分开。VG没有保存tensor数值。
- 真正有2个声明的异步work：H2D与compute；同步read/serialize/buffer write/flush/close没有伪WorkTicket。
- run是实际 `submit → BRANCH`：正常分支才 wait/consume；早期RAISE分支直接构造异常packet，不生成wait/consume occurrence，也没有伪quiescence/borrow release。
- root C1按实际完成保存/恢复pending和handled-context；close新Raise走原Replace。Return/Raise、工作outcome、quiescence、borrow release、handle end不混同；没有从close造target retirement或持久化证明。

## 2. Buffer 层与 file 层必须分开

默认为 buffered 模型：

```text
serialized DataValue / CPU Mat
    → save.write（accepted8）
    → CPU buffer Mat（独立allocation，同serialized version）
    → close.buffer_read：原buffer读+DataValue/DataIdentity
    → close.flush：原Data Use/ContentRead → file Endpoint Mat
    → close.close：原state/handle结束；不作persist证明
```

READ8 是独立profile分母；WRITE_REQUEST8与WRITE_ACTUAL0..8分开，实际flush prefix来自独立raw BytePrefixWrite。DataValue→原producer-owned ContentRead→source Mat/version 的唯一桥由产品固定协议解释，不按变量名/shape/FactRef相等授coherence。

未执行save的早异常路径：有显式empty-buffer LogicalVersion与CPU Mat（shape0、allocation capacity8），close的DataDenotation/ContentRead选择empty版本。flush操作/control/state仍在，但没有假requested8/native0 raw byte-write stage、WriteAssociation或EstablishedProduction。Q reader8仍保留未满足义务。after_save Raise已有buffer8，后续flush仍可能建立file bytes；`written`只控制flush的实际file prefix，不用于假扮worker部分结果。

## 3. 命令、原始失败与修正

统一命令模板（均明确activate lewm）：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_pipeline_closure/focus.py GROUP SELECTOR
```

每次driver保存精确命令/Python版本/完整stdout/stderr/junit/全部registered source前后指纹/returncode。临时basetemp仅在child退出后清理。开发并行，不冒称最终源全冻结。

| 原始attempt | 实际结果 | 归因及最小改动 |
| --- | --- | --- |
| pipeline_skeleton/001 | 1F | 新builder给纯protocol pack误加READ/WRITE行为，原core正确拒绝；仅修builder分类。 |
| pipeline_skeleton/002 | 1P/0.66s | 仅canonical+C1/call骨架；不包含完整resource/content overlay。 |
| pipeline_overlay/001 | 1F | ExternalResource root定义误用于child activation且重复realization；修为每region规范外部定义与单site realization，动态目标仍显式同实例声明。 |
| pipeline_overlay/002 | 1F | Reference read effect=None被原core正确拒；改为显式Unresolved，Data read仍不假造sink effect。 |
| pipeline_overlay/003 | 1F | 模型有效但总预算32768耗尽，测试误要求routes全到达；原truncation保留。 |
| pipeline_overlay/004 | 1P/1.63s | 显式131072有限预算；当时仍是unbuffered初版，不能用于证明后来buffered语义。 |
| pipeline_matrix/001 | 1P/10F/8.42s | **7个产品失败**：同逻辑version的storage RegionRef与endpoint extent dict混送不同geometry，TypeError；交A修产品并保留源候选。**3个fixture失败**：未执行save.write静态ResourceUse将Data source误作handle，原core拒绝；只修为原sink Reference Use。不是“所有原模型都valid”；早先实时汇报已纠正。 |
| pipeline_matrix/002 | **11P/11.20s** | A修混类offers guard后，完整buffered/early-exception/empty-buffer矩阵通过。1条record_property/xunit2警告，junit实际保留了budget属性。 |
| pipeline_empty/001 | **同3个RAISE cases重跑，3P/2.57s** | 仅补empty VV/shape0/capacity8/no-fake-flush-write直接断言；不是新增3个独立case，不累计成14。 |

补正来源保留：root审查指出初版把save.write直接写file只适合unbuffered；因此实际加buffer→file内容边。root随后指出run“全部操作后才Raise”不能对应submit后早异常，已真实拆CFG。root指出未save路径不能继续称serialized8当前内容，已加empty版本。这些是语义修正，不能藏在“验证通过”后面。

## 4. 11个用例的准确范围

1. normal同图全链、准确calls/资源/Mat/source/Q；endpoint conditional MATCHED/COVERED但native/runtime/transform仍False。
2–4. load/run/save实际RAISE、最新部分状态、保留正常静态路径、close cleanup、缺normal输出义务；load/run当前buffer显式empty。
5. close Raise真正Replace旧完成，非恢复旧world/伪正常return。
6. run submit后早RAISE+未观察native terminal，wait/consume不发生、borrow未释放；copy独立完成。
7. budget1与32768均TRUNCATED，完整ProgramGraph/ExecutionModel/Q/source分母与精确pending/cursor保留。
8. 删除CallActivation joins，所有6个调用仍MISSING，不按名字选child；全部activations和Q/source账本保留。
9. buffer accepted8与file flush actual4/read8独立：endpoint MISSING/INCOMPLETE，不借buffer完整性填file tail。
10. 删除flush write/result/support关联但保留独立raw源，endpoint不满足、候选仍未绑定；不是删writer缩universe。
11. flush前观察无未来Completed支持；conditional不能MATCHED/COVERED。

Q仍有required output与external facet；facet无目标/基数保持PARTIAL，不把晚放close/root当persist或整个程序已证明。没有直接将真实OS trace自动匹配到这些声明；CPU/GPU placement也不代表已发生CUDA执行。

## 5. 实际成本与规模（非优化结果）

从 `pipeline_matrix/attempt002/junit.xml` 原property提取至 `budget.attempt002.json`，不是重新运行或估计：normal总用 **115848/131072**，剩余15224，未truncated。产品默认4096未改；提高本组合测试预算不是性能优化。

- 7 regions /68 static operations /171 static values /2 coarse locations。
- 7 activations、23 visits、39 observed operations、108 observed values、148 Uses、16 actual transfers、6 calls。
- 10 content reads、8 raw rows、8 writes、6 established productions、2 work-produced contributions、2 truework/2quiescences/2retentions、1 queueprofile。
- 字节需求8，短写case实际4；非tensor内容快照。
- 主要budget cost：host_order_edges **72892**，host_order_nodes **13475**，geometry **8583**，order_edges **7310**，association_joins **6909**，order_queries **2695**。完整分类在JSON。

跨call host顺序重复扫描是实际成本限制，已通知root/C；本门没有擅自做额外cache/性能开发，也未无限扩大预算。artifact/FK验证、snapshot/replay和detach成本另列，不包含在115848几何/派生计数内。

## 6. 最终 owned 指纹与未验收项

```text
42723a1144309cc544a39a71c78d364de922cd757a0fc0364fc7a8af3cc89c97 tests/fixtures/execution_io_pipeline.py
54ac956439232e9cffaa006485b248fa26a1a45003cd168ef70ffe5c4764fdf7 tests/integration/test_execution_io_pipeline.py
```

fixture在完整11P矩阵后未改；test最后只增强上述3个case的empty断言，并仅对同3节点重跑。原11P时的test hash与最终hash由各attempt source.before/after.json分别保留，不冒称最终hash已另跑一次完整11P。两文件单一LF EOF，现停止产品/测试编辑与测试执行，等待root联合冻结验收。

Source/runtime/native身份、捕获闭包、数值内容、环境/文件协议普适性、fsync持久化、未知effects无alias均未获证明。所有笼统“全过程建模完成/可优化LeWM”结论不由此fixture产生。
