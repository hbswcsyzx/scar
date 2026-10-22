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

## 真实LeWM验收

`run.sh`采用原成功入口、同一已入库的真实calls trace和原256body/10,000operation
预算，仅增加显式structured profile，输出到新目录；不执行或修改LeWM。
以最终`inventory.json.gz`和独立审核为实测依据。运行未完成前不预填提升数。
若实际仅小幅增加body，必须直接报告剩余拒绝原因，不能把接线成功当完整模型。

## 明确未完成

这次接线不改变structured lowerer的unsupported整body回滚。BoolOp/IfExp、
expanded calls、heap/destructuring写与函数环境等仍可阻断；预算未尝试与未建
class/lambda/comprehension接口另列。下一项按真实新结果排序，不能单纯加预算
或把opaque重标为pure。实际Uses/状态/逻辑来源、资源身份/生命周期和输出因果
闭包仍是第一阶段必需项，不自动转入化简或性能A/B。
