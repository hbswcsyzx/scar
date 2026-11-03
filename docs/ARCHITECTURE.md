# 建图架构

第一阶段只完成程序建模与建图；化简、改写和性能优化在后续阶段。
实体和关系定义见 [MODEL](MODEL.md)，实测范围与剩余缺口见 [STATUS](STATUS.md)。
LeWM 是外部 testcase；通用规则由语言协议、原端口和证据派发，不按业务名称选择。

## 形式阶段与顺序

先验收前层的输入域、全部类型/字段及转换不变量，再开发后层。已有后层代码保留，当前冻结新增功能；
功能样例通过不能证明前层完备。当前 Python 前端按本机 CPython 3.14.7 的版本化接口核对。

| 阶段 | 封闭输入 → 机械输出 | 验收对象 |
|---|---|---|
| F0 材料 | 原始bytes、来源/版本 → 原字节blob、编码结果或结构化错误 | SHA/长度/精确还原；不调用lexer/parser |
| F1 词法 | F0材料 → 官方全部token字段/exact_type、源码区间与gap、EOF或错误前缀 | 与官方流逐项相等；源码覆盖并集+gap无漏无重分区 |
| F2 语法 | 同源词法输入、固定parser参数 → 完整constructor/有序字段/子节点槽/带类型标量/坐标 | 无损还原官方AST，含None、空列表及字段存在性 |
| F3 绑定 | F2 occurrence及官方symtable → scope树、全部名字来源字段的角色/绑定关系 | 全scope/symbol/namespace链及名字字段分母；不按名称+行号猜 |
| F4 规范IR | F2/F3及版本化语言规则 → Operation/Value/StateLocation/Region/Resource、CFG/SSA/完成端口 | 每个语法类别×上下文有构造规则，控制/状态/效果约束成立 |
| F5 接线 | 原定义和端口、静态契约及可选运行事实 → 跨区域/函数/库/资源关系 | 原端口、条件与作用域逐项对应，动态仅补实际选择 |
| F6 推理与发布 | 已连接关系 → 条件固定点事实、分片及完整覆盖清单 | 来源可重验；字段未知、预算前沿与缺实现分开 |

每层都须对其全部输入给出有效记录、准确StageError或BudgetFrontier；失败不能改名为UNKNOWN或悄悄跳过。
记录实例覆盖与实现规则覆盖分别核查；新发现材料仍从已验收前层进入，不能绕过前层。
F1/F2使用官方前端，不重造Python lexer/parser；AST是语法输入，最终程序图仍可共享、成环和展开。
F0当前是独立命令，旧static入口不能视为已经自动执行它；现有AST目录计数不证明F1/F2通过。
F0的V1解释规则忽略codec警告（原bytes保留），不继承调用方warnings-as-error；
串行解释或spawn进程隔离，避免共享warning过滤器相互干扰。
F1固定官方token表和实现指纹，通过显式CRLF/CR→LF视图调用generate_tokens，不增加末尾换行。
原生行列、原decoded字符区间及view UTF-8字节区间分开；虚拟EOF不裁剪，gap不全是trivia。
string/line以共享精确文本引用存储；相同文本引用不代表同一源位置，原token extent另存。
TOKENIZED、TOKENIZER_ERROR、BUDGET_STOPPED、UPSTREAM_DECODING_ERROR分开；真ENDMARKER并确认耗尽才算EOF。
词法warnings单独记录；spawn进程隔离过滤器。budget前缀不覆盖当前模型，fresh读取逐字段重放。
F2用官方compile的ONLY_AST|TYPE_COMMENTS，dont_inherit=True、optimize=0及当前feature版本；
记录parser实现、完整结构化schema、整数位数/递归限制和literal预算，不执行bytecode。
按parent/field/list occurrence存平面局部ID表，保声明字段/属性的显式presence；None、空列表、缺失分别记录。
精确literal保IEEE位与代理码点，预算超限不是语法错误；还原使用官方类__new__并逐字段核对。
语法表不是最终依赖图，也不授予scope合法性；新occurrence身份不冒充旧ast.walk SourceID。

## F3的形式边界

源码名字/求值角色、compiler block与runtime frame分别表示；三者没有固定一一对应。
公开symtable会移除内联comprehension表、重挂子表、共享annotation表，不能直接作为源码scope树。
原生id是已释放C AST的历史地址；namespace按名字派生的stdlib视图也不是绑定证明。

严格顺序为：F3-A保全官方原序symbols/整数flags/varnames/children及profile/error/budget；
F3-B按全部constructor×field×context声明名字角色；F3-C建立源码scope/phase和名字→namespace接口，
再以显式投影witness对应编译器视图；F3-D全量fresh验收。前步未通过不新增后步实现。
名字角色按语法类别派发；属性名、keyword标签、import路径、常量文本不能当局部变量读取。
词法存储绑定与实际值/运行类选择分开；缺静态规则不是动态UNKNOWN，未知值也不抹掉已知端口。

