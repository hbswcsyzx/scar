# 当前状态

**第一阶段尚未完成；当前只做静态建模、建图与查询。**
NORMAL_SUCCESS / CPython 3.14.7；交付后端约定 C++20、算子 ABI v1、计划 schema v1。
本阶段未运行 LeWM 或导入 torch/Hydra/OmegaConf。以下秒数均为分析器耗时，不是 LeWM 加速比。

## 当前五层实施

| 层 | 状态 |
|---|---|
| ①统一IR接口 | 接口合同与3个普通/compiled完整单元验收通过；复用core引擎，70,373端点/75,037关系以单元头＋类型ID存储；完整推理链覆盖仍在后续层 |
| ②局部结构与状态 | 绑定、内容、namespace/注解与196个native单元已接统一查询；gcrl63条自动局部链保持；其余状态与入口相关单元覆盖仍待补 |
| ③跨层依赖 | 既有参数/返回/成员/算子部分关系待统一接入；暂停前函数接口批次未发布，不计完成 |
| ④资源与执行证据 | 已有硬件及类型投影；运行I/O和动态记录向统一图接线待完成 |
| ⑤完整推理链验收 | 尚未通过；文件数、节点数和单个源码单元通过均不替代此项 |

①的当前接口门已过，正在推进②；不启用化简或代码生成。入口相关代码与候选关系全面考虑，孤立文件不强求，也不按一次未观察到执行删图。

**Observed / Verified：** `program-binding-state-current/verification.json`通过3个普通/compiled单元的接口发布与逐记录重推：5,846个操作获得效果请求，684个绑定访问、343个地址模板。69种原始指令按20类闭合识别，分类不等于效果已证明。随后`program-local-state-current/verification.json`通过默认CLI的自动局部选择：gcrl完整单元中63条可分析状态链、126个读取选择、7个共享函数体、14,644条关系；不按业务名选槽、不复制函数体/循环迭代。5,499个版本模板中5,387个是开放效果来源，不是已知Tensor新值。完整构建/写盘32.45秒、峰值RSS约358 MiB；独立逐表解码和重推93.84秒，验证进程峰值约914 MiB。当前表4,416,018压缩bytes、112,184,328解码bytes；重复状态坐标/版本集合及严格解码是已显露的存储/读回开销，尚未完成归因。未采集Tensor数值，未运行目标。已存两槽查询也按当前facade重推通过；CLI扩展不要求废弃不变的数据合同。

**最新增量已验：** 同一current材料又补齐7处类隐式名字/frame builtins地址，现为222访问、122地址模板、14,661条关系，该单元已识别的地址规则缺口由7降为0；不代表效果已闭合。新增lookup保hit/miss顺序，prepared mapping与frame环境的原实参以条件边接到地址。构建与针对性检查30.04秒；tracks/versions/selections三表与上次已完整重推结果逐字节一致，沿用其证明，未重复93秒全解码。当前表4,419,322压缩bytes；旧表已由当前发布替换，证明链保在verification中。

**对象内容接口已验：** `program-content-state-current/verification.json`覆盖普通与compiled共3单元：351个属性/索引/聚合协议请求、702个前后world状态投影、2,498条内容关系，全部接原操作、receiver Use与key/bounds端口；同一`ProgramView`可跨绑定与内容查询。新增四表共415,833压缩bytes；3 workers合34.30秒，新增表分别0.55–1.33秒重推，原8张绑定表逐字节不变并继承已验结果，未重做全量解码。gcrl当前发布仍在`program-local-state-current`。统一状态schema为`scar.source-state-view/1`。实测实例为GET/SET/UPDATE；DELETE和slice等原ABI有规则，未宣称本批实例覆盖。append/extend/dict merge/comprehension保原协议，DICT_MERGE的callee不是owner，comprehension按原ChoiceBinding分派。投影是`project(world,address)`符号值，不是Tensor快照或已知LogicalVersion；GET也保后态，不假定getter纯。

**Native局部状态已验：** `program-native-state-current/verification.json`覆盖全部196个已存canonical接口：507地址（496 Tensor＋11 Generator）、1,099 world投影、90组scoped alias声明和3,804条关系；170个声明可能写、12个列表叶族均不等于运行事实。原图复制0 bytes，新增表747,278压缩bytes；构建6.53秒、严格读回5.64秒，验证进程峰值约467 MiB。独立认证原native batches与源码收据，不重跑parser或源caller链。输入保before/normal/raised world，输出仅保原normal结果；alias按declaration/boundary/原annotation字段限定并按需展开MAY关系，不存dense pairs，不把空after或无annotation当纯性。一个`ProgramView`已同时查询源状态与native状态，原core记录优先保留；source调用绑定尚未证明。

