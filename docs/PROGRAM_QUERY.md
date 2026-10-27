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

原生 Tensor 的条件读取也可在同一种只读视图中查询：

```bash
python -m scar.cli query-native-read \
  --read PATH/read.json --sha256 EXPECTED_SHA256 --out read-view.json
```

普通 reader 重核原端口、调用状态、分配和协议来源。视图连接原引用 occurrence、
Use、operation、状态输入/正常状态接口、allocation、读取区间和新符号值版本，
复用原 artifact/ID，不复制成第二套权威图。`CONDITIONAL_READ_RESULT` 仍带全部条件；
不把对象引用当数据身份，不宣称已观察实际读内存、内容相同或 value ready。
当前 producer 只有固定 PyTorch 版本的 CPU `copy_` 源端口协议，不是全部算子的内容恢复。
真实 LeWM 旧采集的一项读回为 11 节点/12 边、CLI 4.731 秒，累计读取93,799,844字节
（stored+decoded），不是全程序建图时间。见
[真实结果](../artifacts/analysis/native_read_query_20261027/RESULT.json)。

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

查询现在同时返回原 `binding_index`，可继续追正常返回：

```bash
python -m scar.cli query-source-returns \
  --model PATH/model.json.gz --sha256 EXPECTED_STORED_SHA256 --binding-index 0
```

它复用原 caller/callee 命名空间、callee 的 NORMAL terminal Use 和 caller 的
CompletionResult(0)/landing Value；world 不混成返回对象。原状态端口仍在规范图中，
此命令尚不新增跨调用 world 连接。
多个返回点保持带条件的 may-sites，不能据此认定运行中选中了哪个返回点。
真实 LeWM 的 `DrawOptions.draw_fat_segment → to_pygame` 已用 public CLI 贯通；
两个可能返回点均保留，实际返回选择、对象同一及内容等价未证。
首次真实读取暴露旧压缩 composition/checkpoint 适配遗漏，已按其原格式补齐。
正常 CLI exit0/31.318s，读取24.15MB stored/182.37MB decoded，body仅解码/建索引各两次；
会话内可复用，整份旧 binding/composition 读取仍较重，尚非轻量全局查询。
记录见 `artifacts/experiments/source_normal_return_main_20261026/lewm-query.json`。

同一命令增加`--include-state`，可同时查询调用的状态接口：caller最后一个world Use
→callee入口world，以及callee正常/异常出口的world Uses→caller对应CompletionResult
和landing value。它引用原状态位置/版本和原控制边，不把world当Python返回对象，
也不推断callee无副作用、状态保持不变或细粒度footprint已经可知。

真实同一LeWM调用已普通读回：一条状态入口、NORMAL的2个可能状态出口、RAISE的
19个可能状态出口，均接回各自caller完成边。实际退出分支仍未选择；结果是静态
条件依赖，不是声称该调用真的抛出了19次异常。CLI exit0/30.440s，两个body各解码/
建索引一次，状态查询复用同会话，未另存一套状态图。结果为同目录
`lewm-query-with-state.json`。

## 精简且可展开的源程序区域

```bash
python -m scar.cli query-source-region \
  --source PATH/body.json.gz --sha256 EXPECTED_STORED_SHA256 --out view.json
```

接受原 SourceProgram、body checkpoint、canonical ProgramGraph 和独立 body fragment。
`--region`选择原 Region，`--expand-lowering`显示原语言管理步骤。默认只合并同一
原 Block 内连续的已知管理编码，不跨分支任意合并同类节点；未知操作仍可见。
`ProgramRegionView.expand()`返回原操作，`value()`返回原值及消费者。Use/Value/
Operation/Region ID 保持原命名空间；展示节点键仅在本次查询有效。

真实239操作样本显示134节点，714次Use分为628跨节点和86内部Use，76状态访问及
121控制边保留。每个原操作恰属一个展示节点，控制/退出/效果未删除。这个命令
只读规范core结构，不重新验证全部source context，不授变换许可。
记录见 `artifacts/experiments/program_region_view_20261026/verification.json`。

