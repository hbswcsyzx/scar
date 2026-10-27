# 后续 driver 字段提案的 root 复审

2026-10-18；在冻结 `e6b4723` 的 full 运行期间只读复审
`driver-field-contract.md`。**Proposed，尚未字段冻结或实施。**

## 继承的决定

保留单一 body/canonical Uses；BodyDrive 必须是专用入口/完成协议，不能把普通
INVOKE 的二分出口偷偷改成 Suspend。Create、gate、delegate、adapter、release
中会回调或失败的工作复用普通 helper Region/INVOKE。C2B 私有frame/caller值不因
driver存在而解禁普通call。当前状态在实际body ingress之前取得，不能从Create/
初始gate恢复旧world；每次Attach才捕获该drive的caller。

## 冻结前必须逐项关闭

1. **实际参数唯一性：**新variant的instance/claim和body输入分别占独立owned Use；
   invoke_arguments仍只存一份actual列表。索引/查询不能再存Value副本。
2. **静态site与动态实例：**两个对象可共享Create/body/Suspend site和同一粗world；
   同一个对象也可经alias驱动。声明引用路径和真实实例/epoch/generation是不同
   证明域，不能从site、类型或静态use数推出唯一/互斥消费。
3. **目标与outcome：**Start与精确Resume case的输入布局各自派生；outcome引用真实
   Suspend/Return/Raise site。覆盖/可达性规则必须说明目标相关的保守范围，不能
   把C1仅声明而未实际到达的出口凭空当completion。
4. **driver-only路径：**接受、delegate-only item、无body关闭、拒绝、再次yield后
   host报错必须区别。host RAISE不自动FINISH_BODY，drive epoch不自动推进body
   generation；request对象的owner与body实例分开。
5. **final release：**真正Detach/完成后，driver中引用释放/回调及部分失败具有当前
   状态与完成边；旧同步FrameExit相邻规则继续保持。版本化适用条件与实际引用
   管理见证需独立审查，不能以无回调metadata primitive替代真实finalizer。

下一步先冻结这些字段/边界并做语言最小反例，再按Create→gate/专用ingress→
lifecycle/adapter/release组合实施和自验收。每项保留独立gate与失败报告，不用新增
detector、backend、Tensor snapshot、完整Python编译器或重型LeWM trace补接口缺口。
完整C2与M0–M2仍开放；本复审不增加任何已验证产品能力或LeWM加速结论。