**Namespace/注解接口已验：** `program-namespace-state-current/verification.json`对SPT和rich两个真实依赖单元（3,844操作）发布并完整重推；覆盖ReadAnnotationNamespace 3、ReadAnnotationRegistration 3、ApplyNamespaceAction 6、AddAnnotationIndex 1。2 workers合47.64秒；单元构建9.23/22.24秒、读回8.78/22.26秒，表合562,647压缩bytes。LOCALS_CHAIN、GLOBALS_CHAIN和class-cell规则保持不同；registration bool不当registry引用，不造中间GP。STORE_NAME/GLOBAL、条件ensure和registry更新均连原内容world；缺地址标记仅在接口实际建立后清除，效果仍不闭合。类型参数关联有原ABI规则，本批没有宣称其实例覆盖。

**②的剩余工作：** 其它隐式状态、完整descriptor/内容效果接口及入口相关单元覆盖。当前两新单元剩余缺地址标记仅为异常状态操作，不能据此宣称其它单元或全程序已无缺口。下一步机械盘点相关单元的类型/接口覆盖，补正常profile中的缺规则，再据原参数/返回接口进入③；之后为④资源/运行事实和⑤推理链验收。缺规则与待选实例分开；绑定未变及不同投影ID不证明内容同异。全图与第一阶段均未完成。

## 分层进度

| 层 | 当前结果 | 剩余边界 |
|---|---|---|
| F0–F3 识别 | 866 材料：849 Python 源、17 stub；bytes、词法/语法、scope、binding、编译视图 | 新依赖按需经同一前端准入 |
| F4 局部图 | 882,537 共享模板、3,385,528 操作、4,645 循环、24,159,357 边 | 共享展开不等于全域 canonical 图已闭合 |
| F5 局部接口 | 原 852 源摘要；48 workers 构建68.80秒；新增依赖独立追加 | 不重建旧图或改变旧端口编号 |
| F5 跨层接线 | 参数、捕获、返回、world、构造/属性/容器；实际 launcher→compile/exec→Hydra→任务正常链 | 尚未固定点；may 调用不是实际 dispatch |
| 配置请求 | 原调用/alias/decorator、入口 argv、实际 compile filename→文件候选 | 初始 argv、搜索路径、环境选择仍带条件 |
| 配置组合 | 自动发现3文件/102数据节点；defaults、package、共享材料和有序根版本 | CLI/lazy、ConfigStore/schema、任务 cfg 字段未闭合 |
| 覆盖输入 | 初始 argv→已知option/positional→6表达式/6有序写入，保来源及类型 | 仅初始版本；组选择、字段应用与lazy引用待接 |
| 输入字段图 | 22状态表达式、12根版本、52字段投影；3条lazy引用，5处可能的中途读取需求 | 条件性输入候选；未绑定任务当前cfg，部分中途状态仍未降低 |
| 声明状态接点 | 自动定位原cfg实参和post-call world，独立保None数据返回；884单元context已求解4M事件 | 原FIFO预算前缀尚未连接API；输入版本及任务内容仍未证明 |
| 按需字段/方法 | 独立于全局FIFO，原引用与匹配call/return连接字段赋值→读取→声明方法接口 | 条件关系不授入口准入、当前字段版本或dispatch；外部writer仍开放 |
| 声明正文/状态 | 共享12个函数上下文、11条方法边；配置修改API接成1条条件状态接口 | 111个正文调用前沿；输入及后续版本、入口准入未证 |
| 调用后状态路径 | 原F4中API后world→调用者正常return的may路径已接通，含分支及共享循环 | 尚未匹配所有调用/分支选择；字段地址、内容版本与opaque effects未闭合 |
| 符号状态地址 | 87访问已接原world与receiver来源：73字段/index访问、14调用输入 | 34来源路径未解；descriptor/index/call效果未消除，不等于当前版本证明 |
| 跨函数返回 | world与data返回分开；10共享节点/9条件返回边，含正常run分支 | 6节点预算前沿、1引用返回边界；尚未接下游实参消费及任务内部版本 |
| 实参消费者/正文 | 35相关输入使用→9形参绑定→6共享正文，保202状态访问 | 原生target、构造及模块来源等139前沿记录；尚未贯通复制后来源与任务cfg |
| 正文操作/值流 | 6共享正文的833操作、18,444边、50局部位置；9入口→75依赖调用输入 | 可能依赖已达任务调用实参；内容/状态版本仍未证明 |
| 派生实参接口 | 75输入→14原形参绑定/8源函数；含task actual2369→compiled formal3972 | 84目标/协议前沿；未授caller匹配或dispatch |
| 正文展开 | 11共享正文（复用6、新增5），12参数入口；compiled任务正文526操作/60调用 | 2非数据参数路由保接口边界；下游native/源调用仍需接线 |
| 调用上下文/构造 | 16入边上下文、220callee查询；318构造阶段/64源正文接口；声明与历史证据分别保留 | 当前0闭合函数来源，868历史候选关系仍OPEN；namespace/成员/外层frame待接 |
| 构造class输入 | 64兼容类型输入→50共享声明上下文/34函数，保原entry与world | 已纳入下列成员展开；不授精确类型或MRO |
| 构造成员/正文 | 51声明上下文、2直接成员边；新增35正文/870操作/60调用 | 120调用前沿；继承及namespace/field来源仍需接，不授精确runtime class |
| base/namespace来源 | 39类/30有序base槽；29槽有条件源码class候选，原端口/来源保留 | 当前globals/class namespace/builtin/slot版本仍OPEN；尚未计算或证明MRO |
| namespace调用接口 | 236原查询锚点共享168来源子图，26条件函数接口/13源函数，102具名请求 | 父调用栈保留；当前namespace/函数环境版本与实际dispatch仍OPEN |
| 继承成员/正文 | 原64构造入口→52共享上下文；2直接＋4继承接口，47共享正文 | 121正文调用前沿；基类路径不代替当前MRO、遮蔽或精确类型证明 |
| 共享正文/下游调用 | 55正文、111保outer caller的入口→421查询；72条件namespace函数接口 | 当前非词法/producer等453关系前沿；尚未到全域固定点 |
| 全源码调用声明 | 581源单元/48,290原callsite全部纳入；33,558具名请求，按unit独立分片 | 不授scope激活或caller选择；7个selector深度前沿、参数/返回来源等待上下文 |
| 具名原生绑定 | 2,559 callsite→7,543条件绑定接口，保196声明/196 ATen selectors | 当前namespace、parser、实际dispatch未证明；非生成绑定仍保显式缺口 |
| 原生端口归一化 | 196 canonical ATen接口；29,964输入依赖、7,543返回包装依赖，显式world接线 | 2,553输入转换/receiver仍OPEN；不是值alias或parser/dispatch证明 |
| 词法读写顺序 | 原C2/F4读写锚点→匹配控制栈/GEN-KILL；3单元7查询排除23条不可达写边，原7处selector截断归零 | 当前仅选中查询的正常路径视图；捕获/未知效果和异常/resume分支保OPEN，不证明Tensor内容版本 |
| 源证据物化 | 9图/657,136引用→771原分片，765项集合路径显式重定位；stored/decoded/locator均核验 | 仅覆盖列出图的表与报告，不等于全部祖先或全程序语义验收 |
| native声明/资源 | 539个原生资源类型投影→18,283源码路由；1,617内存池/设备候选，复用12硬件节点 | 类型/来源与实际placement分开；运行I/O及非生成接口仍需补，不使用旧operand_sources=0旁图宣称接通 |