### 文件资源引用

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

## 全量原生输入输出端口

```bash
python -m scar.cli build-native-ports \
  --eto PATH/execution-trace.json.gz \
  --archive-index PATH/archive-index.json --archive-sha256 EXPECTED_SHA256 \
  --bundle PATH/bundle-partitions --out fresh-native-ports

python -m scar.cli query-native-ports \
  --index PATH/native-ports/index.json --sha256 EXPECTED_INDEX_SHA256 \
  --bundle PATH/bundle-partitions --ordinal 16
```

生成器单次流式解析整个原ETO，顺序复用原instance，共享definition/schema/provider
引用，按source ordinal分片；不再限制为前128个节点。分片确定性gzip，index保存
stored/decoded收据，局部查询只解一片。省略ordinal只读小index和计数。
新的model-run bootstrap在已有lossless coordinates及partitioned native bundle后
调用同一producer；plain旧route保留。此接线已实现，未为它重跑完整bootstrap/import。

真实全源310412节点中，190498项registered schema、40320项无schema CPU算子，
共230818原实例/1256501个有序端口。79592注释不另造操作；另2项是原provider的
thread/process根，保在原bundle中。76压缩片合计22030062B，包含index共22059963B。
构建与首次查询163.811s；压缩后主树public CLI局部查询exit0/1.551s。
bulk分片在本机两工作树间硬链接，共享原不可变内容，没有复制额外22MB数据。

用`--provider-reference REF --descriptor-id ID`替代ordinal可查同一原provider描述的
所有端口出现及原EvidenceEdge。主树真实查询找到11项（6input/5output）及11条原边，
11.845s；只对命中行做typed解码，其余行按原hash/JSON/range检查，未授整片类型证明。
它连接引用观察；不将多次输出误当唯一producer，也不推断LogicalVersion相同。

方向/path/type、既有formal slot及Tensor provider/descriptor引用来自原记录；
非Tensor formal缺口仍明确保留。端口观察不证明normal完成、LogicalVersion相等、
alias/写入或ready，不能拿这些计数当全程序图完成。实际记录位于
`artifacts/analysis/native_port_sidecar_full_20261026/`。

### 原生输入的上游引用导航

```bash
python -m scar.cli build-native-reference-flow \
  --ports-index PATH/native-ports/index.json --ports-sha256 PORTS_SHA \
  --bundle PATH/bundle-partitions --out fresh-reference-index

python -m scar.cli query-native-reference-flow \
  --index PATH/reference-index/index.json --sha256 REFERENCE_SHA \
  --ports-index ORIGINAL/native-ports/index.json --ports-sha256 PORTS_SHA \
  --bundle PATH/bundle-partitions --ordinal 17 --input-path 0
```

索引复用原provider reference、descriptor、instance、formal slot及EvidenceEdge，
按引用分组保存有序出现；不展开output×input笛卡尔积。查询只读目标分组所在片，
返回限定数量的`reference_flow_candidate`。原port index URI/SHA保持准确来源，
不能把相同字节的新路径静默当作原命名空间。

真实全量310412节点/230818实例/1256501端口中，533490个Tensor引用端口全部匹配
唯一原EvidenceEdge（311399 input、222091 output），69362组同时具有两方向端口。
128压缩片34448256B（decoded776703548B），最终成功构建222.666s；这些是离线
索引构建成本。主树公共CLI对ordinal17/input0的查询exit0/2.981s，返回ordinal16的
一个可能输出及两端原edge IDs；没有重采或重导入原图。

ETO ordinal只表示导航顺序，不是完成、happens-before或唯一producer证明。
内容版本、alias、write、effects及ready仍须由各自关系限定；该索引不创建LogicalValue，
不证明因果def-use，也不授复用或变换许可。记录见
`artifacts/analysis/native_reference_flow_20261026/`。

