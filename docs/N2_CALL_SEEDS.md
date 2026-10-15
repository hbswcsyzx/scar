# D0：从真实调用自动取得紧凑源码见证

状态：**D0 有限验收通过**。实现 `39e8f22`：196 项门检查、全仓 2,033 项通过，
零失败/错误/跳过；原始 LeWM 调用归档生成与独立公共重放均退出 0。
这是 [调用连接计划](N2_CALL_BINDING_PLAN.md) 的 D0，不是 D1/C1/C2 验收。

源指纹：`81d6a6b675055eaa70a8e4dff566107dc3329859e999e7f918050bd983c26909`。
门报告 `artifacts/reports/gates/n2-call-seeds-verified.json`，全仓报告同目录
`n2-call-seeds-full.json`，外部来源报告 `n2-call-seeds-real.json`。

## 本轮实际结果

同一真实归档得到 84,319 个入口记录、812 个 entered-code 分组、850 份 captured
descriptor。548 个 code/source 核验通过，其中 421 个具有完整唯一 definition，
成为 421 个可展开种子；259 个 code link 为 INCOMPLETE、5 个 MISMATCH。
summary 的 `issues=0` 只指总体采集/记录问题，不表示这些源码边界已经消失。

生成 349.361s、峰 RSS 230,564KiB；独立重放 352.998s、峰 RSS 237,716KiB。
原始报告 1,558,907 字节、gzip 266,292 字节。源码、raw trace、原 LeWM Git HEAD
及 clean 状态前后相同。重放期间另有单文件 cProfile 诊断并行，重放时间不是
clean benchmark；生成在诊断前完成。两者均是分析器成本，不是 LeWM 加速。

分析成本仍高。按最大已观察源码 bytes 自动选出的单文件诊断，在重度 cProfile
下耗时 88.062s：`_Sources.context` 87.508s，`prepare_source` 47.745s，
`_Inventory.index→snapshot` 38.225s；其中三次全图摘要 `_digest` 累计 24.554s。
这些是嵌套累计时间，不能相加当总时长。诊断证明该来源匹配路径还创建、验证
和序列化未被种子结果消费的完整图层；下一门先共享轻量源码索引和既有 ID 生成
规则，不能简单删除公共验证。原始记录见
`artifacts/experiments/n2_call_source_seeds/source-profile/`。

## 为什么先做这一步

旧自动 body 队列只消费旧 RuntimeTrace，不能利用新 calls-only 中核验的代码。
为了取得展开目标而构造完整引用图，会保留所有参数/局部变量引用并生成大型报告。
新路径读取同一原始证据，只留下实际进入过的代码分组和当前源码见证。
不输入业务函数名单，不执行目标源码，不手工建立 workload 依赖边。

```bash
conda activate lewm
python -m scar.cli trace --calls-only --project-root /path/to/project \
  --out artifacts/traces/example -- python /path/to/project/entry.py
python -m scar.cli seed-calls artifacts/traces/example \
  --project-root /path/to/project --out artifacts/reports/seeds.json.gz
python -m scar.cli check-call-seeds artifacts/reports/seeds.json.gz
```

## 模型与证据

- `scan_call_trace` 是新种子路径与原完整调用路径共用的严格原始记录 reader。
  逐行解码事件后送入 sink；不累积事件行、FrameEntry/Exit 或引用向量。
  保留独立 invocation 集合以验证唯一性/计数，以及代码、文件摘要和 metadata。
- `EnteredCodeGroup` 按 `(process, code)` 保留次数和首末 invocation/原始行锚点。
  引用向量仍逐项验证并收取预算，随后丢弃；不因未保留就绕过校验。
- 只有该进程确有 captured descriptor、当前源码能重现其完整稳定代码描述、且
  唯一 definition/source 对应齐全时，分组才有源码种子资格。
  不以同名函数、文件位置或另一个进程的缺失 descriptor 补目标。
- `SeedCollectionMetadata` 只投影严格检查后的计数、限制和缺口；不复制未知
  extension 数组或局部值。原 metadata 的全部字节仍由 manifest SHA 绑定。
- 种子不是新的核心实体类型；它是执行证据到源码需求队列的来源对应。
  Operation/Value/StateLocation/Region 仍是程序核心结构。

代码见证不能证明当前函数实例、捕获环境、实参来源、内容相等或效果等价。
报告的 caller/data/effects/environment/transformation 五项权限固定为 false，
不能靠修改一个布尔值批准化简。返回引用相同也不提供复用许可。

## 重放、边界与兼容

`check-call-seeds` 先核对报告预算不超过验证者独立上限，再从原始文件重扫，
重新核验当前源码，最后比较完整规范报告；不信任序列化的 seeds 或 summary。
公共 CLI 另有解压报告字节上限；输出流式限额、同目录临时写和原子替换，失败
保留已有文件。拒绝覆盖原始 trace、源码输入及它们的 hardlink。

原调用报告格式保持不变，原 `_read_trace` 只成为 collecting sink adapter。
历史 reader 的独立测试从固定 `8eeaffe` Git 对象取得原函数和校验 helper，
而非将新 adapter 与自身比较。该检查发现并阻断了“后续 process descriptor
提前影响前一 process”缺陷；当前按旧逐进程可见性处理。

独立审查还用通用源码反例复现：Python 文件名可以是 `.json`，内容也能恰好
是报告 schema 的合法 JSON 表达式。source budget 失败时 `snapshot=None`，
旧路径保护曾遗漏这个已采集源码，允许报告覆盖输入。两个 CLI 现共用所有
captured filename 与已核验 snapshot 的保护集合，并检查同文件/hardlink。
目录枚举也改为流式处理，在发现超出 process 预算时立即拒绝；不将无关目录
条目整体排序/保留。无关条目仍需要遍历，不声明目录枚举的 CPU 时间上限。
初轮 191 项通过报告与后来实际失败的四个输出反例均保留，修订版重新验收。

正式门：`gates/n2_call_source_seeds.json`。报告须记录源指纹、实际测试结果、
旧报告重放，以及同一真实归档 trace 的时间、RSS、报告体积和输入不变证据。
采集截断、外部源码、descriptor 缺失与不唯一定义仍单列，不假装已建完整图。

## 下一步的实际连接

D1 才把核验种子自动加入 import/source scope 和 body demand queue，并采用新
inventory 版本保留精确来源。之后必须补实际 operand/绑定、函数环境、返回与
状态接口，最后接循环、细状态与逻辑来源。D0 不产生跨调用核心边，不新增
detector/backend，不声明 LeWM 变换或加速。
具体来源类型、入口依赖 frontier、共享准备及验收反例见
[D1 开发计划](N2_CALL_DEMAND_PLAN.md)。