五类实体为 Operation / Value / StateLocation / Region / Resource；输入输出是端口角色。
对象、storage、逻辑内容版本和物理副本互不等价；循环不按迭代复制。

## 当前验收证据

- **`program-unified-view-current/verification.json`：第①层统一接口验收通过。** 普通gcrl、普通eval与同源compiled变体共1,781模板、5,846原操作、1,962区域；70,373端点、75,037关系，42,567条原normal边及24条回边逐项重推核对。统一`ProgramNode`/依赖查询复用旧core引擎，保完整Port/CallSite/path/completion；反序展开身份及所有字段一致，非法端口/伪收据拒绝，未接caller的形参不误报闭合。旧core值/Use与区域展开通过同一API。schema2头共享namespace/material，压缩24,906,433→11,292,322 bytes，decoded604,166,461→118,743,762 bytes；指令正文复制0、循环不展开。完整构建94.66秒，读回与独立核验183.52秒；峰值约923 MiB，未运行目标。固定类型目录缓存后，选中完整单元29.19秒重推且所有存储记录一致；这是分析器耗时，不是LeWM加速。此门证明统一表示/查询合同与列明材料，尚不证明状态/跨层/资源或整个第一阶段完成。

以下路径相对 artifacts/current/queries/；完整历史留在 Git，当前页只列有效门。

