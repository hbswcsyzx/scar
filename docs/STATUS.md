# 当前状态

**第一阶段未完成。当前按形式阶段重新验收：F0 → F1 → F2 → F3 → F4 → F5 → F6。**
阶段定义见 [ARCHITECTURE](ARCHITECTURE.md)。F0/F1已按声明输入域验收；下一层为F2，组合cleanup开发暂缓。
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

## F1验收与下一层

**F1词法已验收**：866份声明源码共1,961,177个token，全部真实EOF；4个spawn进程采集44.41秒，
独立fresh重放109.73秒。866个词法分片共82,316,986压缩bytes；没有运行parser/symtable或目标。
保存全部TokenInfo字段、exact_type、可逆换行视图、三种坐标、source gap、native错误参数、warnings及预算状态。
闭合schema含69个terminal与48个exact operator；实际源码观察13种terminal，不能混作69种均实际执行。
7个聚焦检查通过（2.57秒），有限族独立核源码引用/覆盖区间，并覆盖全部48操作符和140个前缀引号组合。
捕获后去掉新增词法收据可精确还原F0 manifest SHA；旧22,532分片及端点保持，fresh核验不改模型。
证据：`artifacts/current/queries/formal-frontend-f1/{run.json,acquisition/result.json,verification/result.json}`。
验收限本机profile与声明目录，不证明依赖发现完整，也不是穷举任意输入字符串或错误消息。

1. **F2语法**：现static_lexical实际是AST/作用域导航。访问数量相等不证明所有字段已保留；
   scalar、None槽、空列表、字段存在性仍有缺口。parser的type_comments参数也不统一，同源Name ID可错位。
   下一项固定parser参数、按constructor×field无损保存/还原，再对全部声明源码验收；不先改绑定或规范IR。
2. **F3绑定**：官方symtable存在，但AST→scope仍有候选对应，(name,line)不能作为唯一身份。
   后续需按固定constructor+field上下文覆盖每个名字来源字段，而非凭功能样例通过。

## 当前模型与已有后层证据

`artifacts/current/static/manifest.json` SHA-256：
`55e18833d6f7c41d862fe1b15f749f2bfba5c559a74dcc0ae7945cd303db47ff`。
23398个压缩分片、2,545,860,267 bytes；包含材料、索引和诊断，不能全算实现图。
规范主体仍8098个、1,264,142操作；无图诊断与未展开声明继续单列。
旧CALL/class/import关系仍仅覆盖原basis，F0/F1追加不能升级这些覆盖范围。

先前保存的CEM probe（人工quadratic cost、2轮×4候选）已有81次CALL、9条Python返回、580条双向核查边；
不是完整模型或episode。证据在`artifacts/current/queries/lewm-native-callables/graph-cleanup-returns/validation.json`，
属于F0追加前的局部运行对应，不能作为当前形式前端的验收结果。
待前层通过后，再继续组合控制、generator创建/恢复、native/runtime/kernel及状态/资源连接；
不做化简、backend扩展或目标改写，也没有LeWM加速比结论。
