# 按需查询跨层程序图

`query-program`读取已有分片关系，沿原始限定引用查询work、runtime/算子、Python调用、
源码定义和静态函数体。查询结果不是新的可编辑IR；其中节点键仅供本次结果去重，
每个节点仍保存原类型、ID、artifact版本和命名空间。

在项目目录、`conda activate lewm`后运行：

```bash
python -m scar.cli query-program \
  --relations PATH/manifest.json --sha256 EXPECTED_SHA256 --limit 20

python -m scar.cli query-program \
  --relations PATH/manifest.json --sha256 EXPECTED_SHA256 \
  --work work_relation:QUALIFIED_HASH --expand-static --out query.json
```

第一条只分页读取紧凑索引；`--offset`接续分页。第二条使用正常关系reader重新核对
选中work的原始端点，输出节点、带类型的边、原依据、具体缺口和读取成本。
`--record`可附上完整原关系。输出文件必须为新路径，不覆盖既有结果。

查询中的关系分别保留：

| 关系 | 含义 |
| --- | --- |
| `WORK_ACTIVITY_PROJECTION` | 原work到provider活动的投影 |
| `SUBMITTED_BY_RUNTIME` | provider记录的实际提交关系 |
| `PROVIDER_SCOPE_CONTEXT` | provider上下文关联 |
| `COLLECTOR_SCOPE_PARENT` | 原collector栈上的父层上下文 |
| `ORIGINAL_EVIDENCE_BINDING` | 规范native occurrence对应的原provider记录 |
| `RETAINED_SOURCE_CONTEXT` | native关联的Python invocation上下文 |
| `CODE_SOURCE_BINDING` | 当前捕获代码到其准确源码版本 |
| `HAS_STATIC_BODY` | 原源码定义到规范静态函数体 |

上下文关系不证明Python直接调用；静态体展开不证明其中所有路径执行过。
输入/状态内容、逻辑版本、ready和跨调用数据流由各自原关系提供，不能从这条路径
补猜。缺失关系保留在`gaps`；查询成功不表示全程序完成或允许优化。

## 本次真实运行

结果保存在`artifacts/experiments/program_query_20261026/`。使用既有LeWM的24,082个
GPU work关系，未重新运行episode，也未修改LeWM。

- 索引第一页：仅读取43,381字节stored、109,601字节decoded；reader约0.0067秒。
- 选中一个真实work：原端点校验通过；8个去重节点、10条关系，贯通work到源码body。
- 展开同一body：正常codec读取原Region，原始运行依据保持；reader约2.80秒。
- 错误manifest SHA被拒绝；所有返回边都有结果内的准确端点。

单条完整校验仍读取约163.3MB（stored与decoded合计，包含正常reader重复读取），
当前不能称为轻量。后续在不改变来源/版本判定的前提下复用会话级不可变记录。
`verification.json`保留实际成本。最初缺少本地归档端点的失败保留在计时记录中；
仅恢复原Git对象的准确分片后重跑成功，没有生成替代证据。

## 跨函数数据端口和文件资源

```bash
python -m scar.cli query-call-ports \
  --model PATH/model.json.gz --sha256 EXPECTED_STORED_SHA256 \
  --invocation PID:TID:INVOCATION --direction callee --actual-index 0

python -m scar.cli query-os-file-topology \
  --manifest PATH/manifest.json --sha256 EXPECTED_SHA256 \
  --path weights.pt --limit 3
```

跨函数查询按完整调用身份、attempt或参数序号选择，保留caller/callee原body命名空间、
有序Use、formal slot/value、原调用/入口依据和条件。默认可枚举少量已绑定调用，
`--direction caller`同时列出该调用者的具体未绑定原因。这里只校验准确保留的模型
transport；不重新运行producer，也不据端口连接推断对象身份、内容或return关系。

真实LeWM归档为100,550 attempts，每项均有binding或issue；其中2,516 calls有6,805
argument ports。选中真实callee 40398的第0参数，查询准确返回`to_pygame`的`p`端口
和调用者的原Use。结果在`artifacts/experiments/call_port_query_20261026/`。
原runner最后的legacy比较字段写错，原exit1保留；生产consumer已完成，独立postflight
核原输入并确认旧27条调用关系全部保留。查询成功不改变该失败历史。

OS查询返回原syscall/work/actor/handle依据及逐项资源路径；不将路径导航候选当作
已绑定的文件身份。本次checkpoint查询能找到原read和work，状态明确为共享/未知
FD绑定未决，`resource_path`为空；不能宣称已经连接到NVMe。

## 原生 Tensor 输入

```bash
python -m scar.cli query-native-inputs \
  --manifest PATH/port-navigation/manifest.json --sha256 EXPECTED_SHA256 \
  --row 21 --associations --limit 2
```

省略`--associations`返回原元数据行；`--row`使用原 companion 行号。读取已发布的
压缩分块，不重跑目标或扫描临时索引。返回值保留原native输入、ValueOccurrence、
provider位置和元数据来源；这是保留产物查询，不恢复producer会话。

本次原LeWM批次156片/39,796个规范边界实际通过，65,130条Tensor输入路径已关联，
355,314条仍为`CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE`。后者包含真实库内算子，
不能都称为注解。已发布父片导航为这65,130条关联提供原ProgramSnapshot/execution/
denotation限定端点；普通typed样例读回核对ValueOccurrence及实际UseOccurrence复合
端点，不制造新的UseOccurrence ID。原metadata manifest只用于行查询，端口关联须
使用port-navigation manifest。查询不建立内容、alias、状态或ready事实。