- `launcher-f4-variants-current/verification.json`：实际 compile context 的1,063语法 occurrence 全归类；632模板、2,079操作、15,162边，保原 world 与2个循环。
- `launcher-exec-roots-current/verification.json`、`launcher-namespace-graph-current/verification.json`：exec 分阶段、None/discard、globals/builtins/capture、234名字操作和条件内容连接；exec 字典不是 module。
- `frame-capture-selection/verification.json`：按选中 callable 只读3函数计划＋11 root 接口，保原 factory/callee/world。读取29.05秒，旧全量读取73.89秒；这是材料读取时间对照。
- `hydra-run-admission/closure-sources-verification.json`：15新源完整前端550.69秒，15摘要 workers7.24秒；新图累计869单元/6,089,590端口，旧 offset 不变。
- `hydra-run-admission/reference-proof.json`、`normal-task-chain-verification.json`：已安装有向 copy 闭包保原边；classmethod→构造/init→Hydra.run→run_job→compiled rawrun 接通，cfg formal3972。不是 passthrough/rerun，也不注入猜测 cfg。
- 当前 `hydra-run-admission/copy-transfer-targets`：63,327 CallLinks；4M普通事件＋12,258,044 copy传递，239.47秒（闭包22.23秒）；普通 frontier2,784,656，namespace frontier0，**不是固定点或全覆盖**。顺序敏感 transfer 尚需审计。
- `config-input-materials/verification.json`：真实三 YAML 的102 node/102 reference与 bytes；OmegaConf scalar resolver固定版本，自定义构造不执行；missing/插值仅保表示。
- `config-request-current/verification.json`：自动推导1条 API请求、3条参数 literal/alias路径及唯一 task/decorator关联；主文件候选与材料一致。仍是条件请求。
- **`config-composition-current/verification.json`：新门通过。** 自动发现 launcher/local、solver/cem、主文件，6依赖、5根版本；正确保 `_self_` 和 package 顺序。构建2.06秒、严格读回1.52秒；图压缩表3,234 bytes，含材料与收据共41,881 bytes。通用单用例核嵌套 group、header/显式 package优先级与材料共享。15个库函数固定源码/AST，未执行目标。
- **`config-overrides-current/verification.json`：新门通过。** 按源码声明复用stdlib argparse与ANTLR语法工具，6原argv端口→6表达式→6条件写入；基版本明确引用组合根4。构建0.81秒、严格读回1.20秒；图压缩表1,796 bytes。通用单用例核CLI/YAML类型差异、转义、empty/null/missing、容器、函数和sweep不求值。未初始化Hydra或运行目标；CLI已知option不当作覆盖。
- **`config-values-current/verification.json`：输入字段子门通过。** 共享操作DAG保原数据/argv来源；3条引用在所列条件下得到world.num_envs=1、dataset.stats=pusht_expert_train、solver.seed=42。两处missing合并未知prefix仍OPEN；容器成员是否完整显式记录。3个merge内部状态点保未知，2个地址读取指向旧根19，均不伪装成最终根21。16个源码函数固定AST，语法工具不初始化库。构建2.96秒、严格验收2.72秒；本子图压缩表5,651 bytes，工件30,356 bytes。两个通用用例2.32秒，涵盖覆盖后引用、missing/absent/null、序列替换、动态路径、引用环及未知别名效果。
- **`config-state-admission/sources-verification.json`：新15源ready门通过。** 基于原需求计划，逐path核与旧catalog无交集；16-worker完整前端520.77秒，15-worker局部摘要6.57秒。严格读回77,174端口、880调用、459作用域，旧catalog SHA未变；包含缺失配置加载器与callback源码，未运行目标。
- **`config-state-boundary-current/verification.json`：声明状态边界门通过。** 输入根21→原cfg实参5943的调用后world5952；调用94/attribute171、5条callee alias与6条None-return alias均核scope/原端口。data result5947与定义返回10190、None来源10191分别保留。构建1.87秒、验收4.71秒；扩展目录仅作拼接核验，884单元/6,166,764端口，全部旧offset不变。未重跑全域solver，未证明该scope激活或输入版本匹配，更未证明当前task字段。
- `config-state-context-current`：加入15源后的原FIFO求解，4M事件、273.24秒；307源、2,459作用域，frontier2,599,288。当前工作版本`config-state-connection-active/verification.json`严格读回22.20秒；接口查询保原call/argument/data-return/world及alias行号。此预算前缀的目标状态连接为0，不能把声明当作入口准入。
- `config-state-admission/lexical-experiment-verification.json`：实验性词法copy闭包核验18,864条原names、108源及scope归属。相同4M事件256.62秒，run接口推进但状态API仍未接通，frontier增至10,093,417；**不选为默认**。这不是LeWM运行或加速数据；继续定位原namespace/descriptor/callee队列的传播前沿。
- `config-state-admission/worklist-verification.json`：8:1公平队列原输入、旧offset、事件守恒及状态接口已独立核验。4M事件805.63秒，2,627作用域、160,211条件CallLinks，frontier28,830,867；目标状态接点仍0，**不采用为默认**。CLASS compose_config已有function，attribute与callee已有bound token；callee有订阅且无pending，不能再简单归因于这段词法/CLASS写传播。CLI完成打印参数错误导致退出1，已落盘图仍通过独立核验；此实验不是完成门。
- `config-state-admission/next-call-audit.json`：定点查询确认下一站Hydra调用34（callee1859/result1881）`config_loader.load_configuration`无CallLink，receiver1889也无已发布storage接线。`Hydra.run→compose_config`另已核calls#122784为DIRECT，self、4显式参数、2默认、data/world返回都接通，签名没有拒绝。词法与公平队列实验代码分别存档于`fd943439`/`06a34fdf`，已从工作版本删除；历史结果不当作当前固定点。
- **`config-field-interface-current/verification.json`：按需条件字段/方法门通过。** 自动识别原调用34→method GET44→field GET45；原SET269→GET45形成1条may-content边，再由赋值来源及CLASS binding推导1个DIRECT声明方法接口。4引用slice、356查询状态、357边、29来源候选；独立核407原证据、24调用行、46构造行及35父guard。构建71.46秒、核验22.91秒，峰值RSS约0.76 GiB；单query压缩分片19,498 bytes，原图不复制。通用小用例核调用配对、custom-new返回旧对象和不同对象字段不串线。尚有1引用前沿，外部writer域、当前版本及dispatch仍开放；此门不授入口准入或第一阶段完成。

