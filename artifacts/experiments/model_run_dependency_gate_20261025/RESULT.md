# Actual source-only dependency gate

Root session14750 actualexit0，GNU external37.70s/RSS225256KiB，internal
36.86200746s。终态`DEPENDENCY_SOURCE_FRAGMENTS_WITH_OPEN`。
**新SOURCE_VERIFIED6groups/265calls，4个原source snapshots及4个source graphs已保存；
这265是源码对应调用数，新增body-linked/publication/binding均为0、均未运行。**
主source858/runtime843、原6699 body-linked，以及G1原271条UNRESOLVED bindings不变。

## Before → after，原9/271不变

| 来源 | groups / calls | G1原source前沿 | 本次dependency admission |
| --- | ---: | --- | --- |
| 当前环境的外部包源码 | 2 / 261 | outside project root | SOURCE_VERIFIED2/261 |
| 当前环境stdlib文件源码 | 4 / 4 | outside project root | SOURCE_VERIFIED4/4 |
| 其它worktree的SCAR importing callback | 1 / 4 | outside project root | UNRESOLVED / NO_ENVIRONMENT_SOURCE_ROOT |
| `<frozen os>` | 1 / 1 | 非文件source proof未有 | UNRESOLVED / NONFILE_CODE_FILENAME |
| 本地probe `<module>` | 1 / 1 | VERIFIED source，definition接口缺 | PROGRAM_SCOPE_RETAINED；未伪造module Function |
| Total | **9 / 271** | body-linked0 / source-only binding0 | **body-linked0 / source-only binding0** |

265包含`find_torch_dispatch_rule`260、`OpOverload.__call__`1、pathlib3、json1；名字仅为
实际描述，不用于选择。6项source links均有原DefinitionID与source atom/snapshot，完整
CapturedCode/anchors在RETENTION.json。原process/code、所有descriptor/首尾anchors、271权重、
raw manifest/完整collector metadata与新公共严格source scan准确守恒；未删除tool4或frozen1。
4snapshots/graphs是producer首次prepare/export原source/semantics/control图，未重lower；
本报告没有独立重解或重验graph语义，不能将其称canonical body或完整ProgramSnapshot。

## 两阶段与实际成本

| Stage | wall s | post-check文件数 | 当时累计stored B | 输出解压检查读B |
| --- | ---: | ---: | ---: | ---: |
| dependency-sources | 36.62764540 | 338 | 12,494,347 | 86,130,529 |
| dependency-witness | 0.22412595 | 11 | 12,939,462 | 0 |

本门未重做G1的121.56s native/OS import，也未运行G1八阶段、source inventory/composition、
完整binder或target/package import。source API只做一次原call trace严格扫描，其3个
trace_files报告的已核raw长度合计536,684B；这不是进程累计I/O计费。

* 独立source profile配置全部来自DEPENDENCY_PROFILE_DEFAULT，逐字段来源已存root；
  原bootstrap256calls/4sources默认未改。max_calls512/max_codes16实际9/271。
* 6sources/1MB预算下，实际4files/129,708B，source_prepare_attempts4。
  compiler variants reserved12/cache entries12，独立21上限。不是body operation数，也不冒称
  覆盖全部隐含compile调用。scratch compressed3,841,327B/uncompressed14,565,374B。
* Provider metadata实际目录entries338、files328、bytes7,628,414，分别在4096/512/16MB界内。
  源图/快照/provider archive canonical86,130,529B、compressed12,444,970B，独立总256MB/
  record64MB界内。4图的canonical bytes由原artifact declaration保存，未在本报告解压。
* 新CodeWitness archive4compilekeys/6complete descriptor matches；只读重开4module loads/
  6matches/compile0/source_read0，无witness frontier。source read129,708B；21key/32MB
  archive独立上限。没有填旧G1 archive，也没有合并collector archive或伪造旧compiler origin。
* Planning stored metadata130,047B + decoded144,910B=274,957B，在2MB独立界内；source
  producer/provider/图检查读量另计。output解压检查86,130,529B是本次producer自己的
  post-stage成本；不是本报告重读，也不是全流程input stored+decoded总数。
* raw64MB是各公共source scan参数；input cumulative stored+decoded I/O仍OPEN。
  record/output为post-stage检查及producer独立硬界，stored128MB非连续硬帽；外部timeout180s。
  最后stage snapshot12,939,462B；最后terminal加入后的attempt stat 13,099,932B，
  加当前导航root为13,256,386B，三个计费时点不可混写。

## 准确端点与下一断口

root SHA `a4a3cffb43094f534625c0c59a84716cca786a20a1a5c8a6ceb3fdecdee28a04`；terminal SHA `6860b920d121bf09d044f608a8df1402d683e4a6a31c0c6559afbd9cb10dffe3`。
本门输入仍为G1 immutable terminal
`a61b3d1ba30e9411aed726a882253aa92b5682a5872fdcf889326e55983433e0`；G1原导航/attempt
未改。本门freeze SHA `cc32dbf6ffad762ed1a354e3d25b17050c61c9a4e75e68f6b984aa10d3353616`固定360源码与两入口；root负责独立全源码
字节对照，本报告不冒用其未来结论。原G0 exit2预算stop及G1 exit0历史保留。

已闭合的是当前命名空间内6个Python code与准确source/compile descriptor对应；当前安装
METADATA/RECORD ownership、当前Python/stdlib版本不是采集时package/binary版本证明。
原tool root、frozen provider、module entry独立保留；data/state/content、调用环境、ordered
runtime Uses、Python↔native occurrence、object identity和ready均OPEN。

**下一阶段应真正把这6项原DefinitionID及root/graph/snapshot依据接入普通entry catalog与producer-owned
lower-return/proof handoff，再走普通publication/reader和source binding。** 当前monolith/
source-invocations1不能假扮partitioned/source3；外部definitions尚未进入SourceFrontend
body dispatch，higher witness wrapper也不自动选择外部attachment origin。本门没有继续跑
continuation来堆叠sidecar，也没有fabricate file/body/CP1或放宽这些guards。只有下一断口被
实接并实际验证后才能讨论新增body计数；不得将265直接加进旧binding/6699。

RETENTION.json与STAGE_PATHS.txt列出small candidates及local-only stored receipts。
本报告仅读小root/admissions与stat；没有再读/解压86MB graphs/provider archives，无新测试、
producer replay、生产修改或Git操作。local graphs/unused provider evidence仍依赖本机原URI，
这些小文件不是完整可搬运模型。
