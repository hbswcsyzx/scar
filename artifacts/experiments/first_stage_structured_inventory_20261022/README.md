# 第一阶段：既有 structured 前端接入公共程序库存

日期：2026-10-22。完整程序建模仍 OPEN。本项没有增加优化规则、backend或化简。

## 具体断点与模型决定

现有source lowerer已能表达局部绑定、if/while/for、零次迭代、break/continue/else，
但公共inventory只接受BOUND_FRAME，丢弃`LoweredSourceBody.structured`；单独的
model-program支持不等于实际入口能自动恢复它们。现在复用同一lowerer、预算、
调用来源队列、BodyEntryInterface、StructuredBodyModel与canonical ProgramGraph。
不新建producer/CFG，不伪造FrameModel，不根据LeWM函数名决定建模。

显式`inventory-program --body-profile structured`输出`scar.program-inventory` v7。
它保存一份对应每个成功body的typed structured overlay，核definition/root/
interface/source；失败body不留悬挂overlay。静态、旧RuntimeScope、真实calls三条
路径都按相同profile独立重放。旧1–6字段、默认frame和算法保持原样。
新profile的coverage只按准确metadata source atom链接提升已连接构造，不能将
整个body的源码范围涂成CONNECTED。source-layers只新增对7的header支持，仍不
以留存三图证明全部库存声明。

## 已实际通过的测试

conda lewm / Python3.14.7。root运行以下相关选择：

```text
tests/unit/test_inventory_structured_profile.py
tests/integration/test_inventory_structured_cli.py
tests/unit/test_frame_inventory.py
tests/unit/test_call_source_inventory.py
tests/unit/test_call_demand_schedule.py
tests/integration/test_program_inventory_cli.py
66 passed in 37.47s
```

包括三种新profile入口、旧v5/v6重放、成功body/typed overlay逐一对应、失败body无
overlay、缺少/重复/错root/错profile/类型/authority/删protocol篡改、独立预算、
准确循环source links及非执行哨兵。测试结果不表示LeWM完整建模通过。

## 真实LeWM结果（Observed / Verified，完整阶段仍OPEN）

`run.sh`采用原成功入口、同一已入库的真实calls trace和原256body/10,000operation
预算，仅增加显式structured profile，输出到新目录；不执行或修改LeWM。
实现`1bfbcca`，exit0，wall630.86s、peak374,572KiB；这是分析成本，不是LeWM
性能或加速比。独立标准库`compare_inventory.py`实测exit0、wall4.22s，证明输入
source snapshot/三图context、discovery、raw calls和预算与旧baseline完全相同，
重计body/coverage并核每份typed overlay的definition/root/interface/source及protocol
引用。它不证明全部依赖/状态语义；报告`comparison.json`明确该边界。

| 同范围、同预算 | 旧FRAME baseline | 公共STRUCTURED |
| --- | ---: | ---: |
| 文件 /定义 /原调用 /source atom | 151 /2,217 /10,235 /122,323 | 相同 |
| 带缺口的局部body图 | 50 | **51** |
| UNSUPPORTED /NOT_ATTEMPTED | 206 /1,961 | **205 /1,961** |
| code/source组CORE_LINKED | 32 /425 | **33 /425** |
| core operations /values | 1,148 /1,919 | 1,486 /2,283 |
| 准确source atom链接CONNECTED | 682 | 697 |
| construction预算收费 /10,000 | 3,503 | 5,592 |

新产物有51份typed structured model、481条语言protocol、一处loop。唯一新保留的
body在外部testcase的`stable_worldmodel/utils.py::get_in`；SCAR未按该名字分支。
新增图不等于完整效果或资源模型；全程序、运行可达、细状态和变换授权仍false。

### 为什么提升很小

205个失败body的原metadata逐项保留。独立比较统计首个终止缺口：45个closure cell
环境接口、41个heap/global/destructuring写、15个expanded Call、13个BoolOp、8个
IfExp、9个Dict、7个Subscript及其它声明/异常/注解/格式化/映射缺口。它们会清空
同body里原本已恢复的Call/Use。1,961个未尝试项仍另列，不归入这205个失败。
**剩余4,408 operation预算而仍失败，不能用继续加预算代替协议恢复。**

`replay.sh`使用公开`check-inventory`按原raw/source重建v7并逐文档比较；这是与
上述独立重计不同的验收。现已实际**REPLAYED**，exit0、wall645.19s、peak907,624KiB，
stderr为空。源码准备151次、每文件最多1次，raw/source/profile/预算、图、overlay、
覆盖及摘要完全匹配。`replay.*`保留完整命令、实现SHA与原始输出。这只证明该
有界模型可重建，不证明缺失的程序/资源依赖已恢复，也不是LeWM加速比。

## 明确未完成

这次接线不改变structured lowerer的unsupported整body回滚。BoolOp/IfExp、
expanded calls、heap/destructuring写与函数环境等仍可阻断；预算未尝试与未建
class/lambda/comprehension接口另列。下一项按真实新结果排序，不能单纯加预算
或把opaque重标为pure。实际Uses/状态/逻辑来源、资源身份/生命周期和输出因果
闭包仍是第一阶段必需项，不自动转入化简或性能A/B。

下一实施项须按本次真实阻塞排序，并先审查现有环境接口的复用。若补条件表达式，
必须区分取值与条件上下文：and/or返回选中对象，未选分支不执行，不能多测一次
有副作用的`__bool__`；每次truth/子调用的失败后态与引用hold/release关系须保留。
只画短路形状或以纯布尔真值表验收不够。新source规则须与旧V1重放隔离；当前
不提前实施又一个分支，也不把第一阶段拆成无尽的手写协议测试。