组合门6项 obligation保留隐式库根、3个同名 schema查询、组选择与CLI/lazy层；
覆盖门保当前argv/追加项、组及字段更新条件、lazy与任务绑定。OPEN_PROVIDER不产生虚构数据；未求出最终 cfg。

- `config-declared-context-current/verification.json`：12个共享声明上下文、11边（8普通方法、3静态方法），111调用前沿；构建26.31秒、核验26.43秒，峰值RSS约0.73 GiB。原LEXICAL/MODULE/CLASS/builtin选择与包装调用保条件，不按成员名猜目标；staticmethod不加self，classmethod绑定类，延迟body创建不进入正文。通用小用例保递归回边、遮蔽条件和三种descriptor。
- `config-declared-state-current/verification.json`：原状态projection与声明edge1匹配，1边界→1连接；内容实参、None数据返回、world输入与返回分别核验。构建约29秒、核验28.33秒；保留输入版本、后续状态版本、声明非入口准入3项义务。历史FIFO中的0连接仍是原前沿；新声明边不冒充历史CallLink或运行Invocation。
- **`config-post-call-world-current/verification.json`：共享调用后状态路径门通过。** 从原238个模板批量读取并投影，API后world可达caller正常return；保2219 CONTROL、1412 STATE边、172操作状态变化、6回边。原scope后续87访问：7属性SET、64属性GET、14调用、1item SET/1GET；这是may依赖，不是总序。构建约39秒、严格核验40.20秒，峰值RSS约0.74 GiB，压缩96,951 bytes。通用用例核迭代耗尽world与回边；首轮遗漏的exhaustion状态桥已按原F4修正。未证明当前内容、effects或第一阶段完成。
- **`config-addressed-world-current/verification.json`：符号地址门通过。** 原87访问保原world：73字段/index位置、14调用输入，合108来源路径。8个显式写位置均追至同一个原call-result根；7属性路径与1动态key保原selector，未写专用规则。34路径保producer/module等缺口，无budget截断；不能据显式写集合忽略call/descriptor副作用。构建42.68秒、核验43.21秒，峰值RSS约0.75 GiB、压缩33,264 bytes；通用小用例核scope隔离、动态索引、opaque call与引用环。
- **`config-world-returns-current/verification.json`：跨函数返回门通过。** 声明上下文优先，再保独立历史may-call点：10共享状态节点、9返回边，8条条件引用路径；正常run分支已在图内。world和data分别核验，另一个调用结果不冒充原引用；6节点预算前沿及1引用返回边界保留。祖先一次认证＋按unit查调用，将同图单次构建267.01→186.46→93.52秒，四表字节完全一致；严格读回100.32秒，压缩396,563 bytes、峰值RSS约0.75 GiB。这是分析器对照，不是LeWM加速比，也未获内容版本或全覆盖证明。
- **`config-reference-consumers-current/verification.json`：实参消费者及共享正文门通过。** 35输入使用分开callee/attribute receiver/位置/关键字；9源形参绑定进入6共享正文，保202状态访问。已核正常run的config实参→core.run_job config形参及正文（Source Scope13）；复制函数输入保依赖而不unwrap输出。构建137.75秒、核验144.03秒、峰值RSS约0.76 GiB、压缩413,098 bytes。单次历史表扫描保原证据，通用小用例核receiver/static/env、world与deferred边界。139前沿是来源/接口未决记录，包含未选中输入路径，不是139个被拒优化或139个无消费者操作。
- **`config-value-flow-current/verification.json`：正文操作和值依赖门通过。** 保原833个操作及typed输入/输出、18,444边（含4回边）、50局部位置/227访问；不生成输入输出或writer/reader的笛卡尔积。9形参入口得到75处may依赖调用输入，正常run_job配置形参已追至task调用35实参0；复制输出不冒充原对象，172名称内容/捕获边界显式保留。构建165.12秒（父认证142.80、正文19.49、查询0.036）、严格核验172.68秒，峰值RSS约0.78 GiB、压缩535,261 bytes。通用小用例1.45秒；真实核验阻断目标import。不是已证明的内容来源统一、执行路径或第一阶段完成。
- **`config-value-interfaces-current/verification.json`：派生实参接口门通过。** 75输入保父may-dependency，单扫历史calls接14条原实参/形参绑定、8源函数；task调用35 actual2369→compiled rawrun formal3972已接原world/data返回。根config与派生actual不因此成为alias。84条前沿含同一输入的多target边界，不是84个被拒优化；主要为native/目标契约、构造及pack。完整父认证173.82秒仅一次，接口构建13.53秒、同进程原规则重验13.13秒；峰值RSS约0.80 GiB、压缩12,818 bytes，阻断目标import。compiled正文未在本视图展开，当前caller上下文、运行dispatch、内容版本及全图完成仍未证明。
- **`config-body-expansion-current/verification.json`：普通/compiled正文展开门通过。** 11共享正文中6个只引用父表、新增5个，12参数入口；新增605操作/13,442边/72调用。compiled rawrun形参3972已进入原编译正文（526操作、11,554边、60调用、8回边），得到67个may依赖调用输入；不运行compile/exec或目标。2个环境等非数据参数路由保独立边界。完整父认证188.00秒、正文构建23.27秒、同进程重验26.40秒，峰值RSS约0.80 GiB、压缩387,227 bytes；compiled材料另独立核原domain/ordinal/digest/profile。原port ID不变，旧body payload复制0，循环保共享回边。仍未证明当前内容、activation或全覆盖。
- **`source-native-binding-materials-current/verification.json`：独立生成声明目录门通过。** 2839定义、1703导出/1703 wrapper、2220 group，复用仍有效原始材料并核当前工具/源码版本；未复用失效旧source绑定图，也未运行torchgen worker或源solver。构建2.38秒、strict读回4.68秒、峰值RSS约0.28 GiB；定义表压缩840,714 bytes，原始材料约37.1 MB。所有native引用仍None/DECLARATION_ONLY，源/原生/资源连接均False；manual绑定和Python reexport未纳入，不将声明目录当作链路已贯通。新模块用`source_native_binding_materials.py`，原C2b collector逐字保留。
- **`config-call-context-current/verification.json`：选中入边与构造协议门通过。** 1,569原接口记录、16共享入边上下文、220callee查询（1,536引用状态/1,316边）。形参只沿栈顶原接口弹出；未选outer caller不合并，声明edges证据单独适配，不伪装历史calls。通用两caller回调用例0.91秒，真实声明证据也核过。原168调用点投影318构造阶段、64 source new/init接口；new结果与world保持ConstructionPort，init数据丢弃，foreign/pending不补完成。当前函数origin=0、868历史候选关系全部OPEN、236来源边界（75 namespace、133 producer/成员、27 call/protocol、1 outer）；这不是优化被拒或新调用目标已确定。完整父认证215.11秒，构建33.28秒、重验27.31秒；压缩397,823 bytes、峰值RSS约1.66 GiB，无target import/执行。补声明schema支持前后当前图各表字节一致；第一阶段仍未完成。
- **`config-constructor-class-inputs-current/verification.json`：构造兼容类型投影已核。** 原64 source entry给64单参数class输入（10 class object、54兼容instance），可共享为50声明上下文/34源函数；原entry、source_class、Fn connection及所有条件仍保留，额外类型投影缺口0。1.04秒完成原route逐项校验与typed表读回；不把无关pack算成新的class缺口，也不声称精确运行类型、MRO或分配。后续成员展开见下项。
- **`config-constructor-members-current/verification.json`：构造输入→成员/正文门通过。** 64原构造entry进入51共享声明上下文，2条普通成员接口；51正文上下文映射46共享body（原11只引用、新增35），新增870操作/60调用/19,227边。120未解调用仍保原代码位置；classmethod兼容实例分支另需bound class等值条件和open-subclass前沿，不能默认cls是requested class。源码单元先批量读模板，再投影正文。完整父认证250.09秒、构建92.04秒、原规则重验101.32秒；压缩633,726 bytes。没有证明实际activation、MRO或完整调用图。
- **`config-class-bases-current/verification.json`：有序基类与namespace来源门通过。** 39类/30基类槽，其中29槽保源码类候选；209来源状态/187边。补标准`import a.b`父包属性来源后，原三表字节未变；构建12.47秒、重验13.04秒、压缩21,969 bytes。113前沿保当前namespace/builtin等字段缺口，不授实际bases/MRO；通用用例0.93秒。
- **`config-namespace-callees-current/verification.json`：namespace→callee门通过。** 原236查询锚点共享168来源图；26条件接口涉及13源函数，102具名请求不当作native目标。原caller栈、实参、data/world及路径条件保留。父链认证250.94秒一次；本图构建11.44秒、重验12.43秒，压缩133,875 bytes。
- **`config-inherited-members-current/verification.json`：继承路径→成员/正文门通过。** 同一认证父对象复用，无二次父认证；64原入口→52上下文，2直接＋4继承接口；47共享正文中11引用父表、新增36（882操作/62调用/19,483边）。原base槽、namespace路径及descriptor条件随边保留，不按第一基类或同名类选实际MRO。构建97.05秒、重验102.22秒，压缩653,963 bytes；121正文调用前沿仍开放。本轮两图全程478.72秒、峰值RSS约1.79 GiB。
- **`config-source-fact-materials-current/verification.json`：源证据物化门通过。** 旧`ReferenceSlicer.fact`把collection当primitive目录的问题由显式目录路由解决，原证据键、GP、locator不改，不造文件或软链。现扩至所列9图的657,136引用→771原分片（765重定位），逐核目录链、stored/decoded收据、unit及locator；compiled保绝对variant与records/0，不回退原源码。构建131.85秒、重验136.74秒；索引71,088 bytes、原分片合99,713,538 bytes，峰值RSS约1.01 GiB。旧逻辑URI须经material resolver解析，不能直接`Path(uri)`；此门不重新授予图语义或完整祖先覆盖。
- **`config-connected-bodies-current/verification.json`：共享正文→下游查询门通过。** 复用47正文、新增8正文/610操作/70调用，合55正文；26 namespace入口＋67构造入口＋18成员入口共111，全部保选中outer caller，最大stack4、入口预算截断0。421查询保2,993状态/2,572边，补72条namespace接口（14源函数）、70具名请求及74构造接口，均为条件关系。新增派生返回须匹配完整caller stack，111条`interface_scopes`存许可域，防同一结果端口串到另一caller；原历史may关系不伪装成匹配证明。3个小用例1.51秒核caller分离、双层转发和派生返回许可。父认证250.91＋114.05秒仅一次，构建109.09、重验166.70秒；压缩4,728,937 bytes、峰值约2.50 GiB。这些是分析器耗时，不是LeWM性能。
- **`program-declared-calls-current/verification.json`：全源树调用声明图已构建。** 按通用source-root选择581原单元，48,290 callsite与原owners/callee全部保留；675,747 namespace状态、639,845来源边、33,558具名请求。4个spawn worker按unit独立写入，catalog各初始化一次、每unit清普通facts/端口缓存；构建383.97秒、压缩42,785,099 bytes，最大子进程RSS约1.04 GiB。入口源码unit完整重推4.29秒；没有声称581单元都再次语义重推。无全域FIFO截断；7个selector深度边界分布于3源码单元，其他未决为版本/参数/call-result等字段或关系，不是缺失callsite。scope声明不等于已执行。
- **`program-named-bindings-current/verification.json`：完整符号→生成绑定声明门通过。** 581单元按完整返回模块＋selector路径查既有2839声明，2,559 callsite得到7,543候选，保196 binding/196 ATen selector及全部overload；30,996请求没有对应生成声明，不能按末段同名补匹配。原callee/参数/packs/receiver/result/world都保留。4-worker构建239.08秒；修正guard与分析未选状态混用时，仅迁移7543条条件注解3.39秒，原ABI及匹配集合未改，新规则选中unit读回8.48秒；压缩2,003,330 bytes。原生schema、parser接受、实际dispatch和scope激活仍未证明，不是可变换机会或实测调用次数。
- **`program-binding-native-current/verification.json`：源码→canonical原生端口门通过。** 从上述匹配机械选出196精确selector，复用isolated parser/lowerer按64分4批；原声明目录不改，以独立links表连接。581分片保29,964输入依赖、7,543返回包装依赖及7,543组显式source world→native world / native normal world→source result_world；这些是条件依赖，不是值/状态版本相等，wrapper前后effects仍OPEN。2,553输入转换/receiver未解，22参数包依赖不伪装成单参数。初构建39.45秒；审计发现整数列表varargs遗漏后续维度，已按通用声明规则重建3,920条聚合依赖，实际四维base overload逐GP验证；fixed/optional列表保歧义OPEN。归一化刷新26.51秒、没有重跑原生parser或源树；全部196 canonical图核验＋选中unit新规则重推1.68秒。表压缩5,841,417 bytes，native材料与图1,417,715 bytes；未声称581单元都再次重推。未导入/执行目标或选择实际dispatch，也未接硬件placement。

