# N2.b0：自动范围、接口与覆盖清单验收

日期：2026-10-15。状态：**PASS_BOUNDED：有限源码范围与接口清单通过自主验收**。
完整 LeWM 自动程序图、化简指导和加速均未验收。

## 1. 冻结实现与自动输入

- 首次实现：`f21eb53`；267 项 gate 通过后，外部压力暴露分析开销。
- 效率修复后的冻结实现：`a6ed118ecea0e5fd0b59d513c558822d2053abd0`。
- 测试源码摘要：`5242b0a9676d22f1e54e617ac5357ff0e9334c5266e361da71ab7908ac0fc706`。

用户输入入口源文件和项目边界。默认自动推导候选 source roots，不输入函数
列表，不手工补任何 LeWM 节点、参数、边、版本或 pure 声明。

```bash
conda activate lewm
scar inventory-program /home/zyf/AAA/le-wm/run_inference.py \
  --project-root /home/zyf/AAA/le-wm --max-files 256 \
  --out artifacts/reports/gates/n2b0-efficient-lewm-inventory.json.gz
scar check-inventory artifacts/reports/gates/n2b0-efficient-lewm-inventory.json.gz \
  --max-files 256
```

其他预算使用默认值：源码 8 MB、目录 4,096、body 尝试 256、操作构造 10,000、
调用目标见证 4,096。解释器是 conda `lewm` 中的 Python 3.14.7。命令只分析
源码；未执行 LeWM。配置不是 LeWM 名称选择规则的一部分。

## 2. 本门实际增加的连接

```text
入口 -> 有控制上下文的 import 依赖 -> 物理源码候选及版本
     -> 自动定义/调用/阶段/覆盖清单 -> 有限核心 body 图及来源对应
callee binding -> import/export 源见证 -> 带未接受条件的目标候选
```

相同模块名的不同物理文件保留，定义身份包含版本和位置；重复 qualname 不覆盖。
默认值、装饰器、class body、函数体、推导式、annotation 分开记录。隐式装饰器
应用和 class construction 有独立接口记录，不伪造源 ast.Call。

每个成功准备文件的可执行 source atom 恰有一个覆盖记录。CONNECTED 只表示
有核心图来源对应；INVENTORY_ONLY 与 UNSUPPORTED 保留具体位置。操作效果和
实际目标没有因分类而升级。failed body/回滚操作仍扣共享构造预算。

重导出使用去重 BFS，完整 import 边保留，每目标一条确定性见证；不枚举所有
路径。有限跨文件候选保留 binding/namespace/实际代码对象条件，核心 callee
仍未确认。不同 body 的 coarse world 尚未合并，不能据 ID 不同推导状态独立。

## 3. 自主测试结果

| 检查 | 冻结结果 | 证据 |
| --- | --- | --- |
| N2.b0 映射 gate（含 N2.a/N1） | **336 passed**，25.25 秒 | `artifacts/reports/gates/n2b0-efficient-verified.json` |
| 整仓回归 | **1,406 passed**，97.94 秒，2 条既有警告，无失败/跳过 | `n2b0-full-regression.json`、`n2b0-full-regression.xml.gz` |
| 旧 validator 独立对照 | 48 例，已包含于 gate | `test_record_validation_compatibility.py` |
| 同快照构建与防御性路径对照 | 21 例，已包含于 gate | `test_source_preparation_equivalence.py` |

反例覆盖遮蔽/重绑定、父包与 namespace/重导出、重复定义、注解阶段、import
控制条件、失败成本、预算、篡改/源码漂移/新候选、输出不得覆盖源码。
类型检查优化仍逐次检查字段与 post-init；测试覆盖原地篡改、子类、Union 分支
副作用、错误路径和异常。私有源码工厂仍检查 decoded UTF-8 总字节预算、源
快照、构造计数和最终图；公共不可信图接口仍独立重放语义层。

整仓两条既有警告是多线程进程 fork 的弃用提示和量化 Tensor API 弃用提示。
Junit 原文压缩前后校验 SHA256，原始记录未丢失。

## 4. 外部自动清单：Observed

本轮自动范围有 **143 个文件**，原始文件合计 1,506,512 字节；候选根来自项目
及其中的两个打包子项目，未使用手工函数或路径补丁。无文件准备失败。