继续复用官方前端；现成scope库仅在已验证能力内复用。LibCST1.9.0的walrus实测反例与
Ruff对class-cell的显式近似表明不能把工具输出无条件升格为优化事实；不按name/line或ast.walk猜接线。
依据：[CPython](https://github.com/python/cpython/blob/v3.14.7/Python/symtable.c)、
[LibCST](https://github.com/Instagram/LibCST/blob/v1.9.0/libcst/metadata/scope_provider.py)、
[Ruff](https://github.com/astral-sh/ruff/blob/main/crates/ruff_python_semantic/src/scope.rs)。

F3-A已实现类型化编译器视图与独立材料store；显式flags、原序参数/符号/children和别名均可fresh重验。
编译器补入free symbols的顺序受Python hash上下文影响；profile保有效指纹，worker与parent必须相同。
完整转录保原序，不能用排序掩盖差异；分析进程固定PYTHONHASHSEED，不能靠启动后改env假装生效。
原生compiler错误、adapter协议错误、资源与预算分别处理；外部store摘要需由fresh事实重新计算校核。
collect-only保留原模型，只写新分片并绑定必需四种源码收据；无关manifest元数据变化不使其失效。

F3-B以113个constructor的196个field和288个attribute建立484条共享规则。
全槽按ABSENT/None/空列表/有值分区计数；名字、属性标签、keyword标签、import规格分别分类。
增量赋值、仅注解、普通赋值、walrus等使用原父字段和ctx选择角色，不声称运行时读写。
实例只存F2槽引用、角色和必要上下文；字面量、文本、坐标仍只在F2保存，catalog每store一份。
`SyntaxRoleView`一次建立父槽索引，查询任意原槽，包括不落稀疏port的字段；循环查询不重复扫AST。
schema未覆盖则拒绝；预算停止不发布部分角色表。F3-B通过也不代表scope/名字存储绑定完成。

## 共享子图与可组合接口

源码 AST/CST 是识别输入；执行依赖由可共享、可成环的规范图表示。
模块、函数、类体使用各自的原主体身份；未建主体保留缺口。
分支、循环和异常保留控制结构、合流及适用出口。
每个定义主体保存一份，调用与循环迭代引用它，不复制函数或按迭代展开节点。
循环视图引用原成员、header 参数、初始边和回边；它不另造一份 CFG。

接口必须保留输入、环境、正常/异常等完成的 payload 与前后状态。
数据返回、引用返回和状态返回分别连接；引用相同不证明可变内容不变。
每条关系携带原 namespace/typed ID、上下文、条件与证据；缺边不证明无依赖。
字段可以是已知、符号值、候选或 UNKNOWN；一个字段未知不能抹掉整个节点。
区域 cut 只描述输入、消费者、状态、效果与资源，不授权替换区域。

## 静态模板与动态实例

静态侧建立子图和可组合端口；动态侧观察实际选择，再对应到原端口。
两者按事实是否可静态确定分工，不按文件边界分工：跨文件的已知关系直接静态连接，
同一文件里的不确定分派也保留条件或补充观测。文件负责材料、版本、存储与构建调度；
函数、类、循环等 Region 才是共享结构和可展开接口的单位。
运行绑定必须限定 run scope、process/thread、InvocationKey、attempt 及事件锚点。
静态 context 是接口选择；None、闭合栈和 Open 后缀有不同含义，均不是 Invocation。
同一调用点的不同 attempt、同一函数的不同激活不能因共用模板而合并。

[call_operands.py](../scar/trace/call_operands.py) 复用 CALL 事件采集；
[python_call_targets.py](../scar/trace/python_call_targets.py) 记录实际 callable，
[code_snapshot.py](../scar/trace/code_snapshot.py) 提供完整代码身份及指令位置。
采集仅保存必要原事实；静态对应、接口建图和推理在离线侧完成。
代码对应核完整 CodeID、编译路径、解释器 profile 和原位置；名称或行号只用于筛选。
有历史源码指纹时必须核对；没有时可静态建立当前源码子图，但运行对应只授权匹配的 Code 作用域。
子函数匹配不证明父模块执行、factory 创建来源、globals/defaults/closure 内容或兄弟定义的运行版本。
实际类对象的调用证据不证明它来自某条类声明；创建来源须另有证据。
一次观察只限定该运行事实，未覆盖路径与未知状态继续保留。

## 分片存储与统一读取

artifacts/current/static/ 是唯一当前程序模型；源码/主体/关系按分片保存。
每片附 stored/decoded SHA 与原 ID 引用，跨片引用不复制原图。
共同 reader 共享有界缓存、校核原收据；原输入稳定期间复用解码结果。
增补缺失主体保持已有主体和关系原样；旧关系仍只覆盖其原输入范围。
无图诊断不是已完成主体；仅fresh读取确认原收据内无图/端口、源身份不变，才允许补建并保留诊断输入。
既有规范/partial图不走此替换口；实际支持尚缺时报告static rule，不消耗无效的补建请求。
artifacts/current/queries/ 保存派生查询证据，不是第二份权威程序。

## 已有后层能力与当前开发边界

已具备源码层、局部规范图、共同依赖查询、部分条件属性推理和循环边界查询。
真实 CEM 的81个CALL实例及9条函数接口已接入共同图的显式观测端口查询，静态邻接不变。
实例端口引用原点及run/Invocation/attempt/事件作用域；只有实际选中的return形成返回接口。
参数未定不丢入口/状态/返回；ABI布局保留条件备选、默认值义务和pack依赖，不猜receiver或容器身份。
对应 owner 是 [program_observed_dependencies.py](../scar/analysis/program_observed_dependencies.py)。
选中 CEM 循环的边界查询已在原预算内完成；这不证明状态、效果、资源或整个程序闭合。

可证明的线性编译栈来源已接原cleanup返回；跨跳转合流继续保留候选，不按None猜来源。
这些是已有局部结果，不证明形式前端完备。F0/F1/F2已对声明材料验收；下一层只做F3作用域与名字绑定，验收前不新增F4及后层实现。
不得把裸 context=None 的观测边注册为全局事实，也不得丢弃未执行的异常路径。
Python→native/runtime/kernel、Tensor 属性、alias/effects 与资源连接仍需按实际缺口补齐。
第一阶段只有在实体、结构、连接、属性和覆盖均经核查后才完成。
