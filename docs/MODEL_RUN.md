# 从已有采集自动组织建模

保存的 source-entry SP5 现可通过 `publish_source_entries` 独立准入，并以
`CompositionIndex.from_source_entry_publication` 查询原 qualified body；普通
`bind_source_invocations` 已在同一 CPU 采集上实际关联 260 次调用。
它保原 SourceDefinitionReference、namespace 和 SP5 URI，不伪造项目 fi/bi；
原生图仍是原 SP5，publication 只导航。此后继现已接为独立
`source-entry-bindings` 通用CLI，真实四阶段门exit0/40.817240s，实际仍为原9groups/
271calls中的260body、5source、6unresolved；它与此前公共API门分别保留资格。
参数/环境/state/return/control 仍未连接，详见
[真实结果](../artifacts/experiments/qualified_source_entry_binding_resume02_20261025/RESULT.md)。

2026-10-25。P0通用离线入口已实现，真实八阶段串联通过；完整程序建模仍OPEN。
LeWM正式source858/runtime843的覆盖不受本次小CPU样例影响。

```bash
python -B -m scar.cli model-run --from-capture CAP --out RUN --plan-only
python -B -m scar.cli model-run --from-capture CAP --out RUN --resume --max-calls 512
```

在lewm conda环境使用本开发树时，先把`PYTHONPATH`设为该树路径。入口接受当前
支持的成功采集目录，使用原始声明中的命令、进程、项目边界和artifact来源。
它不执行采集命令，不导入workload，不接收业务函数名单。缺失的exec cwd、
命令入口、依赖或代码来源不会用分析进程的cwd猜补。

## 自动链路与输出

`--plan-only`读取有总预算的小metadata，不扫描原始trace或编译源程序。
普通模式依次调用既有capture importer、真实source coordinates、verified source
seeds、inventory8、source-layers、composition、fresh source bindings及workload
CodeWitness writer/readonly reader。工作单元和analysis seed由原记录机械确定。

每阶段生成独立目录和started/terminal收据；规范图保持原schema、命名空间及
artifact身份。小`model-run.json`保存导航和资格状态，没有新的可写图权威。
resume保留此前attempt并生成新attempt；P0会fresh replay整链，尚不复用完成阶段。
最新导航根可更新，原attempt及规范产物保持原字节。

此P0使用合法monolithic inventory bootstrap；已有分区路线仍保留。
`SourceFrontend`需要的原lowerer返回checkpoint handoff、partitioned report2/3，
以及native V2/统一覆盖账本接线仍OPEN，不能伪造检查点或前一运行报告。

## 实际门与边界

唯一已有CPU capture的首次G0实际exit2：43954B metadata、raw0，271次调用超过
默认256上限。显式512上限后，同一目录resume的G1实际exit0，八stage完成，
内部124.585290s；约26MB存储，主要耗时为native/OS导入。没有新capture/target/GPU运行。
原G0attempt和首次源码保留，360份当前工具源码的运行前后hash一致。

样例只有module顶层，源码清单1文件、0函数定义/0body，271次调用全部UNRESOLVED。
模块入口缺定义见证1次，另270次是CODE_SOURCE_INCOMPLETE：其中269次/7个Python
code groups的绝对源码位于recorded root之外而未准入，另1次是`<frozen os>`。
外部组包括Torch registry/overload、SCAR工具导入、pathlib及json；不是270次native
或module调用。下一步需自动依赖准入及明确tool/runtime namespace，保原271分母。
这只验证了通用串联及预算/恢复行为，不是完整源码依赖或模型验收。
workload archive单独完成1个compile key和readonly复核，不借用collector代码档。

预算分别报告：小metadata读取硬界、各公共API的raw参数、各stage完成后的record/
stored-output检查，以及外部wall限制。当前没有累计stored+decoded输入硬帽；
post-stage解压校验约999MB是输出校验成本，不是全部输入I/O测量。
超限保留失败和partial，`COMPONENTS_LINKED_WITH_OPEN`不授变换资格。

真实执行、预算与源码版本见
[根复核](../artifacts/experiments/model_run_offline_g1_20261025/ROOT_REVIEW.json)及
[实际结果与归因](../artifacts/experiments/model_run_offline_g1_20261025/RESULT.md)、
[接口和后续接线规划](../artifacts/analysis/model_run_orchestration_design_20261025/PLAN.md)。

## 独立依赖源码阶段

```bash
python -B -m scar.cli model-run --from-model-run RUN/model-run.json \
  --out SOURCE_RUN --stage dependency-sources
```

该入口核对导航和不可变terminal、原source-seeds/binding收据，再仅调用既有依赖准入
及新CodeWitness archive，不重做capture/native/OS/bootstrap。独立预算用
`--dependency-max-*`配置并逐字段记录来源，原bootstrap默认值保留。

真实门实际exit0/36.862007s：原9组/271调用守恒，4份snapshot/source graphs为6组/
265调用建立SOURCE_VERIFIED；新archive4compile keys/6descriptor matches，readonly
4loads/6matches、compile0。工具跨worktree4次和frozen1次未解析；project module1次
保留原scope。源码与编译匹配不是函数环境、actual/formal、状态或执行对应的证明。

