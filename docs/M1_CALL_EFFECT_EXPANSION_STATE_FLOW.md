# 本门发现的普通 CALL 当前状态缺口

本补充在 `interval-before.json` 及 `flow.py` 实际代码审读后、修复之前冻结。
它属于原“同一对象不同状态版本、准确调用后状态”的建模义务，不增加优化后端。

原静态校验器 `program/validation.py` 对普通 CALL 的 StateVersionValue 结果会更新
`current[value.location]`。动态 `execution/flow.py::derive_flow` 则只把结果写入
value environment，再更新 StateAccess.after；普通 CALL 没有普通 StateAccess，
因而漏掉这些状态结果，后续 `state_at` 仍可能指向调用前版本。

真实 `interval-before.json` 中普通 CALL 出现
`state_preservation_state_missing: state input is not established at this exact program point`，
而原 call1 state result→call2 state Use 的实际值路由完整。这是当前状态派生缺口，
不能由“完整效果展开”关系绕过或用旧版本当作当前状态。

修复要求：

- 仅按原普通 CALL 的原 StateVersionValue 结果更新动态 state 与 state_definitions。
- 当前值来自该 operation occurrence 的实际结果，不推内容相等、alias 或保持关系。
- 结果未捕获时当前状态必须变成 Unknown/None，不能沿用先前版本。
- INVOKE/BodyDrive 继续只在各自实际完成 EDGE 有状态，不创造共同 AFTER。
- 在原 NEW 普通 CALL 节点中，先核 call1 AFTER / call2 BEFORE 与真实 state result，
  再核区间；同时核 call2 future results 缺采时 AFTER 为 None。节点身份不变。

因此本门明确增加一个旧产品允许路径 `scar/ir/execution/flow.py`。
旧测试/fixture 仍受原字节保护；完整相关回归必须覆盖 flow、call query/validation、
原 state preservation/history 和本门新区间。原摘要/alias/opaque 阻断不得借此消失。
该修复记录为建模缺陷修复，不作为 LeWM 性能优化或加速证据。
