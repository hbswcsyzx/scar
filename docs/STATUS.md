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
| native/资源 | 既有声明、CPU/DRAM/GPU/设备内存/SATA/NVMe 旁图 | 尚未与新入口完成全链路重验 |

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

最后一门仅通过局部有序组合：6项 obligation明确保留隐式库根、3个同名 schema查询、
组 override的已有目标选择、CLI/lazy层。OPEN_PROVIDER不产生虚构数据；未求出最终 cfg。

## 后续顺序与验收

1. **覆盖与引用层：** 原 argv→override语法/类型→有序字段版本→lazy引用；核覆盖后引用、missing与null/缺键分离，不把 YAML resolver当 CLI语法。
2. **配置接口层：** 补 ConfigStore/provider与输入变更条件，沿已验 actual/formal/world接到任务字段；保 deepcopy、删除与callback效果，不把初值冒充当前值。
3. **算子与资源层：** 新 context图连接现有 Python/native声明、算子及资源图；已知属性静态保留，运行地址等未知字段不伪造。
4. **全图验收：** 源码闭包、顺序敏感传播、循环和跨层接口的覆盖分母/缺口审计。队列清空本身不证明全覆盖；第一阶段通过后才进入化简。

CLI与查询见 [DEVELOPMENT](DEVELOPMENT.md)，实体与连接约束见 [MODEL](MODEL.md)。
各层以小索引＋分片正文按需读取；现有入口前缀不为每一子门重新全量构建。
