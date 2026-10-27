# 分片inventory → 原source/body组合 → 本次真实调用

状态：**Verified：本次 compose / same_capture 来源绑定通过；完整阶段 OPEN。**
输入是已发布840body/151source的分片manifest，复用原151source archives，不使用旧54body
inventory、不prepare/重lower、不拼单JSON。固定272038 capture，不混新369749物理采集。

`producer.json`保存revision、实际模块和脚本SHA及输入收据；`implementation.patch`
保存本轮两个修改模块；`progress.jsonl`逐source及阶段保存elapsed/RSS，`run.time.txt`
记录整进程wall与peakRSS。只读目标/原档，原图/producer/state保持不变。

新composition和source-bindings/report使用schema2，保留真实source-shard/CP/component
locator与canonical namespace；旧schema1保持兼容。未知/unsupported与全部原invocation
保留，retained ancestor不升级directcaller，完整模型及优化许可保持False。

## 实际运行

`run.sh` 使用 conda `lewm`，实际 Python PID 391812，执行会话 17409，exit 0；
`run.stderr.txt` 为空。基线 revision 为 `49ea6f032c6a95c39801ccc0d188a2ae179ef14a`；
实际未提交代码的 SHA 与 patch 均在启动前保留。

| 项目 | 实测 |
| --- | ---: |
| 151-file compose | 662.44 秒 |
| 独立坐标核对 | 5.41 秒 |
| same_capture 原档全扫及绑定 | 197.48 秒 |
| 整进程 wall（time） | 14:26.32 |
| peak RSS | 814,720 KiB |
| 新 prepare / lower | 0 |
| 新目标执行 / GPU episode / 测试套件 | 0 |

这里的运行时间是建模工具耗时，不是 LeWM benchmark 或加速比。

## 输入与身份

- 分片 manifest：`../first_stage_full_inventory_restored_20261023/result/manifest.json`，
  63,577 字节，SHA `1443fedcbd8882e86dee392339a5ea51fd29ea102068a65d9e51e06b347de09e`。
- 原 source archives：`../first_stage_source_context_20261022/result/source-layers`；
  `index.json` SHA `5c68691c28273676a8262f24fe9891e03433f06b7d16758e8620050c160a97c4`。
- 本次运行：`../first_stage_lewm_dispatch_20261023`，PID 272038，
  Run `capture:91a2ed5e3f92817799bd02fb2453dadd65ad28fbf4361165c31b881c371c0c66`。
- 本次 call-events 原档：200,876 行，187,485,595 字节，
  SHA `f44ee6c7616566f8cf670b51de23afd0cae33cd4929cd18443af177d4e463ff9`。
- binder 独立预算：raw 256,000,000 字节、300,000 行、250,000 events、
  2,000,000 references；坐标独立预算 2,000,000,000 字节、2,000,000 行。

分片输入通过正规 `CompositionIndex` schema2 读取；原 schema1 保持兼容。
source 的 snapshot/context 与旧 archive 逐份核对；canonical graph 沿用原 codec。
locator 指向真实 source shard、component 和原检查点，原 physical/decoded SHA、
原 pointer、实际表示版本与 body namespace 均保留，不产生虚构 root manifest pointer。

实际生产模块 SHA：

```text
program_composition.py  fb8d5d148260c8b9d199425c97930157d30b9ae88d0a285e7435fdf0473988d2
source_invocations.py   5a2e35b6de42e084286bd50455e0662131eb4cb383279f575a8a13ce753ce38e
inventory_partitions.py edc39a1ea3ab36e5758e083ab7a877256c128c6c08300d4182376fcb0c5ff27e
```

## 实际分母与缺口

| source composition | 数量 |
| --- | ---: |
| 文件 / 全部索引文件 | 151 / 151 |
| definition / body header | 2,217 |
| canonical body | 840 |
| UNSUPPORTED / NOT_ATTEMPTED | 787 / 590 |
| source atoms | 122,323 |
| semantic operations | 114,560 |
| CFG suites / nodes / edges | 6,916 / 65,880 / 78,691 |
| control regions | 5,587 |
| 条件调用目标（未升级为实际 dispatch） | 263 |

