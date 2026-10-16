# B1修复门：有界调用窗口证据

日期：2026-10-16。状态：**有限实现与363项组件门通过；新全仓/GPU/LeWM门未完成**。
基线实现`c91876b`，源指纹
`33d92b1635ac614ab817388dbeb45cda5fe6f71a6af99b115193e473582d1933`。
本门解决真实输入暴露的采集规模问题，不新增detector/backend，不更改LeWM。

## 1. 已测事实与失败

- 冻结组件304项、全仓2,535项通过；独立CUDA/autograd原程序的公开查询通过。
- 未修改LeWM原成功命令新运行exit0、success_rate=100.0，插桩wall302.111秒。
  base保留168,626事件/84,313入口/850 code，零drop/error/path gap。
- sidecar保留2,000,000事件，其中1,996,176条指令，768,801,553字节，drop1。
  最后记录仍在数据集构造的一处内联列表推导；当时base水印约3,200。
  因而该profile没有覆盖随后真实规划器执行，不满足B1实际采集门。
- **Inferred**：当前route builder按process级丢失拒绝其所有attempt。
  未为已知失败的2M事件再执行昂贵route重建，不能把该推断称作测得路线计数。
- 原始call文件929,747,206字节已无损压缩到32,886,570字节，逐文件校验
  decoded SHA/bytes后删除本次拥有的plain副本。原程序Git及tracked Python未变。

## 2. 模型对应与职责

Operation/Value/StateLocation/Region及其源码依赖图继续表达程序结构。
Execution evidence是面向具体查询的观察投影，不要求每次循环都序列化每条指令。
本门投影只支持已声明的参数来源查询；省略的操作、状态及控制依赖仍存在。
缺少其动态记录不支持dead work、无副作用、全程序覆盖或TRANSFORM结论。

既有`CPYTHON_LOAD_OCCURRENCES_V1`是逐指令profile，原raw和report算法保留。
新增规则设计为`CPYTHON_CALL_WINDOWS_V1`，使用显式metadata.rule及CLI模式分派。
相同数据类不意味着相同观察范围；旧report不能悄悄改按新规则重建。

## 3. 审查后规则

1. 由当前完整CodeType自动分析每个CALL；保留其完整、物理相邻的
   LOAD/PUSH_NULL/NOP→CALL窗口，而非任意LOAD子序列。继续记录每个必要LOAD
   的有序suboperand与CALL INSTRUCTION、真实CALL_ATTEMPT/ENTRY_HANDSHAKE。
2. 窗口内部不能有jump target或exception-handler入口；首offset允许多入口。
   offline必须从准确descriptor对应的源码独立重建并核对该条件。
   已有Name/位置参数、flags、epoch、previous-attempt和实际entry约束继续适用。
3. 非窗口指令可停止逐次回调，依据本机CPython对local INSTRUCTION的DISABLE
   行为实测。不得调用影响其它工具的全局restart_events；退出只释放自己的tool。
   本机fresh-process探针发现，frame退出置0再重设mask会恢复禁用位置。
   新profile因此在每个CodeType存活期只安装一次，返回后保留到stop；安装表使用
   有界weak引用及对象identity，不能按共享code descriptor合并不同CodeType实例。
   旧profile的逐frame生命周期保持原样。
4. 失效观察点不能因首次无pending就永久关闭。保留CALL正常continuation及必要
   异常handler入口，用于在caller恢复后取消尚未进入的attempt；需由collector与
   reader协议共同检查。任何不完整执行片段都不能拼出新的完整参数来源。
5. hook缺口、预算超限、未知code/namespace/layout继续明确拒绝；profile只缩小
   观察范围，不改变authority或内容/环境/状态的证明强度。

规则依据：[CPython monitoring文档](https://docs.python.org/3.14/library/sys.monitoring.html#disabling-events)。
在线页当前3.14.8；所有本机探针与验收必须记录实际3.14.7，不能宣称跨版本通用。

## 4. 自主验收节点

| 门 | 必须证明 | 反例 |
| --- | --- | --- |
| W0设计与探针 | DISABLE实际作用域、重复invocation和tool恢复；独立审查窗口连续性与expiry | 干扰其它tool、重启全部事件、关闭必要失效观察点 |
| W1通用程序 | 大型无调用循环后仍有完整多层参数查询；事件/回调规模受静态位置与真实CALL约束 | 两次调用、shared参数、循环重入、分支/异常进入窗口内部、悬挂attempt |
| W2历史重放 | c91876b真实GPU归档与旧v1报告由公共CLI完整重建；新profile篡改拒绝 | 伪造profile/源码/offset/条件、把稀疏视作全量 |
| W3冻结回归 | 映射准则、必要全仓、独立GPU/autograd均通过且源指纹不变 | 未支持情形留下错误completion或绕过预算 |
| W4真实LeWM | 原命令新capture无drop；自动inventory/link/公开重放与查询，逐项记录真实闭合链/断点 | 手工函数名单、手工图、业务名称规则；将条件路线说成获批优化 |

W4保持完整要求；小程序通过不能替代原LeWM。每门保存失败和通过证据、源指纹、
原始输入及manifest，提交推送后继续。没有可信LeWM加速比，B1尚未整体验收。

## 5. 当前已验收与仍未完成

冻结组件`N2-CALL-WINDOWS-B1-COMPONENT`：363项通过，73.446秒；测试期间源指纹
`38dfe6c34545b405fa5e8f08e2828f7357c862527500a6a1f2b3d97072796574`未变。
门逐项覆盖新collector的静态窗口与mask生命周期、按PID版本化协议、来源规则、
公开大型循环后查询、独立预算及旧frame/source回归。旧8项条件/所有authority保持。
这只证明已支持的引用来源投影；大型循环后的查询通过**不证明循环体已被lower为
完整core图**。模型的自动控制/loop-carried状态、alias、细版本与GPU依赖仍未闭合。

源码审查发现并修复：未知offset不能静默DISABLE；静态反汇编要逐项有界；
所有CodeType实例的disabled-offset记账要有总上限；已知foreign tool/mask干预后
不能返回DISABLE或部分清理；stop/fork释放前先核对全部自有配置。
源码完整scope及公共旧归档、独立GPU、新LeWM重试仍按W2—W4要求继续验收。
原c91876b的2,535全仓及GPU结果不能替代本次新指纹的完整验证。
