# 自动建图：实际能力与验收路径

日期：2026-10-15。N2.a 有限函数体门已通过，见 [N2A_ACCEPTANCE.md](N2A_ACCEPTANCE.md)；
N2.b0 的入口驱动自动范围与接口清单已有限验收，见
[N2B0_ACCEPTANCE.md](N2B0_ACCEPTANCE.md)。
完整 LeWM 自动建模尚未验收。最新边界、难点和后续验收见
[AUTOMATION_PROGRESS.md](AUTOMATION_PROGRESS.md)。

## 用户输入与自动化边界

实际使用要求是提供源码/程序入口或运行命令，SCAR 自动识别构造、恢复依赖、
建立图和报告。用户不需要为每个 Tensor 填类型，不需要手工制作 IR，不需要
给某个 workload 补节点、连边或 pure 标记。手工 IR 仅用于独立测试校验器。

新增的入口只要求源码入口和项目边界，不要求函数列表：

```bash
conda activate lewm
scar inventory-program /path/to/project/entry.py --project-root /path/to/project \
  --out inventory.json.gz
scar check-inventory inventory.json.gz
```

它自动发现本地候选源码、枚举定义/调用/覆盖缺口，并共享每文件准备结果，
自动尝试有限 body 构图。候选文件图与独立 body 图尚未合成完整程序图；
详细报告含义见 [PROGRAM_INVENTORY.md](PROGRAM_INVENTORY.md)。
任意运行命令、动态 loader 和运行配置到完整执行模型的连接仍未完成。

旧入口仍可用于**指定一个源码函数体**的诊断：

```bash
conda activate lewm
scar model-program /path/to/program.py --entry Class.method --out report.json.gz
scar check-source-program report.json.gz
```

`model-program` 不 import 或执行目标。正常构图返回 0；未支持的函数体返回 3
并保存带位置的缺口报告，graph=null；输入错误返回 2。带缺口的图不等于完整
程序模型。`check-source-program` 返回 0 只表示报告与当前源码确定性重放一致，
包括如实重现 UNSUPPORTED 报告；不是优化合法性审批。

## 当前自动恢复的连接

1. 源码快照与精确 AST 位置 → 既有 Opcode、有序 operand 与新 Operation。
2. 参数 → 引用值 → 逐使用点；相同引用的两个使用仍有独立 UseID 和位置。
3. 普通局部赋值 → 当前定义；Python 编译期符号表决定 local/free，而不是
   仅扫描已执行的语句。不可达 import/del/except target 也影响作用域。
4. if/else 的逐路径定义 → 真正的合流参数；不能把只在一侧定义的局部量
   错当成全局量。未知 truth conversion 保留调用及异常完成。
5. 普通表达式/调用 → 正常或异常完成 → 相应结果和后状态；正常结果不会
   流入异常路径，异常后的状态也不能倒退到调用前。
6. 同文件函数体候选 → 独立调用位置的 actual/formal/返回对应。候选仍为
   INFERRED；实际运行目标、namespace 条件未确认时不能据此改接确定调用。
7. 每个图操作、值及 use → typed 源码对应；所有层和对应关系可从源码重放。

未知 Python 操作目前经过一个 coarse world 状态域；它保留保守依赖，
**不能区分实际只读哪些 Tensor、文件或 RNG**，也不能支持有用的独立性证明。
Python host 返回不代表 GPU kernel 已完成。自动分类、依赖恢复、效果精度、
运行对应和优化证明是不同的完成度，报告分别披露。

## 尚缺什么，如何补，如何验收

| 顺序 | 缺口与实现方向 | 自验要求 |
| --- | --- | --- |
| N2.a | 自动函数体连接、公用命令、严格持久化与完成方式 | 自动源码正例；作用域、分支、异常、重绑定和报告篡改反例；外部压力报告 |
| N2.b0 | 自动 import 范围、定义接口、全部可执行源码位置清单、批量 body 尝试 | 无逐函数输入；重导出/歧义/遮蔽/预算/动态边界；压缩报告严格重放和外部入口压力 |
| N2.b | for/while、零次路径、回边、break/continue/else、循环携带定义；随后 try/with 的退出 | 循环值/状态逐前驱绑定；异常和 finally 不可丢；不把一次 trace 当全部路径 |
| N2.b | 属性/下标读写、容器与对象状态、alias；将粗 world 细分为可核对位置 | 同引用内容变化、view/共享写、部分覆盖、未知 alias 冲突反例 |
| N2.c | defaults/decorators/导入初始化、跨文件调用、动态 dispatch 与入口依赖范围 | 定义时与调用时操作分离；目标重绑定、初始化残余效果；自动覆盖清单 |
| N4 对应 | 将静态图接到真实 nn.Module/operator/copy/kernel/sync 的动态实例 | 输入/输出 occurrence、实际代码版本及 stream 顺序；to/expand 不误计 copy/allocation |
| N3/G7 | 观察根 → 依赖闭包 → 子图替换/上移/共享 → 具体修改指导 | 精确改接哪些 use、保留哪些状态/异常/效果、失效与成本；可重放 proof ledger |

N2.b/N2.c 内部可按源码反例调整顺序；不能通过放松校验获得覆盖率。按源码
出现频率选择构图规则，不把语法出现次数称为性能成本。实际优化仍需运行证据。

## 完整 LeWM 压力标准

LeWM 只作为外部输入。最终应从入口/成功命令自动选依赖范围，恢复 CEM 循环、
模型调用、预处理及结果消费者，并回答跨层来源、哪些状态随迭代变化、已有
缓存命中/填充路径、物化消费者、常量来源与 import 残余依赖。

当前指定若干函数的测量只验收这些边界，不折算成全程序完成率。自动产生
大量节点不代表关键边已正确连接；源码图中某操作缺少效果摘要也不代表它
可以删除。SCAR 必须给出具体断点，再用通用规则修复后自动重建。

没有新 backend、已选择的 LeWM 变换或已验证的 LeWM 加速比。
