# C2F：当前body入口的outcome frontier

2026-10-18；基线`012db08`。查询已实施，7项新定向测试、517项组件与冻结
`9f3d7e7`的3,549项全仓通过；**静态派生查询组件已验收。** 这是
[driver复审](M1_DRIVER_INTERFACES.md)确定的必要派生关系，完整driver字段仍开放。

## 模型含义

一次实际body入口由原entry或特定Suspend case的landing描述。该次执行可能停在
某个Suspend/Return/Raise；下一次temporal恢复属于另一入口，不能放进本次结果。
因此整个Region的exit清单或所有终端集合不能代替source-relative查询。

```text
entry → Suspend A ───→ driver
          ⋮ temporal
landing A → ordinary CFG → Suspend B ───→ driver
                              ⋮ temporal
landing B → ordinary CFG → Return
```

三个入口的frontier分别是A、B、Return。branch/INVOKE/C0/C1路线全部保守遍历，
在第一次terminal停止，不跨temporal边；循环有限遍历但不声称动态必终止。
这定义的是声明图的结构可达性，不执行分支条件、不证明runtime选择或源语义。

## 公共查询合同

已实施`ProgramIndex.body_outcomes(region_id, start=None)`：

- region与start用准确typed ID；已知但未声明resumable body返回None，表示无声明。
- start省略选body entry；显式值仅接受该body的entry或真实resume landing。
  未知端点/跨body/普通内部block不能冒充入口。
- 返回派生`BodyOutcomeSite(operation, kind, values)`元组，稳定ID顺序不代表执行顺序。
- values复用规范UseSite。Suspend只取exported和handoff states，排除saved private值；
  Return/Raise只取自己的terminal values。不改变producer或新增ExitPort。
- 空元组表示该声明入口没有结构可达的这些终端，不等于无effects或dead work；
  非空也不证明全部路径完成。查询不授权transform或真实driver执行。

共享纯派生函数由同一body/CFG得出OperationID结果，未来driver validator复用它；
不维护第二份可写控制图/outcome表。ProgramIndex仍先完整validate供给的图。

## 自主验收与边界

当前设计probe先用已有合法IR验证8个CFG入口/无完成情形，另一个检查仅是driver
额外域的签名设计；不是9个driver产品测试。实施后的组件门必须另有真实API测试：
首Suspend、两种resume、两cut、branch/循环、C1/INVOKE、空frontier、规范Use和
错入口，以及原body/wire/query回归。随后冻结实现后只跑一次完整回归并归档。

不新增wire capability、detector/backend、source lowerer或runtime claims；不把此
派生组件当完整C2D或M0–M2完成。不因已有3,542项旧回归就宣布新查询通过。

## 当前验收进度

新7项API测试覆盖上述入口、载荷、循环、C1/INVOKE和错误端点；完整组件门为
517项 / 7.384s，9项标准全部PASS，406个源文件哈希前后相同。
源指纹：`2407cdea2418e8f9dc023ef8ab37709f1172a11bd75b4b134bcbb5ff69a58f84`。
首个定向运行曾因手工fixture漏传world而被core正确拒绝，原日志保留；没有将
它算作产品误判或修改core绕过。共享helper只读每个block的最终terminator，
不扫描Tensor内容或维护第二份图。

组件报告：`artifacts/experiments/b1_call_operands/model_driver_interfaces/component/final.json`。
冻结实现`9f3d7e796f2fb975528b123d009f1dacb84602ba`的完整回归3,549项PASS、
零失败/错误/跳过，三条既有warnings。单次运行433.223s、峰值1,030,428KiB；
HEAD/clean/406源文件与26份fixture哈希前后完全相同，只清理自己basetemp。
这些时间是验收成本，不是workload性能。完整证据与核验脚本见
[归档](../artifacts/experiments/b1_call_operands/model_driver_interfaces/README.md)。
完整driver、source/runtime对应和第一阶段都不属于本组件已完成的范围。
