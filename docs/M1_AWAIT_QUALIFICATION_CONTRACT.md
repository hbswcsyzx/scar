# 精确资格检查：静态可行性与实际选择

2026-10-19；基线2fc9571。原D0/D1/D2字节不改；本补充针对D1“合法失败不得
整体拒绝”与旧显式检查负例的解释冲突，不缩完整A–H/16/P5/M2分母。

## 一、实际证据与决定

`model_await_outcomes/first-failure-paths/` 为761源码稳定指纹
`8c784e9e1c4b3fadab3e17d251947faca8c1c297a587a493185001066b7d97a5`，2P/4F。
两F是新测试API错误；另两F在快照前就被静态资格拒绝。该Program与上一门的
显式qualification GENCORO负图相同，仅新capture选择真实false→TypeError。
这是合同/oracle冲突的实证，不冒称“新的不同图已复现旧产品错误”。原native12
语言证据与本轮A/B独立只读审查一致：带准确检查的完整Python CFG要能保两腿。

**D3_FROZEN**：原typed `AwaitIteratorQualification` 是一个固定条件检查。
同准确输入已知不合格时，接受腿在该声明合同条件下不可行；它在静态CFG中
存在不使整个Program无效。实际捕获选中这条接受腿才是声明合同矛盾。
静态Program有效性不随一次capture选择改变。无检查/绕过检查继续使用坏候选
仍拒绝；未知类型不能推不可达；native/source/runtime/value/transform权限仍False。

## 二、不新增实体或wire

Operation/Value/StateLocation/Region/Resource及Program23/Execution8不变。
约束从原独立expected、input、own bool/N-R、branch及polarity派生为查询视图；
不是新producer、state版本、可写phase或控制边。原来源和接受/拒绝分支仍完整保留。

局部qualification视图增加 `feasibility`：

```text
record / source / accepting_edge / bool_binding
cases: (source_case, accepts: True | False | None, reason)
acceptance: True | False | None
known_inventory_complete / conditions / flags
```

每case按原来源/tuple求值。普通GENERATOR为可接受iterator；COROUTINE、
GENERATOR_COROUTINE、ASYNC_GENERATOR、已知非iterator为不合格；外部/opaque/
不完整来源为None。结论仅在该固定native检查及来源声明成立的条件下适用。
mixed来源保逐case结论，不能ANY代替全分母。bool own result的已知literal若与
此结论矛盾仍须报错；普通检查自身RAISE不自动认证其packet种类。

## 三、只有准确受保护路径可以替代旧硬拒绝

检查candidate必须与独立expected绑定；own bool必须进入原branch。接受端口→
本次成功返回→准确advance须为同candidate/caller/guards/current整条原路径。
原接受边必须控制所声称的成功出口；仅可达或存在某个qualifier不能提供豁免。
直接同region推进按原CFG检查；跨parent/callee只沿准确ExpandedAwaitCallee及
原调用返回端口，不扫旁支check。绕过检查、旧bool、别的来源/caller保原拒绝或
准确未证，不据实际Drive反选expected。

不合格case仍列原jobs，注明 `INFEASIBLE_UNDER_DECLARED_QUALIFICATION` 或
逐case条件；不删除source/N-R/consumer分母。来源未证不能推不可行。

## 四、实际选择与缺采

Execution视图在同一个shared budget/context中枚举原qualification站点与其实际
occurrences。候选来自本次input Use；类型来源只取独立声明/准确原Create lineage。
bool接受由其own result→同activation原branch/actual transfer确定；INVOKE按自身
准确NORMAL/RAISE。缺输入/branch/transfer/来源保持具体gap和原未查计数，不能猜。
已知坏候选实际选择接受，产生 `await_qualification_acceptance` 矛盾；实际拒绝
仍须核其原packet/state/consumer，不因本条规则自动证明TypeError或合法性。

## 五、明确旧负例迁移与验收

原 `test_general_await_known_generator_coroutine_cannot_continue_as_iterator`
的原失败与字节保存在2fc9571及旧归档。保其caseID与“坏返回无合法检查不能继续”
义务，输入改为移除typed qualification的准确语义附件/展开ref及该row消费者；
原candidate/正常CFG/实际advance均不删，旧legacy拒绝仍须出现。该唯一旧测试
的输入迁移必须逐字节登记，不能宣称本轮全部旧tests字节不变。

另增独立正反例：qualified完整静态图有效；实际reject合法；实际accept矛盾；
无typed检查仍拒；错bool/错candidate/旁支或绕过检查不能豁免。原classify/direct/
wrapper规则不因此放宽。先保存真实首红与迁移说明，再实现公共查询，作者冻结后
root串行受影响回归。此补充不是最终outcome/consumer闭合或整门通过声明。
