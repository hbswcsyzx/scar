# N2.schedule 自主验收：全局需求与单根构图

日期：2026-10-15。状态：**PASS_BOUNDED_GLOBAL_DEMAND_SCHEDULE**。
D1–D5 有限门通过；父N2和完整优化系统尚未完成。

冻结实现 `994f9443b102787cd3d067ce5a5a1e99143f8729`，干净工作树启动。
实现/测试/gate 联合 SHA256：
`a7a9fd431765e5edffa840aab82d555d20ec66d315c068c6a0f4c92b6cda1073`。
设计与验收门见 [N2_SCHEDULING_PLAN.md](N2_SCHEDULING_PLAN.md)。

## 1. 模型和职责

Program 的 Operation / Value / StateLocation / Region 未被改成分析任务。
新增 typed `expansion` 描述 SCAR 如何花费构图预算：观察来源候选、条件调用
候选、剩余定义，逐任务记录来源/调用锚点、是否尝试、状态和构造/收费操作数。
这些是分析工作和证据，不是实际 callee、纯性或优化审批。

新流程先索引全部发现文件，再由全局队列安排 body；每次 lower 只构造当前
root，条件目标通过队列去重展开。调用见证也按需求分配；未需求 owner 的
调用直到最终汇总才使用剩余额度。独立 body 不被自动拼成完整程序图。

重量上下文每文件完整 prepare 一次。进程自建、结束即删除的私有 scratch
有128,000,000压缩写入字节和64,000,000单记录原始字节上限；文件0600、目录
0700。输入报告不能指定pickle或scratch路径。恢复前校验自己的压缩摘要，
从封存text重建symtable，不重新读取已变化源码。不可用上下文保留轻量索引。

同时驻留一个重量上下文；动态交替依赖允许多次恢复，同一文件没有固定三次
上限。CLI另报typed分析测量，语义报告不把随机临时路径/物理压缩字节量作为
身份。该测量属于SCAR，不是LeWM内存/传输数据。

## 2. 冻结门与历史兼容

| 自验 | 实测结果 |
| --- | --- |
| mapped gate | **457 passed**，18项标准全部通过 |
| 全仓回归 | **1,505 passed**，2条已有warning，无失败/跳过；wrapper126.636秒 |
| 旧包独立生成 v2 | 从 Git `b886e40` 实际包导出，在隔离临时目录运行原CLI生成报告；0.672秒 |
| 当前版本公共CLI重放旧报告 | exit0；0.446秒，保留旧root包含候选body的原图，不改写为v3单根策略 |

历史小程序只有合成来源观察，不执行target；兼容检查只支持此fixture范围。
新CLI有trace默认v3并保存expansion；无trace维持v1；旧v2走原调度重放。
两个context预算均有独立验证器上限，报告不能自行提高。公共trace/gzip/输入
覆盖保护以及v1源码路径继续在门内验证。

通用端到端检查包含：前文件40个unused不饿死后文件观察函数；交换文件排序；
同文件隐藏候选不能抢另一个观察root的操作预算；观察caller的条件helper
优先；同一定义去重；失败/回滚不退款；未知构造失败扣完剩余操作额度并声明
精确成本未知；后次恢复失败保留已成功core连接；封存源码与磁盘漂移分离；
source/trace/ledger/预算篡改拒绝。fixture不按LeWM名称决定规则。

## 3. 失败、修复与接受的限制

- 开发兼容检查出现4个失败：3个旧CLI测试仍预期schema2，1个仍向已不使用的
  `.run`入口注入失败。按schema迁移和新的index失败阶段更新，修复后35项通过。
- 独立审查发现见证预算仍可被未观察调用先占用。跨文件和构图后才出现的同
  文件目标均有反例。共享lazy linker已修复；link/admit/finish共同计费，不让
  后续无关见证覆盖已需求目标。5项独立检查最终全部通过。
- 最初建议的每文件两三次恢复上界不成立：两文件交替20任务需5+5次恢复。
  接受当前保守边界：每文件prepare=1，总恢复不超过已尝试任务数，重量上下文
  驻留1个。测试保留该成本，不用恰好容纳两文件的cache制造普遍常数保证。