原 canonical body 合计 66,112 operations、105,824 values。151 个 module initializer
仍没有 canonical body；590 个未尝试 body 中，581 个是当前 class/lambda/comprehension
接口缺口，9 个受原 aggregate construction budget 截断。unsupported、source/control、
effects 和跨函数边界缺口见 `composition/summary.json`，没有因索引覆盖而改成已闭合。

| 真实调用绑定 | code group | invocation |
| --- | ---: | ---: |
| BODY_LINKED_REUSED_WITNESS | 74 | 5,624 |
| SOURCE_LINKED_REUSED_WITNESS | 351 | 3,162 |
| UNRESOLVED | 392 | 91,652 |
| 总数 | 817 | 100,438 |

捕获 CodeID 共 855，817 个有 entry 的 descriptor 均完整匹配。100,438 个 entry 与
100,438 个 exit 全部保留，orphan exit 为 0。96,799 条记录是 direct parent，
3,638 条只有 retained ancestor，1 条无 parent；96,416 次通过 frame interval
资格核对，4,022 次保持未解析。`REUSED_WITNESS` 表示复用原源码证明，
本次 `witness_mode` 仍严格为 `same_capture`，没有拿其他运行的调用事实替代本次事实。

具体 invocation frontier：

```text
CODE_SOURCE_INCOMPLETE                    87505
VERIFIED_CODE_WITHOUT_DEFINITION_WITNESS   4147
CANONICAL_BODY_UNAVAILABLE                3162
FRAME_RESUMPTION_CONTINUITY_UNRECOVERED    4021
PARENT_SUSPENDABLE_FRAME_OBSERVATION       4021
PARENT_NO_PARENT_ENTRY_WITNESS               1
```

每个 invocation 的 actual/formal、返回值、function environment、state/effects、
canonical completion 仍未闭合。`whole_program_graph_established`、
`execution_model_established`、`first_stage_complete`、`transformation_authorized`
均为 false。来源绑定成功不等于程序完整建模通过。

## 可查产物

- `composition/index.json.gz`：新 schema2 组合索引；原图不复制。
- `bindings/report.json`：完整 raw 扫描、同 capture witness 核对、输出 SHA/分母与缺口。
- `bindings/bindings.json`：每个 process/code 一次来源/definition/body/locator。
- `bindings/invocations.jsonl.gz`：100,438 行，原 invocation、坐标、parent 资格及原 namespace。
- `bindings/capture-coordinates.json`：本次共同坐标独立文件。
- `locator-examples.json`：从既有 binding 提取的三种状态示例，不另跑建模。
- `summary.json` / `progress.jsonl` / `run.time.txt`：真实计数、阶段耗时与 RSS。

## 下一步（Proposed，未执行）

369749 是另一次 `first_stage_lewm_physical_20261023` capture，不能使用 same_capture，
也不能复用本次 InvocationKey/Run/PID 或祖先关系。只复用完整 CapturedCode / pycode-v2、
精确 source snapshot、definition 和 canonical body 的代码来源证明；当前源 fingerprint
漂移或无匹配 descriptor 的代码保留 frontier。必须完整独立扫描 369749 自己的 raw 档。

下面为基于已读 collector metadata（200,876 events、855 codes、无 dropped event）的
最短现有 CLI；只作为下一步命令，不属于本次已执行结果，且 output 必须是新目录：

```bash
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" python -m scar.cli bind-source-invocations \
  --composition artifacts/experiments/first_stage_partitioned_composition_bindings_20261023/composition/index.json.gz \
  --capture artifacts/experiments/first_stage_lewm_physical_20261023 \
  --witness-mode reused_code \
  --max-call-trace-bytes 256000000 --max-call-trace-lines 300000 \
  --max-call-trace-events 250000 --max-call-references 2000000 \
  --max-bytes 2000000000 --max-lines 2000000 \
  --out artifacts/experiments/first_stage_source_bindings_physical_20261023/result
```

它不会重新 prepare 151 个文件；SCAR 自身源码已漂移时必须保留其 source frontier。
后续 dispatch/native/OS 联合仍只能使用同一次 369749 的 provider 原档与共同坐标，
不能接入本次 272038 的 marker。此实验不新增 detector/backend，不执行优化。
