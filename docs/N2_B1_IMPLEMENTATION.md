# B1：原始程序到跨层参数与返回查询

日期：2026-10-16。状态：**Implemented，组件验收通过；B1端到端验收未完成**。
前置主线 `6a7410d`，R1已验收；本门不替代环境、状态、控制路径及完整程序门。

## 1. 交付要求保持不变

输入原始程序命令/入口与预算，自动采集、发现源码、建立core和公开查询。
不提供函数名单、人工纯性、常量表或手工workload图。正例必须穿过具体caller Use、
actual occurrence、callee formal、return，再回到同一次caller result及准确上层输入。
同一次`choose(x,x)`的两个参数保留不同Use/occurrence，不能按引用相同挑来源。

结构实体仍是Operation/Value/StateLocation/Region；此次接通Region的调用接口。
它是有条件的引用来源，不证明内容、函数环境、world状态或效果等价。

## 2. 实现分工与接口

| 部分 | 实现 | 依据 |
| --- | --- | --- |
| 真实采集 | `scar.trace.call_operands`与版本化LOAD解析 | pre-load、CALL当前callable/layout、原v1 entry握手；metadata-only |
| 有界协议 | `scar.ir.program.call_operands`、`scar.analysis.call_operand_reader` | 独立原始锚点、manifest、计数、预算、PID/TID、水印和gap |
| 跨层路线 | `scar.ir.program.call_operand_routes`、`scar.analysis.call_operand_routes` | actual位置→formal，唯一attempt→entry→NORMAL返回；薄core模板 |
| 公共报告 | `scar.analysis.call_operands`、CLI | 当前raw/source/inventory完整重建与canonical比较，严格预算先于外部输入I/O |

新采集附加sidecar，旧v1事件格式和报告规则保留。旧link-calls仍使用原v4/v5和
LEGACY匹配；新私有组合路径显式接bound-frame v5/v6与RECORDED profile。
生产reader只扫描原始frame流一次，内部组合复用其本地结果，不接受serialized
trusted标志。报告不复制全部指令或每invocation的完整core图。

调用者的base entry与sidecar握手在同一recorder锁内执行；monitoring callback
也先取同一锁，保持跨线程水印和sidecar顺序一致。不能把entry_index当InvocationID。
停止时先关闭monitor，再关闭base并写sidecar metadata绑定全部原始文件。

## 3. 通用命令

```bash
scar trace --call-operands --project-root /path/project --out /path/trace -- python /path/project/entry.py
scar inventory-program /path/project/entry.py --project-root /path/project --calls /path/trace --out inventory.json.gz
scar link-operands /path/trace --project-root /path/project --inventory inventory.json.gz --out operands.json.gz
scar check-operand-links operands.json.gz
scar query-operand-refs operands.json.gz --process PID --thread TID --invocation INVOCATION
```

`--call-operands`包含calls-only，不启动Torch hooks，不保存Tensor值或长期持有应用
对象。capture与独立reader/route/report各有预算，不能由输入报告提高验证上限。
当前capture规则针对本机CPython3.14；它没有宣称所有Python实现都支持相同字节码。

## 4. 实际开发检查与发现

以下是非联合冻结的定向结果，不冒充最终B1验收：

- 原有frame/source链接与历史reader回归47项通过。
- 新records/reader180项通过，包含真实fresh-process两文件动态import/shared参数采集。
  人工协议反例不作为源码自动建图正例。
- 首轮公共CLI集成30项通过：distinct/shared/非weak shared原始程序自动v6构图、
  多层查询回到唯一run.x、位置/condition篡改、独立预算先于missing inventory I/O、
  hardlink输出保护。首次fixture错误把typed ID dict当字符串key；修正测试读取wire，
  未放宽产品对应。
- 独立审查复现分支合流误连：实际返回x，查询却把静态phi两侧x/y都当本次来源。
  已增加CONTROL_SELECTION_UNVERIFIED边界；不同SSA来源合流在没有动态选择证据时
  停止，全部相同SSA来源保留共同引用。同对象不能代替控制路径证明。
- 发现新completion早于LOAD/gap检查发布；已移至整条narrow规则验证后，与参数路线
  原子计费。known hook gap、缺LOAD、raw Method和布局矛盾不会残留completion。
- collector审查修复完整namespace扫描、恶意key用户协议、正常停止tool释放，以及
  动态CodeType clone的计划缓存/工作预算；具体正反例进入其定向测试。

CALL观察到归一化的FunctionType不改标为MethodType。属性调用由未支持的LOAD_ATTR
窗口停边；Name-bound method保留pre-load真实MethodType与CALL归一化两份不同事实。

## 5. 联合自主验收顺序

冻结组件门 `N2-CALL-OPERANDS-B1-COMPONENT`：**304项通过**，52.893秒，
测试期间实现指纹未变。源指纹：
`33d92b1635ac614ab817388dbeb45cda5fe6f71a6af99b115193e473582d1933`。
六组准则逐项映射到协议/reader、collector、位置路由与控制边界、公开CLI、
inventory独立输入预算及旧frame/source回归。报告在
`artifacts/reports/gates/n2-call-operands-b1-component-20261016.{json,md}`。
这不是全仓回归或B1端到端通过；以下外部GPU与原LeWM门仍待完成。

1. 完成独立review并冻结所有实现，记录源指纹；所有已知反例必须纳入门。
2. 运行映射门与必要全仓回归；公开原始程序正例须真正查询准确上层Use。
3. 保留一个独立公共程序的原始输入/证据/报告；验证PyTorch GPU Tensor输入及
   autograd状态，不把引用来源成功说成Tensor内容/效果证明。
4. 对未修改LeWM原成功命令做受预算限制的新capture/自动分析压力测试，记录
   实际覆盖、路线数及每类断点。不得手工补图，不能把缺口改成成功或TRANSFORM。
5. 保存失败/通过报告与证据manifest，自行验收、版本提交并推送。

## 6. 后续仍需完成

实际receiver/default/pack绑定、函数环境、跨调用world后态、动态控制选择、
loop-carried依赖、细粒度状态/alias/provenance，随后才是观察根闭包和具体化简指导。
分支、循环或效果未知的记录不能被直线引用查询覆盖。尚无可信LeWM加速比。