开发JUnit、历史包兼容receipt、冻结gate、全仓JUnit和外部原始命令/时间均
单独归档。未因测试通过将UNKNOWN effects改成NONE，没有新backend。

## 4. 原始 LeWM 外部自验

使用与N2.entry相同的原始入口、项目范围、真实归档trace、文件预算256、body
预算256、构造操作预算10,000，不提供文件/函数名单。不重新执行LeWM。
外部生成exit0，耗时425.783秒、peak RSS331,492 KiB；严格重放exit0，
耗时450.457秒、peak RSS774,604 KiB。全部151个源码快照、归档trace和
LeWM HEAD/干净状态前后不变，分析实现fingerprint不变。LeWM保持
`f70fed80288462ca4d006cb3607ec6da6eaa851f`。

| 同一来源/预算的查询 | N2.entry | N2.schedule |
| --- | ---: | ---: |
| 发现文件 / 定义 / 源调用 | 151 / 2,217 / 10,235 | 相同 |
| 因预算未尝试的运行来源候选函数 | 27 | **0** |
| 上述27个候选本次状态 | NOT_ATTEMPTED | **3 LOWERED_WITH_GAPS / 24 UNSUPPORTED** |
| 来源定义到core Region连接 | 1 | **4** |
| 全部成功body（带缺口） | 41 | **26** |
| 全部body失败尝试 | 215 | **230** |
| 核心操作 / 构造收费 | 1,035 / 1,618 | **678 / 1,544** |

新增3个来源core连接来自自动索引中的 `MLP.forward`、`Embedder.forward`、
`FeedForward.forward`；这些名字只是外部结果展示，不进入规则。四个连接中
只有 `FeedForward.forward` 有精确code witness，另外3个为MISMATCH来源候选。
运行代码/定义匹配仍是34 VERIFIED、222 MISMATCH、6 MISSING、23 OUT_OF_SCOPE。
不能把4个结构连接写成4个已验证运行callee。

所有36个观察函数来源候选均被尝试，4个产生core、32个不支持；另有137个
class/lambda/comprehension接口缺口和83个非普通函数body索引。27个新尝试中的
24个阻断含16个签名接口、2个closure及写入/BoolOp/切片/推导式/raise/try。
256次尝试全局分为36观察、7条件调用需求、其余fallback；无上下文不可用，
无未知构造成本。所有task记录仍独立于实际执行可达性和优化许可。

本次SCAR分析测量：44次恢复，恢复压缩payload22,107,381字节，累计压缩写入
51,588,946字节，接受原始记录195,378,657字节。累计原始量不是同时占用内存，
恢复payload不是PCIe或物理磁盘读流量；scratch在阶段结束时删除。与上一版
402.571秒的单次分析相比，本次更慢约23秒，**未测得分析提速**；这里没有
clean重复基准，不推导稳定开销比，更不推导LeWM加速。

关键查询是上一版因预算未尝试的27个来源候选：这次确实被尝试，并分别列出
核心区域和签名/控制/状态阻断。核心连接、代码复现、效果和优化
仍是四个不同结论，不能用更多节点代替接口完整度。

机器记录前缀为 `artifacts/reports/gates/n2-schedule-*`；comparison脚本按
定义/快照连接前后报告，不按具体LeWM函数名选择结果。
`n2-schedule-acceptance.json` 汇总并核对冻结gate、全仓、历史包、外部receipt
及压缩证据SHA256。五份开发JUnit均经解压SHA核对归档，保留失败记录。

## 5. 下一门

本门完成后，继续 [N2_SIGNATURE_PLAN.md](N2_SIGNATURE_PLAN.md) 的
S1–S4：全种类bound formal接口、body与定义阶段分离、明确参数绑定状态。
之后补循环carry/零次/异常、细粒度状态与跨调用组合，才进入可核验子图化简。
完整LeWM自动模型、父N2、可信TRANSFORM和clean A/B加速仍未完成。
