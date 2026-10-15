# N2.entry：将真实代码来源接回自动程序清单

日期：2026-10-15。状态：**有限来源桥接已验收**；实现 `b886e40`，
429 gate / 1,477 回归通过，原外部入口生成与严格重放通过。前置版本 `45c80ee`。
覆盖和剩余断点见 [N2_ENTRY_ACCEPTANCE.md](N2_ENTRY_ACCEPTANCE.md)。

## 1. 要解决的实际断点

N2.b0 从入口的 import 语法得到 143 个候选文件，未包含启动器动态执行的
源码。已有真实 trace 已记录这些文件的 CodeID。下一步复用证据完成连接，
不再增加 collector、detector 或 backend，不修改外部 LeWM。

输入是入口、项目边界和已有 trace；用户不提供动态文件或函数列表。输出从
运行证据自动增加来源候选，再展开 import 闭包和核心 body 图。源清单仍包含
未观测的静态候选，不能把一次 trace 当作完整程序。

## 2. 模型与证据关系

```text
有摘要的原始 trace 逻辑流
  -> 按 CodeID + process 区分的代码观察（首末记录引用、次数）
  -> 路径选择结果（候选/相对路径/生成代码/界外/缺失/链接等）
  -> 与入口共享预算的源码发现集合及当前快照
  -> 精确离线代码复现 + 定义候选
  -> 已有 DefinitionInventory / module initializer / core body 对应
```

这些是 evidence 与 source/core 的 typed 对应，不新增程序顶层节点。
Operation/Value/StateLocation/Region 继续承担程序结构；文件名不代替 Value
或对象身份。代码复现仅证明 code object，不证明绑定、闭包、效果或值相等。

旧 trace 可缺原始 compile filename、flags 和 Python 配置；精确 marshal 复现
失败要报告未匹配，不能放宽摘要或把当前文件 hash 冒充运行源码 hash。已有
`correspondence_v2` 的编译索引复用为共享 helper，每文件/文件名/编译配置缓存，
不按每次 invocation 重编译。来源与物理文件分别去重，保留多进程来源。

## 3. 构建与优先级

1. 有界流式读取 raw/gzip JSONL；记录解压原始字节 SHA256 与行定位。
   不加载旧大图、不保存 Tensor 数值，不复制逐调用输入输出。
2. CodeID 提及的绝对项目内 `.py` 是候选。相对路径缺可靠基准时不使用分析器
   cwd；generated/outside/symlink/missing 均保留独立结果。不得扩展项目边界。
3. 入口先入队，运行候选随后；复用一个发现队列、visited 和文件/字节/目录
   预算。动态来源不伪造 import SourceReference。已由静态发现的文件仍保留
   每条代码观察的来源连接。
4. 源码准备仍每文件一次；在同一快照上核对代码，避免第二次读取另一版本。
   实际来源文件和其定义候选优先消耗有限 body 预算；优先级不授予合法性。
5. 调用 callee 不因来源或代码复现自动成为已确认目标。主机/设备状态、完整
   loader 语义、参数版本和消费者闭包仍由后续门处理。

## 4. 版本、预算与重放

- 无 trace 时保持 `scar.program-inventory` v1 的 API、排序和字节级结构语义。
- 有 trace 时使用明确的 v2 envelope，包含 typed runtime scope、输入摘要、
  选择结果及匹配；SourceDiscovery v1 记录不被偷偷塞入新字段。
- 从报告重新读取原始 trace、重建选择与发现，并重放当前源码和核心图。
  不信任报告自报 seed/witness。trace 变化、源码变化、新候选、篡改必须失效。
- trace 有独立的解压总字节、行数、单行、唯一代码组及文件名候选上限；代码
  核对有独立编译尝试上限。原始输入无法读完时不能声称摘要/覆盖完整。
- 报告不能提高验证器独立上限。raw JSON 重复键、非有限值、无效编码要拒绝。
- gzip 是物理保留形式；同一路径的无损归档/重压缩保留逻辑流证据身份。
- CLI 输出不能覆盖入口、发现源码或 trace（包括 hardlink/symlink 别名）。

## 5. 自主验收节点

| 节点 | 必须产出的证据 |
| --- | --- |
| E1 观察与路径模型 | 真实有限 Python 子进程记录；重复/多 pid、相对/生成/界外/链接/缺文件；预算和严格 JSON 反例 |
| E2 共享发现 | 无静态 import 的动态文件及其 imports 自动入图；静态未观测分支保留；entry 优先；读入/计费去重；空输入与 v1 一致 |
| E3 代码与定义连接 | 同快照精确代码复现、源定义候选/正常歧义；旧版本/错误文件名/缺配置保持边界；多调用不重复编译 |
| E4 公共入口与重放 | `inventory-program --trace` / `check-inventory`；全部报告篡改、源/trace 变化、预算自升级和输出覆盖反例 |
| E5 外部压力 | 对原 LeWM 入口和已有真实 trace 自动重建，无手工文件/函数列表；列出新增范围、代码匹配及所有剩余断点 |
| E6 版本归档 | 冻结代码，mapped gate 与必要回归、外部源码不变核验、压缩报告、验收文档、commit/push |

本门验收的是自动来源桥接，不是完整 LeWM 模型，也不是完成一次优化。
完成后继续入口依赖展开、签名/定义时接口、循环携带值及细粒度状态；每步以
来源/状态/消费者查询的实际改善验收，不能以节点数量替代。