| 项目 | 实际数量及含义 |
| --- | --- |
| 定义 | 2,122：函数 1,563、class 287、推导式 245、lambda 27 |
| 源码调用 | 9,674；其中 169 条跨文件候选见证，不是已确认运行调用 |
| 覆盖记录 | 115,723：CONNECTED 163、INVENTORY_ONLY 101,922、UNSUPPORTED 13,638 |
| body 尝试 | 256：LOWERED_WITH_GAPS 16，UNSUPPORTED 240 |
| 未尝试 | 1,307 个函数受 body 预算限制；559 个定义需要 class/lambda/comprehension 接口 |
| 保留核心图 | 215 个操作、436 个值；构造工作 1,382 次（包括失败） |
| 发现缺口 | 外部/不可用 1,013、歧义 12、star import 10、动态导入 7、动态执行/编译 2 |

源码清单生成：**401.595 秒**，峰值 RSS **293,052 KiB**，gzip 约 **5.7 MiB**。
当前源码重放：**405.052 秒**，峰值 RSS **689,104 KiB**，返回 0，完整清单确定性一致。143 个已读源码
快照全部未改变；LeWM Git HEAD 和干净状态前后相同。分析与回归在同机运行，有其他服务负载；这些数字是
分析成本，不是 workload benchmark，不能推出 LeWM 加速比。

启动器的 exec/compile 边界尚未恢复其加载文件；外部依赖也未全部展开。
默认值、装饰器、async/variadic/keyword-only 等接口阻断了 97 次 body 尝试。
循环、状态写入、closure、BoolOp 等仍有源码定位的缺口。115,723 条清单记录
绝不表示已恢复同等规模的核心依赖图。

## 5. 失败与修复记录

1. 开发时 import 位置与别名位置混用，后分为 statement source 与 alias_source。
2. 独立反例发现 annotation 执行归属混淆、failed body 未扣总操作预算，均已修复。
3. 重导出见证按路径展开会指数增长；改为去重 BFS 和独立见证预算，原 import
   边仍保留。补充 import 控制上下文，分支内导入不再失去条件。
4. `f21eb53` 的同范围外部尝试持续 919.862 秒未完成，核对自有进程身份后
   SIGTERM；shell 返回 143。原计时和中断记录保留。这不是成功 baseline。
5. cProfile 定位重复 schema 解释及同快照重复语义抽取。缓存类型计划，不缓存
   对象有效性；源码工厂内部生成三层，公共输入验证与报告 replay 不减弱。

独立的源码准备局部测量（无 profiler，warmup 0，重复 3 次）：

| 实现 | 每次秒数 | median / min / max |
| --- | --- | --- |
| `f21eb53` | 4.110 / 4.108 / 3.934 | 4.108 / 3.934 / 4.110 |
| 效率修复 | 1.189 / 1.113 / 1.113 | 1.113 / 1.113 / 1.189 |

三次 SG/操作语义/CFG 序列化摘要均与旧实现一致。这是对同一个 154 行文件的
局部测量，不能外推为整库或 LeWM 运行加速。旧完整分析被中止，不能把 919.862
与 401.595 当作两个已完成运行的 A/B 加速比。

## 6. 状态与下一步

- **Implemented / Verified（有限测试范围）**：自动源码候选清单、接口/覆盖、
  批量核心 body 尝试、条件调用见证和严格持久化重放入口。
- **Observed / Verified（本门范围）**：上述外部清单、成本、当前源码重放和
  未修改核验，见 `n2b0-efficient-lewm-receipt.json`；压缩清单也随报告归档。
- **Inferred**：本地 import/call 候选，不升级为运行可达或已确认 callee。
- **Proposed**：运行加载证据回接入口范围、入口/use 引导的展开预算、签名接口
  分离，继而实施 [N2B1_PLAN.md](N2B1_PLAN.md) 的循环/绑定规则和细粒度状态。
- **未成立**：完整 LeWM 程序图、消费者/效果闭包、具体合法化简指导及加速。

原始执行和 NO-OP 仍保留。本门没有新增 detector/backend、修改 LeWM 或选择
任何 LeWM 变换。详细自动化要求和下一阶段验收见
[AUTOMATION_PROGRESS.md](AUTOMATION_PROGRESS.md)。