该门结束时原G1绑定报告不修改，body-linked仍0；后继entry消费见下节。
正式body publication与新普通binding尚待接线。完整模型及LeWM正式覆盖数不变。
源图bulk按精确local receipts保留，未把全部86MB解码数据复制进导航root。
见[实际根复核](../artifacts/experiments/model_run_dependency_gate_20261025/ROOT_REVIEW.json)。

## 原定义entry、真实return与普通读回

同一CPU样例后继实际exit0/6.771874s：公共SourceEntryCatalog保留6候选及原9组/271调用，
按原调用权重自动选1entry，消费原source/context与readonly CodeWitness，正常sealed
lower返回28ops。相同返回已保存为SourceProgram5，普通STRUCTURE/source与独立code
reader均通过；readonly1load/2matches、compile0，source_prepare0，无raw/native/OS重做。
原260调用仅是所选定义的权重，不能增加runtime覆盖。正式静态858/runtime843不变。

live owned return只在该进程中有效，JSON不能恢复owner。后继可对原SP5 artifact做普通
独立准入，发布CP2未知成本，无需重复lower；publisher/binder及完整第一阶段仍OPEN。
见[实际结果](../artifacts/experiments/source_entry_catalog_gate_20261025/RESULT.md)。

后继CLI已实现`model-run --from-model-run <dependency terminal> --stage source-entries`，
真实门session48967 exit0/7.515233s，1entry/28ops及普通source/code读回通过。它固定
原terminal/admission/archive/source scope，并自动带入
原bootstrap的project composition与独立readonly archive。共同catalog保留全部9/271及
六dependency候选；module无definition明确保留前沿。仅复用现有catalog/plan/worker，
独立`--entry-max-*`默认窗口1entry/1file/4000ops；不重dependency/raw/native/OS，
不混入publication/binding，也不创建第二份图权威。
依赖archive实际1load/2matches/compile0，project archive0load/0match；两类原来源和
module无definition前沿均保留。project+admissions是同原9/271的来源联合，不是新增调用；
它与此前独立entry门分别保留实际producer/profile收据，不倒改历史。见
[CLI实际结果](../artifacts/experiments/model_run_source_entries_gate_20261025/RESULT.md)。

## 已存entry body的自动出版与调用关联

```bash
python -B -m scar.cli model-run --from-model-run SOURCE_ENTRY_TERMINAL \
  --stage source-entry-bindings --out BINDINGS --plan-only
python -B -m scar.cli model-run --from-model-run SOURCE_ENTRY_TERMINAL \
  --stage source-entry-bindings --out BINDINGS --resume
```

该独立阶段固定原SOURCE_ENTRIES immutable terminal、worker成功产物、dependency/
bootstrap输入与两readonly archive，机械取所有成功SP5。默认一个program；数量超限
明确BLOCKED，使用`--binding-max-programs`显式配置，不能截掉其它成功项。独立binding
profile不混用bootstrap/dependency/entry flags。plan-only仅有界小metadata及artifact
stat，不读graph/raw或编译。新source-entries输出精确worker terminal receipt；旧输入
只在所有保存program与原SUCCEEDED总数一致的无歧义情形接受，否则保留成功归属前沿。

实际模式复用既有publisher→ordinary qualified reader/query→fresh genuine coordinates
→v4普通binder，输入从原products自动取得，没有实验目录import或业务函数名单。
SP5 URI不变、CP2成本UNKNOWN，不lower/恢复owner/执行目标/重建native或OS模型。
默认4000ops/128MB source-provider decode，actual raw2MB/2048lines/1024events，坐标
64MB reservations；原seed metadata64MB等profile另列为解码上限，不授当前raw许可。
record64MB/output128MB是既有参数及post-stage检查，外部180s，全输入累计I/O仍OPEN。

resume新建attempt并保旧失败。输出只链接原SP5、规范publication/v4绑定和原project
composition，没有新图权威。当前publisher仅支持qualified external-entry；project
SP5保全部declaration并报PROJECT_BODY_PUBLICATION_ADAPTER_MISSING，不伪fi/bi。
actual-formal/env/state/return/control及完整模型仍OPEN，旧SBA不因新v4自动取得资格。
实现范围与门见[短计划](../artifacts/analysis/model_run_source_entry_bindings_20261025/PLAN.md)。

真实CLI门session71666 exit0：1原成功SP5，独立出版→普通qualified查询→genuine坐标→
v4普通binder四阶段完成，无实验模块import、lower/compile/target/native或OS重建。
readonly依赖1load/2matches、project0；原9/271守恒，260body+5source+6unresolved，
271exits/0orphan。五类未连接接口仍各271，旧SBA2/3不放宽，858/843/6699不变。
本门旧成功归属仅1/1兼容，未把任意legacy partial mapping或project adapter当已通过。
详见[CLI实测与留存](../artifacts/experiments/model_run_source_entry_bindings_gate_20261025/RESULT.md)。
