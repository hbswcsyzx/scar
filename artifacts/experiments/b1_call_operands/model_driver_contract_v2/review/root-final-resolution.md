# D1连接合同终审决定

2026-10-18；只关闭字段设计/实施范围，不关闭产品D1、完整D0/D2/D3或M0–M2。

已逐条读取三个提案、两份提案补充、root core/gate/lifecycle有限审查及修正复核。
原报告均保持原样。最终采用 `docs/M1_DRIVER_CONTRACT_V2.md` 第1–3节与
`docs/M1_DRIVER_IMPLEMENTATION.md` 作为下一批代码依据。

## 已处理的实质问题

1. 取消可跨CFG保存/重用的permit，改用final gate INVOKE正常私有单操作landing。
   NORMAL/RAISE全driver域后态有真实producer；原角色经独立owned Uses转发。
2. 不强制通用RequestGate/U-A历史，也不强制一个独立AssociationRead site。
   当前R/B/S/session/continuation检查是已知DriverRule profile的NORMAL合同。
   早期真实acquire/lookup/helper不能删除；若有AssociationRead，校验其自己的规范
   输入/normal结果。缺来源不能授source/runtime证明；结构声明不是静态对象身份。
3. 固定入口角色must-copy、BODY/ASYNC的session差异、角色索引和Uses独立、Start无
   delivery、Resume按slot、outcome source与private landing均已明确。
4. Create是已绑定后的frame-create抽象primitive，不是Python源CALL；default/pack/
   环境等先有真实producer。多Create和外部instance允许声明同一body接口。
5. schema明确v11和七个table，旧v1–v10全部标记拒绝；不以多写record取代整条路径。
6. finite frontier不承诺totality，空frontier不伪造DIVERGE结果。原body CFG保留循环。

## 一项未采纳的审查建议

core报告建议 `lifecycle == derived region state domains`。root不采纳该等式：
lifecycle L是用途分区，driver全部state D还可能含环境/资源/调用者context等域，
强迫L=D会混淆作用范围。最终合同明确 `nonempty L subset D`，gate输入/两completion
覆盖D，body需要的域也为D子集。D由core entry唯一派生，不另存。实施正例必须含
L≠D，反例必须拒绝只更新L而漏掉D。此决定不减少任何gate后态检查。

## D2明确未通过

失败边也能触发session清理；普通finalizer unraisable与真正向外raise wrapper不同；
typed NoBodyFinish成功合同、终结锚/owner的逐边对应和重复引用放弃语义仍需冻结。
root正文第4节已标为D2候选，不能按草图直接发布。没有将这些问题转成UNKNOWN通过。

六项corridor设计检查通过只证明现core接线及专用约束需求；初稿枚举错误完整保留。
产品源/26份fixture保持原冻结指纹；没有新pytest/full/语言探针/LeWM/GPU。
本轮Verified是设计探针，Implemented仅指文档/计划收敛；不存在新driver或变换验证。
