# F19完整异步关闭链：限定结构验收

状态：**Verified，限定于所供模型结构**。root自主验收，无需用户逐门批准。
基线`c02e973`；最终922输入指纹`d5d8919d624b2845f3d30d3023ae646d25a213d2c463286b1773e2f136f66edf`，两次运行前后稳定。

## 实测与原单位

| 冻结运行 | 实际结果 | wrapper秒数 |
| --- | --- | --- |
| verified-new | 30 PASS，0失败/跳过 | 357.117132 |
| verified-regression | 26模块302 PASS，0失败/跳过 | 571.604609 |

这是两次同源码focused运行的332项并集，不是一次full suite或LeWM benchmark。

| 原F19完整单位 | 本次证据 |
| --- | --- |
| 真Return/Raise→F→新Throw/Close | 四格公开history、准确own N/R、caller当前state；删身份回到None；sameR retry独立 |
| graceful close | GE进入真实finally/C1→AWAIT/HOLD→同R/本次S恢复；Return/GE/普通异常三出口及两层回复 |
| illegal close-yield | 构造错误前R COMPLETE而B仍Suspend；六driver调用/三body段/五Create；sameR拒绝、新Close/Throw无Drive、同B NEXT恢复finally→真实F |
| 交叉义务 | 错HOLD/提前release拒绝；删adapter/绑定保原源分母；错matcher/bool、构造来源缺证；缺input/bool/packet/body outcome不借完整兄弟；tiny保hosts/ports/cursor |

每个actual stage额外核准确RequestCreate ownN→本call request；resume/NEXT送值核
当次caller sent→实际Drive输入。真正terminal后的窄release不宣称物理free。

## 模型改变

- Implemented：三处统一ASYNC_YIELD→COMPLETE；AWAIT仍HOLD，F仍仅由真Return/Raise。
- Implemented：原packet→matcher/bool/True边→fresh constructor/own N/R→packet/host的
  有界派生收据。每段copy独立核；新旧packet不union，旧CLOSE输入合同不变。
- Verified：公开静态`handled_completion`及既有dynamic drive查询接通准确原ports/
  actual occurrences；来源缺采、重复site、预算截断不升级True。
- Rejected：准备期免费另开百万预算、按操作名推异常类别、用fresh packet非copy
  直接判错、缺独立期望却伪造known contradiction、删denotation后仍要求终结证明。

所有新派生工作在query shared预算；INVOKE全槽、adapter、原route、绑定扫描计费。
不跨query缓存证明。已知False在缺constructor或截断后仍保留；未查部分不授True。

## 证据与版本边界

保留全部首败源码/JUnit/日志。独立审查见归档`independent-review.json`：A确认最后
槽扫描费用阻断关闭，以最终新/旧运行通过为接受条件；B/C原审查与修正逐项保留。
Program27/Execution8、原copy语义及所有既有tests/fixtures字节保持。

原已知focused目录2325义务全部保留，本次重验其中249；
新增30项，另发现53个既有目录外义务，当前已知目录2408。
未重跑整个目录或整个仓库。两次运行都不是P4组件/full或P5/M2验收。

Observed：本次是所供图与capture测试；旧CPython3.14.7固定源码、22调用和两编译
观察复用，本次native目标执行0次。初始S=None与未选ITER边界保持；不宣称完整
native driver。source/native/runtime identity、自动whole-LeWM恢复及变换权限未证。
没有新增detector/backend，没有新的LeWM优化或加速比。

## 合账与下一阶段

F19在上述条件下限定接受：原16行目前10接受、6开放；await A–H已有结论保持。
仍开放F20/F22/F24/X25/X26/X27、P4 component/frozen-full、P5，以及M2原113构造/
196字段。**整个第一阶段尚未完成。**

下一门按[M1_YIELD_FROM_INITIAL_PLAN.md](M1_YIELD_FROM_INITIAL_PLAN.md)先做F20同一
父实例首次委托的六路，复用现core、原InitialAdvance和consumer ledger；合法
完整图出现真实查询反例后才决定薄产品修正，不新增来源工具箱或优化后端。
