# 当前状态

**第一阶段尚未完成。当前只做静态建模、建图与查询。**
NORMAL_SUCCESS / CPython 3.14.7；后端约定C++20、算子ABI v1、计划schema v1。
没有运行LeWM或导入torch；以下时间都是分析器耗时，不是程序加速比。

## 已落实

| 层 | 已实现的图与接口 |
|---|---|
| F0–F3 | 866材料：849 Python源与17 stub；原bytes、词法/语法、scope、binding及compiler视图 |
| F4 | 882,537共享模板、3,385,528操作、4,645循环、24,159,357边；函数/循环不按调用或迭代复制 |
| F5局部接口 | 852 source单元，8,750 iteration、709 deferred body、9,361 mapping模板；48 worker构建68.80秒 |
| F5求解 | 参数/默认值/捕获环境/world/返回、构造/属性、容器增量和同步generator；参数包缓存及共享content因子 |
| 静态字段 | 每端口最多4个literal候选及type/open信息；参数、返回、模块成员、属性、容器关系保原端口与条件 |
| 实际入口 | 自动连接path/read_text/compile/exec；有效future flags独立建C1/C2、官方C3-T/S及632模板共享F4变体 |
| 命名空间 | 有序C2 lookup、READ/WRITE/DELETE及原world；函数实际globals捕获；exec字典与module身份分开 |
| 新入口求解 | 编译变体仅经exec激活；追加4,360端口，原5,978,863端口编号不变；自定义builtins内容订阅与标准fallback条件分别记录 |
| Frame与输入 | 已选callable→原factory globals捕获→caller frame→exec/globals()；root dict view和独立声明输入端口，保创建world与callee |

原基础manifest SHA：601e929904dc7481693f4a0747b7e01269ecf6d1302ff1efec072627c288aba0。
编译上下文变体不覆盖原F0–F4。源码、对象、storage、逻辑内容版本和物理副本互不等价。
原生声明及CPU/DRAM/GPU/设备内存/SATA/NVMe资源旁表已有，尚未与新入口完成全链路重验。

## 当前实际验收

路径相对artifacts/current/queries/，全部是静态结果。

- `launcher-f4-variants-current/verification.json`：实际compile context的1,063语法occurrence全部归类；632模板、2,079操作、15,162边，包含原world序列和2个循环。
- `launcher-exec-roots-current/verification.json`：2个条件分支；namespace选择、builtins插入、closure检查、audit、body、discard/release共6阶段；正常结果None，根返回值不冒充exec值。
- `launcher-namespace-graph-current/verification.json`：234个名字操作、4组globals捕获、3条带版本/lookup条件的内容连接；构建5.44秒，压缩表35,034 bytes。这些may边不是常量或可变换证明。
- **历史接口前缀（8986b4ad）：** `launcher-context-targets-current/verification.json`完整typed读回20类已发布关系表，并展开实际context函数体。1M事件前缀构建98.62秒、核验50.50秒，产物约4.8MB；275加载单元、2,007 scope、7,942调用连接，其中166条caller属于编译上下文；2个exec分支、96条有guard的builtin候选。
- **完整读取frame对照（d4372014）：** `launcher-frame-targets-current/verification.json`完整typed读回26类关系表，核selected factory/callee/capture/world与既有calllink吻合、4个输入字段与原entry.json逐字匹配且已接content因子。11个root接口、1个默认exec frame绑定、25个globals()读，当前前缀的frame/capture obligation均0；7,898条调用连接，其中166条caller属于编译上下文。1M事件构建172.85秒、核验58.47秒，产物约4.8MB。
- **当前按需frame门验收：** `frame-capture-selection/verification.json`逐项核原14条factory/callee证据对应的3个函数模板，并核第二模板增选保留已有refs/witnesses。`launcher-selected-frame-targets-current/verification.json`完整typed读回26类关系；实际读取仅3计划＋11 root接口。1M事件构建129.08秒、核验59.20秒；8,096条调用连接、166条context caller、frame默认绑定1/globals读25/声明输入4/相关obligation0。
- **未收敛：** 当前普通frontier为17,857，namespace frontier为0；状态仍为CONTEXT_TARGET_BUDGET_FRONTIER。frame绑定是带原版本/选择条件的引用关系，未宣称runtime对象身份；locals快照及不确定字段继续保留协议/前沿。
- **读取成本已减少：** 旧索引578计划/73.89秒，当前3计划/29.05秒；11 root接口全部保留。两次1M不是固定点，队列顺序和候选计数可不同；不据此宣称完整关系相等或LeWM加速。后续仍可减少header的重复校验。
- 通用单fixture核晚到自定义builtins能接入source callable；`relation-replay-verification.json/.py`可复现新旧类/容器flow的832事件与9类关系完全相等，耗时9.50秒（含fixture构建），不作为主图加速数据。
- 旧独立eval.py长任务已由实际launcher/context求解替代并终止，未发布固定点；收据为`entry-pack-fixed.superseded.json`。首个1M原型的两项namespace问题记在`launcher-context-targets-1m-reviewed/review.json`，当前产物已修正并重验。

## 后续顺序

1. caller frame及按需读取门已通过。下一步先准入Hydra正常RUN调用源（安装版hydra/core/utils.py当前未在facts中），获得task_function(task_cfg)的原始端口；不得借用已有passthrough/rerun分支冒充。locals快照/隐式状态仍有待静态细化的字段。
2. 补配置输入与字段来源：实际argv有launcher追加项；YAML保defaults顺序、package、覆盖及插值；环境/搜索插件未定处保条件。然后接正常task cfg形参及原GET/SET端口。把module需求机械分为源码、namespace、原生边界和真正缺少的输入，不把全部demand当缺文件。
3. 将新的context图接到既有Python/native绑定、算子及资源要求图；保alias、逻辑来源、位置、状态和效果，运行时未知字段仍未知。
4. 在上述入口与接口稳定后持续求解，审计源码、跨层边界、循环和资源的覆盖分母。队列清空不等于整个程序覆盖完成；第一阶段通过后才进入化简。

当前入口：
`python -m scar.analysis.source_context_build --facts <source-facts> --namespaces <namespace-graph> --entry <script-entry> --interfaces <local-interfaces> --out <fresh-output> --until-fixed-point --jobs 48`

各材料由对应静态阶段机械生成；CLI参数是材料路径，不是手写业务连线。小引用索引与分片正文分别保存，读取时按需展开共享子图。
