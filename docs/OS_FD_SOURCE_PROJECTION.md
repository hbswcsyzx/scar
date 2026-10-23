# 既有OS handles的真实FD来源投影

2026-10-23。**Implemented + Verified（既有handle范围）**：唯一新生产文件
`scar/trace/os_fd_source_projection.py`；R1/R2/core、coordinates、FD contexts、source helper、
runtime和CLI未改。唯一真实投影gate已exit0，见末节；完整模型仍OPEN。

## 公开接口

```python
inputs = FDSourceInputs(
    capture_root=retained_capture,
    selected_manifest=published_fd_context_manifest,
    archive=original_archive,
    coordinates=original_coordinates,
    projection_files=original_non_main_file_receipts,
    context_events=original_non_main_context_events,
    context_evidence=automatic_context_evidence,
)
result = build_os_fd_source_projection(
    base, verified_selected_view, inputs, fresh_output,
    budgets=FDSourceBudgets(), progress=progress,
)
projection = OSFDSourceProjection.read(
    base, verified_selected_view, inputs, result["manifest_receipt"]["path"],
)
for selected in projection.iter_handle_records():
    ...
one = projection.record("handles", original_handle_ordinal)
resolved = projection.combined_resolve(actual_provider_selector)
```

`base`必须为公开`OSResourceBase`；selected view必须为公开验证后的
`OSFDTableContexts`，并与显式manifest完整bytes/SHA/schema/Run及其typed registry一致。
调用者不能传一个handle dict授予authority。公开查询ordinal是查询坐标，不是构建工具
需要手填的actor/TID/source位置；构建请求从全部原handles与当前选择视图机械生成。

## 范围与证据

原R1公共reader完整读取已有handles/resources/artifacts小表；既有selected ProviderHandle
保留原record/source/selector，未解析端点自动生成source请求。由原coordinates、精确
archive logical/local映射获得actor与birth需求。已核context events及已有自动witness
覆盖的birth不重建；缺少的实际birth flags与FD来源在同一次raw读取中投影。

本次实际生成12649 legacy source请求、8个raw档、4个缺birth flags，均由输入derive；
它们不是默认值、产品断言常数或业务规则。

仅支持真实成功open类、dup/dup2/dup3、F_DUPFD/F_DUPFD_CLOEXEC输出。open值来自真实
return；dup输出保留原target，不创建另一个IR OFD。dup2原地no-op不能伪造新binding。
同source存在多个未解析输出而无法机械对应时明确frontier，不解析opaque HandleID。
已有pipe双端等provider端点保留原映射。

父/子native TID来自原per-native-TID provider selector与coordinates，不当TGID使用。
creator的process=None保留。所有字段、目标与原Run/preimage严格限定，不补parent最终
FD snapshot，不推断CLOEXEC/offset/共享写入顺序、效果闭包或GPU ready。

## 一次raw读取与有界存储

每个需要的compressed原档**物理读取一次**到独立有界缓存，先核compressed SHA/bytes，
再对该缓存做一次流式解压；逐原行核raw SHA/bytes/lines，只解析请求行。不会把整个
decoded main raw保存在内存。分别报告physical compressed bytes、raw bytes、raw lines、
selected parsed lines和生成ports；不把“只解析请求行”说成“只读取请求行”。

line期望来自已核非main file receipts与原全scope分母推导的main补集，不能用未命中
替代不存在。没有重新构造百万Action/Work或重导原observations。

默认预算：128MB raw、2M原行、16KiB单行、32MB单compressed文件、20k handles、512
artifacts、4MB单metadata/manifest、16MB独立decoded chunk、128MB全部projection decoded、
64MB全部projection stored。预算失败或SHA不符不发布manifest，不自动抬预算。

复用既有`_Chunk`、有界JSON encoder与wholechunk reader，输出固定三个表：

- `fd_ports`：新provider记录的真实FD值、extraction合同、原SourceFact/Run/target及
  原HandleBinding reference。`new_ir_resource_created=False`只表示工具没有新建IR资源，
  不否认原open实际创建了一个已由R1记录的OFD。
- `birth_facts`：自动所需的真实birth source/result/flags。
- `frontiers`：未解析、合同不符或歧义，保留原引用；creator无自身birth另列actor frontier。

