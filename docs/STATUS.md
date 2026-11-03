# 当前状态

**第一阶段未完成。当前按形式阶段重新验收：F0 → F1 → F2 → F3 → F4 → F5 → F6。**
阶段定义见 [ARCHITECTURE](ARCHITECTURE.md)。F0/F1/F2已按声明输入域验收；下一层为F3，组合cleanup开发暂缓。
现有后层代码及成果保留，但不能代替前端完整性证明。

## F0：原始材料

当前模型声明的866个源单位、12,655,117原始bytes已全部保存并逐项fresh核验。
每份材料保存唯一原bytes blob、SHA/长度、解释器profile、编码/解码结果与准确错误。
没有执行目标lexer、parser、symtable、compile或LeWM；没有据此宣布后层通过。

| 核验 | 结果 |
|---|---:|
| 保全 / fresh核验 | 866 / 866 |
| 来源 | 866份均与文件原始版本精确匹配 |
| 原扫描remaining / issues | 0 / 0 |
| 原21,666分片、旧unit字段与关系发布 | 保持 |
| 初次归档 / 最终fresh核验 | 38.72 / 4.77秒 |

边界：866/866是声明材料目录的完整性，不证明所有程序依赖已发现，更不证明词法、AST、绑定或执行图完整。
独立F0入口支持语法非法、编码/解码失败的bytes；失败仍保原文，预算/不可用输入明确报错。
CP932等非可逆codec不能仅凭相同文本恢复；候选必须匹配原raw SHA/长度并再核解码文本。
partial不覆盖当前模型；归档仅追加owned材料，保所有旧端点，fresh核验不改模型。
当前F0是独立命令，旧static入口尚不能视为自动执行它。

证据：`artifacts/current/queries/formal-frontend-f0/{run.json,acquisition/result.json,verification/result.json}`。
纯API与独立材料集成2例通过；集成强制禁止ast.parse/symtable，并核不可逆编码、缺文件、预算和并发新增文件保留。
补审发现unicode_escape解码warning受外部warnings-as-error影响；已固定忽略codec警告并恢复调用方过滤器，
并行归档改用spawn隔离。3例通过；866份补充fresh核验4.72秒，材料与manifest未变。
补验：`artifacts/current/queries/formal-frontend-f0/warning-policy-verification/result.json`。

## F1词法

**F1词法已验收**：866份声明源码共1,961,177个token，全部真实EOF；4个spawn进程采集44.41秒，
独立fresh重放109.73秒。866个词法分片共82,316,986压缩bytes；没有运行parser/symtable或目标。
保存全部TokenInfo字段、exact_type、可逆换行视图、三种坐标、source gap、native错误参数、warnings及预算状态。
闭合schema含69个terminal与48个exact operator；实际源码观察13种terminal，不能混作69种均实际执行。
7个聚焦检查通过（2.57秒），有限族独立核源码引用/覆盖区间，并覆盖全部48操作符和140个前缀引号组合。
捕获后去掉新增词法收据可精确还原F0 manifest SHA；旧22,532分片及端点保持，fresh核验不改模型。
证据：`artifacts/current/queries/formal-frontend-f1/{run.json,acquisition/result.json,verification/result.json}`。
验收限本机profile与声明目录，不证明依赖发现完整，也不是穷举任意输入字符串或错误消息。

## F2语法

866份源码全部PARSED，1,511,372个occurrence、2,551,189个field槽和3,931,984个attribute槽。
8个spawn进程采集110.91秒，独立重读/还原并与官方新解析逐字段核验157.32秒；没有执行目标或symtable。
新增866个语法分片共33,269,423压缩bytes。保显式presence、列表None空洞、精确IEEE/complex/bytes/代理码点。
113个constructor×196field及288attribute槽的339种合成形态通过；实际源码见101种constructor，二者分别计数。
F1/F2共11个聚焦检查通过（5.21秒），含四mode、独立wire核对、预算与上游禁止解析。
新表去掉新增收据可精确还原原F1 manifest；旧23,398分片、unit字段、关系与ID保持。
语法成功不等于scope合法，也不是最终执行依赖图；现有ast.walk身份不因新parser参数而静默重排。

采集证据：`artifacts/current/queries/formal-frontend-f2/acquisition/result.json`。
完整核验与汇总：`/var/tmp/scar-f2-recovery-7w7nd_0z/{verification/result.json,run.json}`。

## F3-A材料（已验收，尚未接通AST）

**Implemented/Verified**：完整类型化public compiler材料、canonical append、collect-only独立store和fresh reader。
866份源码全部CAPTURED，40,411个scope、208,528个symbol；866分片共2,981,301压缩bytes，解释前沿0。
8进程采集162.00秒、独立核验162.33秒（均包含完整F0/F1/F2重验；纯native双pass审计为6.24秒）。
6个聚焦检查通过，含4个F3-A族与2个F1/F2集成；eval.py单文件9scope/89symbol亦独立验证。

原序参数/符号、原始integer flags、nested/type及child别名均保存；不持久化历史native地址。
修复了adapter错误冒充compiler诊断，以及store摘要/预算/权限声明未验证的问题。
实际跨seed实验确认free-symbol补入顺序不同；profile现在保有效hash上下文，跨worker/replay不匹配则拒。
PUBLIC_COMPILER_VIEW/UNJOINED始终显式；这不是完整lexical scope、名字绑定或第一阶段完成证明。

本轮材料/汇总在`/var/tmp/scar-f2-recovery-7w7nd_0z/f3a/{materials,verification,run.json}`。
/home仍emergency_ro；通过同一main的变更源码缓冲运行，原模型manifest和消费分片不变。
真实模型尚未注册新材料（canonical_model_published=false）；fixture已验证追加端点保持及canonical fresh读回。

## 下一层

F3-B：完整constructor×field×context角色表 → F3-C：源码scope/phase与名字存储绑定 → F3-D：全量独立验收。
旧15个公开标志已全存，349组name+line冲突及内联/annotation共享证明不能据此直接接AST。
字段角色和source/compiled/runtime三种scope必须分开，F3通过后才进入F4；不增加优化backend。
先前审计及LibCST能力反例保存在`f3-audit/`；现成库仅按已验证能力使用。

## 当前模型与已有后层证据

`artifacts/current/static/manifest.json` SHA-256：
`f1c5834c5e0fc115954f87dc77fa4f0d2be55788e920bcdbbbfa64842bf7bb1e`。
24264个压缩分片、2,579,129,690 bytes；包含材料、索引和诊断，不能全算实现图。
规范主体仍8098个、1,264,142操作；无图诊断与未展开声明继续单列。
旧CALL/class/import关系仍仅覆盖原basis，F0/F1/F2追加不能升级这些覆盖范围。

先前保存的CEM probe（人工quadratic cost、2轮×4候选）已有81次CALL、9条Python返回、580条双向核查边；
不是完整模型或episode。证据在`artifacts/current/queries/lewm-native-callables/graph-cleanup-returns/validation.json`，
属于F0追加前的局部运行对应，不能作为当前形式前端的验收结果。
待前层通过后，再继续组合控制、generator创建/恢复、native/runtime/kernel及状态/资源连接；
不做化简、backend扩展或目标改写，也没有LeWM加速比结论。

当前/home仍只读；同一main通过/var/tmp临时Git索引、对象库和少量变更源码缓冲继续开发。
本地HEAD/index仍在f4cc1afc；恢复可写后先核原hash，再同步缓冲与文档、注册材料；不覆盖用户更改。
