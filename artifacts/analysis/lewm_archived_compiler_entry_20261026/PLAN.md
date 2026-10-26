# 原归档源码 → 新独立 CodeWitness：仅三个生产文件的 API 切面

设计未实施。G0 session57836已actual0；原817/100438全部保留，243 external候选中
16有metadata key、227缺key。当前11969门的原20key不变；本切面不做publication3、
current-Run static reuse、SBA、CLI输入扩展或新AST支持。

## 1. source_attachments.py：原snapshot文本的有界只读出口

新增 `SourceAttachments.archived_source(snapshot: SourceSnapshot)`，只允许精确typed
snapshot等于原VERIFIED link中保存的snapshot与原source-file记录；先正常
`require_unchanged()`，再按既有 `_artifact_path/_aux` 读取原 `snapshot_artifact`。
continuation保持PARENT/CONTINUATION的准确root、parent report SHA、origin与locator；
direct-admissions也按其现有明确分支处理，不互相伪装。

返回原normalized text、typed SourceArtifactLocator及原encoding/raw SHA/bytes信息。
独立核原URI、namespace/root、raw base64字节SHA/长度、tokenize encoding、universal
newline文本与SourceSnapshot fingerprint全部相等。缺snapshot是具体frontier；hash、
namespace、源码字节矛盾硬拒绝。不调用source_view/definition_reference/_view，不解
source graphs，不读live文件，不宣称definition membership、当前guard或Run资格。

## 2. code_witness.py：显式导入原源码输入，不接受成功flag或任意text

新增 `CodeWitnessStore.admit_archived_source(snapshot, *, source_owner)`，只允许新owned
writer（create=True），source_owner必须是正常构造的精确SourceAttachments，方法内部
调用上述普通出口并重新核normalized fingerprint。API不接受序列化owner、可信bool或
caller给的裸text作为来源证据。相同snapshot若已有source，原规范text须完全相等；
冲突拒绝，不覆盖旧store。

沿现有 `_write/_publish` 保存UTF-8 normalized source；原source record保snapshot与
source artifact收据，额外明确原snapshot locator、owner完整report/parent收据、encoding/
raw SHA，区分新归档输入与当前live读取。旧text()/resolve()默认及旧manifest读取不改。
这一步只存输入，不授CodeType；随后正常
`resolve(captured,snapshot,recorded_optimize_levels,allow_compile=True)`仍使用现
compile_cache_key（原compile filename/path、准确recorded future flags、dont_inherit、
optimize、Python/build），调用compile不exec。source读自刚保存的归档文本。

新模块必须在独立readonly reopen中 `resolve(...,allow_compile=False)`，并完整
`describe_code(CodeType)==CapturedCode` 才可报新witness。metadata key或source指纹
本身都不是该证明，也不证明函数对象、defaults/globals/closure/state。

## 3. compiler_witness_archives.py：原continuation观察资格进入现有acquisition

保留现 `plan_observed_witness_acquisition(composition,definitions,archives,...)` 原合同。
新增窄入口（名字可在实施时统一）：

```python
plan_attachment_witness_acquisition(owner, archives, *, origins=None, budget=...)
acquire_attachment_witnesses(owner, archives, fresh_out, *, origins=None,
                            producer, budget=..., store_budget=..., progress=None)
```

owner是正常SourceAttachments，archives是明确readonly CompilerWitnessArchives。
origins=None机械枚举全部原SOURCE_VERIFIED组；可选tuple[EnteredCallCode,...]只能是
原组唯一子集。新request重新从原owner.code_witness得到完整CapturedCode、原
CodeSourceLink/snapshot、recorded optimize levels、原record/source-link/descriptor
locators及原Python build；不从caller保存的plan、成功状态或当前PID猜补。
request_id绑定这些完整来源和原snapshot artifact。所有817组/100438 calls仍在summary，
未选/缺来源/预算不足逐项保留；原272038不改为369749。

共享现有acquisition的写者/attempt checkpoint/readonly replay循环：已有metadata
variant先正常readonly完整match；缺项才调 `admit_archived_source` 并正常resolve。
新archive生产者明确ORIGINAL_ARCHIVED_SOURCE、准确输入与当前compiler字节版本。
不能追加旧20key或CPU4key。缺证据与真实descriptor/source矛盾分开记录，不能把
硬矛盾吞成UNSUPPORTED。compiler阶段不伪造SourceDefinitionReference或semantic
membership；后续原catalog.resolve仍须对原source graph独立核membership。

## 下一门与当前窗口预算事实

先syntax/API小检查，再Root持有一次16-entry/8-file缺key窗口；用G0保存的原window
自动选全部项，不按函数名单。精确source原件/flags/optimize先固定；初始保守上界为16个原组各最多3个
recorded optimize variants=48个请求；实际按完整compile_cache_key（含future flags）
去重，不从文件数推定key数，不因已有key重复编译。source文本/records/archive/time等独立预算从原snapshot声明
申请，超界保未试，不能静默抬旧20-key限制。原声明8图stored16,307,247B/
decoded143,780,744B只是后续body的上下文，不在本compiler门打开。

另一个**已有key**窗口16entries/4files可先独立readonly匹配后走原普通worker；其4图
声明stored8,781,306B/decoded75,553,689B，最大单图35,453,004B，加G0已验证aux
canonical13,890,260B为89,443,949B unique声明工作集，原128MB unique-selected界可容。
该界不是重复解压总量；实际reads另报。不预填成功16或14299当前body calls，不重
已成功15个project图。两窗口的出版/369749接线/SBA均另候Root批准。