- **`program-control-names-current/verification.json`：顺序敏感名字接线已验证。** 机械选出所有原selector截断查询（3单元/7查询），8个read过滤共排除23条正常路径不可达写边，7处截断归零；保3,995控制状态/4,012转移/437定义。C2 slot.owner核对函数环境；原writer FactRef、所有READ recipe上下文和未知效果分别保留。缺任何同槽写/参数锚点时禁用排除。3-worker初构建76.40秒；共享格式迁移后与下列完整单元共4任务并行重推76.96秒，原查询/定义语义指纹均未改变。当前表压缩818,158 bytes，最大读回子进程RSS约712 MiB。不是581单元全域顺序分析，也不证明实际dispatch或Tensor内容版本。
- **`program-control-unit-current/verification.json`：完整单元顺序建图已验证。** 37/37原调用，11组到达定义共享6份函数正文（425操作/3,893原控制边）；15个read过滤保9,000上下文状态及真实回边。无profiling构建19.10秒；选中单元完整重推23.64秒。共享后表893,122→726,417 bytes，所有原定义/查询语义指纹一致；旧63.53秒构建有cProfile插桩，不能与本次clean时间计算加速比。只覆盖所选单元，剩余imports/参数/字段来源明确保前沿。
- **`program-control-names-loop.json`：真实循环传播通过。** 原BACKEDGE与匹配recipe栈保留，1,172状态/1,176转移；前驱写跨回边到读取的路径未被误删，循环不变量绑定在固定点保留，未展开迭代。14.34秒并通过typed codec/import guard；复用同材料模拟缺失写锚点，新过滤器明确拒绝排除。这里证明绑定定义传播，不证明所引用对象内容不变。
- **`program-source-resources-current/verification.json`：原生端口→资源类型桥已验证。** 581单元保18,283条源码归一化路由，539个共享类型投影（496 Tensor、32 Device、11 Generator），接1,617目标池/设备候选；另保1,162源单元host候选、283 dispatch声明及588 native executor候选。复用12硬件节点及原拓扑，不重新探测设备，不制造实际分配或传输。构建37.15秒，全局类型/硬件与选中unit路由重推7.60秒，表压缩415,607 bytes、峰值RSS约319 MiB；未声称581路由分片都再次语义重推。

