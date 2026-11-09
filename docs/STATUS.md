# 当前状态

**第一阶段尚未完成；当前只做静态建模、建图与查询。**
NORMAL_SUCCESS / CPython 3.14.7；交付后端约定 C++20、算子 ABI v1、计划 schema v1。
本阶段未运行 LeWM 或导入 torch/Hydra/OmegaConf。以下秒数均为分析器耗时，不是 LeWM 加速比。

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
| native声明/资源 | 独立2839条生成声明、1703导出；有效硬件旁图12节点/12边 | 旧source binding工件过期；当前声明未接源/原生端口，原资源候选operand_sources=0 |

五类实体为 Operation / Value / StateLocation / Region / Resource；输入输出是端口角色。
对象、storage、逻辑内容版本和物理副本互不等价；循环不按迭代复制。

## 当前验收证据

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

native/资源审计：11个旧`python-bindings-*`图为schema1–4且producer过期，不能接当前schema5 reader/ContextTargetGraph；
原始`materials.json`仍通过当前隔离工具与材料版本核验，可独立重建声明。现有资源图的264 placement candidates对应operand_sources=0；
源码path→mount/disk只表示文件所在位置，不证明程序open/read/write。硬件inventory有效不等于源程序已接资源或实际产生ResourceUse。
`config-body-expansion-current/downstream-audit.json`按11正文全部调用查原关系：168调用点中134有814条历史may边，涉及346个源函数（339尚未展开）；
含construction/new/init、deferred及未匹配caller上下文的callback候选，不能据此宣布346个真实调用。当前compiled单元的torch namespace仅有dtype `float32`读取，
生成声明目录尚无由此得到的算子调用依据；下一门须先区分源调用上下文及构造协议，而非把声明目录直接当作native链路。

## 后续顺序与验收

1. **输入字段层：** plain/untyped条件性字段应用与lazy引用子门已过；不代表完整cfg。未知prefix与中途地址/合并状态按表保留，不从条件候选证明当前内容。
2. **跨层源调用/状态层：** 原config→core.run_job→派生task实参→compiled rawrun形参及正文已保条件接通，普通/compiled材料适配门已过。下游按callsite/caller上下文分开普通调用、construction/new/init、instance-call与deferred协议，先接原body接口及状态，再推进已确认声明正文。保全部may候选及未解条件，339个未展开函数不冒充已激活正文。输入和后续版本仍待证明，不重新编译目标、复制循环或盲增预算。
3. **算子与资源层：** 原始生成绑定声明已从旧source solver解耦；待上述源连接提供NamespaceLookup/类型来源，再接Python→native归一化依赖和资源类型候选。重接原实参，不能继续使用operand_sources=0的旁图声称全链路完成；Tensor类型、设备候选与实际分配/传输分开。源运行I/O与源码文件位置分开建模；运行地址等未知字段不伪造。
4. **全图验收：** 源码闭包、顺序敏感传播、循环和跨层接口的覆盖分母/缺口审计。队列清空本身不证明全覆盖；第一阶段通过后才进入化简。

CLI与查询见 [DEVELOPMENT](DEVELOPMENT.md)，实体与连接约束见 [MODEL](MODEL.md)。
各层以小索引＋分片正文按需读取；现有入口前缀不为每一子门重新全量构建。
