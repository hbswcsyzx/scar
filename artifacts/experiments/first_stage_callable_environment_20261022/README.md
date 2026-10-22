# 实际函数环境采集

2026-10-22。第一阶段OPEN，仅一次小CPU实际采集，未扩测试。

通用CALL hook新增独立function-environments sidecar；exact function字段按原
EnvironmentRole固定五role+co_freevars顺序cells输出。函数沿用原weak引用；不能弱引用
的globals/saved-builtins/cell以仍活的只读函数owner现场is核对建立代次，地址不作
连续性证据。defaults/kwdefaults关联可变，严格使用event-local引用。

probe.py通过公开scar trace自动采集、无手填图：19事件=10 dispatch+9 entry；
零error/gap/drop，pending_peak1且结束0；9个entry的function/globals/builtins全匹配。
同code两个closure的cell分别为anchor3/anchor4，共享getter/setter保持anchor3；
cell内容改变不改cell身份；defaults重绑仍执行正确。删除函数后weakref变None，
observer未持有应用function/cell/dict跨callback强引用。

仅字段/readonly association证据，不读cell/容器/Tensor内容，不证明defaults实际
绑定或函数状态/纯性。metadata的complete callable_environment及transformation
权威字段保持False。真实LeWM采集后另报告实际量级与路由缺口。


## 同一原档连接到规范入口

没有重跑probe。link.py从源码/原始calls自动建inventory，调用现有operand linker和
新环境adapter，得到5个函数定义中的3个带缺口body；5个准确structured返回根。
环境6个实际entry关联22个原ValueID端口；12个defaults端口明确未绑定。4个其它
候选保留断点（3个无body接口、1个无entry）。原raw hash/count/attempt/handshake
全部核对通过，未伪造formal来源/ValueOccurrence或LogicalVersion。
参数/完成route仍0：caller drive/factory仍无完整body，不能用这些环境身份替代
caller Uses。此结果验证接线并如实保留原程序模型缺口，不是完整建模验收。