native/资源审计：11个旧`python-bindings-*`图为schema1–4且producer过期，不能接当前schema5 reader/ContextTargetGraph；
原始`materials.json`仍通过当前隔离工具与材料版本核验，可独立重建声明。现有资源图的264 placement candidates对应operand_sources=0；
它们已由`program-source-resources-current`的原归一化端口路由替代用于当前资源接线。
源码path→mount/disk只表示文件所在位置，不证明程序open/read/write。硬件inventory有效不等于源程序已接资源或实际产生ResourceUse。
`config-body-expansion-current/downstream-audit.json`按11正文全部调用查原关系：168调用点中134有814条历史may边，涉及346个源函数（339尚未展开）；
含construction/new/init、deferred及未匹配caller上下文的callback候选，不能据此宣布346个真实调用。当前compiled单元的torch namespace仅有dtype `float32`读取，
该旧入口视图未得到算子调用依据；当前已另建全源树声明图及196原生接口，不能把新声明候选反推为这个旧入口已激活。

## 后续顺序与验收

1. **输入字段层：** plain/untyped条件性字段应用与lazy引用子门已过；不代表完整cfg。未知prefix与中途地址/合并状态按表保留，不从条件候选证明当前内容。
2. **跨层源调用/状态层：** 全源树声明与入口上下文分开，通过原call/CodeScope/端口连接。正常控制流的到达定义已接入查询，原7个selector截断归零；保C2 slot所有者、原writer事实、所有recipe上下文并集，锚点/预算缺口禁用排除，外部未知来源仍OPEN。下一步把顺序敏感来源用于更广的源调用，并接字段/返回生产者、捕获和参数类型；不调预算或写变量名特例。原声明与异常/resume分支不被覆盖。
3. **算子与资源层：** 196个ATen接口、源码端口与资源类型/目标池候选已接，539投影共享而不是按调用复制。下一步补非生成接口和源运行I/O；源码文件所在位置不等于运行I/O，类型候选不证明物理使用或placement。运行地址等未知字段不伪造。
4. **全图验收：** 源码闭包、顺序敏感传播、循环和跨层接口的覆盖分母/缺口审计。队列清空本身不证明全覆盖；第一阶段通过后才进入化简。

CLI与查询见 [DEVELOPMENT](DEVELOPMENT.md)，实体与连接约束见 [MODEL](MODEL.md)。
各层以小索引＋分片正文按需读取；现有入口前缀不为每一子门重新全量构建。