## 对象引用旁的符号数据结果

```bash
python -m scar.cli query-symbolic-output \
  --projection PATH/lift_fresh_output_checked.json --sha256 EXPECTED_SHA256 \
  --occurrence exec_value_occurrence:ORIGINAL_OUTPUT
```

原canonical Tensor端口是ReferenceValue；不能把对象引用直接解释成Tensor内容版本。
新关联保原ObjectIdentity不变，单独为同一限定输出端点命名payload符号，并以现有
ValueGraph存LV/version/UNKNOWN provenance/region=None Materialization。不同符号ID
不证明数值不同，版本0也不是Tensor._version；输入内容版本、copy/alias和ready均未知。

真实lift_fresh输出已自动完成一次构造/codec读回/合并视图验证；原program/execution/
evidence/values不变，新增仅1组符号。factory在调用者预先限定的记录上检查关系，
query核publication receipt/内部一致性，二者都不重放所有来源。尚未接全量producer。
记录见`artifacts/analysis/symbolic_native_output_20261026/report.md`。

同一值模型已扩为原native operator的有序实参/结果接口：

```bash
python -m scar.cli query-native-operator-value \
  --publication PATH/operator-values.json --sha256 FRAGMENT_SHA \
  --ports-index PATH/native-ports/index.json --ports-sha256 PORTS_SHA \
  --bundle PATH/bundle-partitions --ordinal 21686 --direction output --port-path 0
```

真实view→add_→view片段中，4个Tensor实参、3个结果各有端点局部符号。每个结果的
UNKNOWN/Inferred provenance仅连该实例报告的实参符号，parent列表不是已知内容
依赖或完整最小依赖；跨实例reference候选不成为parents。may-write/may-alias分别
指原EffectSummary、formal slot和原port，物理region仍仅作为有来源的候选引用。
原操作/引用图未改，未断言实际写入、copy/view内容等价、normal或ready。

片段74854B；主树公共query exit0/3.109s，可查询add_两个原Tensor实参、一个结果、
DECLARED_MAY_WRITE与SCHEMA_MAY_ALIAS。尚不是全量值生命周期producer。
记录见`artifacts/analysis/native_operator_value_interface_20261026/`。

完整native接口已有自动producer，无须人工给三个示例ordinal或组装定义映射：

```bash
python -m scar.cli build-native-operator-values \
  --ports-index PATH/native-ports/index.json --ports-sha256 PORTS_SHA \
  --reference-index PATH/reference-flow/index.json --reference-sha256 REFERENCE_SHA \
  --bundle PATH/bundle-partitions --out fresh-value-declarations
```

query命令把`--publication`换成`--declaration-index PATH/index.json`，SHA对应声明index。
普通source range/原instance、port、schema与provider目录完整扫描一次；声明只保存
原76片的准确收据、逐片计数、ID推导profile及producer版本，目标operator的现有
Fragment/ValueGraph按需派生，不保存第二份巨大的符号图。原数据和schema仍是依据。

实际完整扫描230818实例/1256501端口，Tensor端口533490的descriptor/device均已
解析；schema190498、无schema40320。formal467756已解析、788745未解析保留unknown。
4034项may-write、100859项may-alias仅为声明接口。总263.202s，index77514B；没有
持久化符号或ValueGraph记录。共享catalog预加载后的单query2.519s；新进程还需
catalog加载，不能把warm query当冷启动成本。主树fresh-process公共query实际exit0/
36.812s（含catalog加载）；目前冷查询仍偏重，进程内可复用catalog。完整报告见
`artifacts/analysis/native_operator_value_declaration_20261026/`。

程序侧IO可通过`trace --stream-interfaces`和`query-stream-interfaces`获取实际builtin
接收者、声明状态接口和C_RETURN/C_RAISE，精确连接原CALL行。范围与实际GPU+OS
联合读回见[STREAM_INTERFACES.md](STREAM_INTERFACES.md)，canonical/backing连接仍未闭合。