新schema为`scar.os-fd-source-projection` version1。每个ProviderRecordSelector指向
**新manifest的真实tables/fd_ports/chunks、真实JSONL line/ordinal与/record/fd**，不冒充
旧R1 row。原引用字段明确称`canonical_record_sha256`，哈希有界canonical record加末尾
换行；不是原raw-envelope SHA。raw SourceFact与旧R1 source URI通过精确归档映射并存，
不改写旧receipt。

fresh目录、O_EXCL chunks、fsync+hard-link原子manifest发布。PUBLISHED只表示这个
限定provider投影已发布；支持partial frontiers，不代表完整资源模型。

## 真实endpoint精化

新reader复核完整input artifact receipts、chunk双SHA/size/line/ordinal、稀疏handle index、
原source/Run/target/preimage。raw提取合同在producer单次读取中检查；reader默认**不再读
82MB raw**，不将byte验证冒称raw重提取或完整Linux语义验证。

`iter_handle_records()`合并原handles与fd_ports两个有序流，各读一遍；不为12649条记录
重复decompress。仅将原同IDHandleBinding的endpoint精化为现有ProviderHandle：

- selector指向真实新fd_ports值，namespace继续使用原native FD协议；
- lifetime表示限定source上的观测赋值，不声称完整kernel generation；
- container继续Unresolved，等待独立context/availability证明；
- 原target、end、rights、ownership、support、source、start与已有35个选择不变。

局部`record()`通过明确稀疏index查询；submissions完全委托已有view，不新建/修改Work。
combined resolver仅按原base或本projection的**完整ProviderArtifact**分派，不按basename、
PID、相近时间或hash单独合并，不从任意URI打开文件。

此步只scope于R1已建handles；未建继承/stdio、未知OFD target、物理文件/device/pipe
buffer、canonical state/effects等仍OPEN。没有fake ProgramSnapshot或新mutable图。

## 唯一真实验收

实验：`artifacts/experiments/first_stage_os_fd_source_projection_20261023/gate-attempt01/`。
实际**exit0**，wall **73.74s**，RSS **296,208KiB**。没有修代码或重跑。它是在并行
服务器负载下的离线验收成本，**不是LeWM benchmark或加速比**。

实际source扫描8档，82,093,008raw bytes、1,035,968原行、8,624,059compressed bytes
各物理读取一次；仅12,653选中行解析，生成12,649 fd_ports与4 birth_facts，provider
frontier0。缺失birth实际为3个vfork与1个带CLONE_FILES/CLONE_THREAD的clone3，未由
同process关系猜flag。

投影共3chunks、27,655,358decoded / 1,343,742stored bytes。manifest **197,638bytes**，
SHA256 `0ebb957e8b4fd86eafefbce6f854ff045627cface9523f06766aabab8b2e8723`。

- 12,649输出实际分为12,648 OPEN_RETURN、1 DUP_RETURN_EXISTING_TARGET。
- 公开reader完整验证所有新selector的chunk/line/ordinal与真实FD字段，按2个fd_ports
  chunk有序批量进行；每chunk另实际调用combined resolver代表。没有做12,649次从头
  readline。报告明确全量批量检查与2次point-call的不同范围。
- 全部12,684原/新handles在公开core codec与逐非endpoint字段比较中通过。同ID、原
  target/end/rights/source等不变，原35 ProviderHandle逐record原样保留。
- 新12,649个ProviderHandle的container继续Unresolved；原35个已知container保留。
  这是FD来源闭合，不是把12,110 context候选冒称已验证。
- 原/新target集合均12,683；dup增加binding但不新增IR OFD。原selected25 Work/38access
  不变；creator290个point.process=None原样保留。
- 12关键源码SHA前后匹配；本次实际98个SCAR imports冻结当前SHA，无漂移。

全量selector/字段矩阵使用有界逐行gzip，分别保存12,649与12,684条证明；没有另一张
mutable图或巨型JSON。原R1/R2/selected view与输入文件SHA未改变。

未建立的继承/stdio/其它引用、context归属、状态/offset、physical device关联和完整
ExecutionModel语义仍OPEN。PUBLISHED与本门PASS只适用于既有handle FD来源范围。
