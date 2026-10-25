# 原生 Tensor 输入 metadata 保留

2026-10-25。Implemented；真实CPU采集、离线完整回读及普通CaptureCoordinates
成员归属Verified；后继已接一个真实采集的规范输入端口子集。内容/状态/ready、
全部原生内部及整程序建模仍OPEN。

现有同一个owned profiler的同一次DFS可额外保存每个TorchOp的输入metadata。
设置`SCAR_NATIVE_TENSOR_INPUTS=1`，并对普通trace启用`--call-operands
--execution-evidence --tensor-physical`；默认V1输出合同保留。新profile
`scar.native-tensor-input-event-tree-v1`生成有界JSONL分块和小manifest，严格reader
核完整字节、行/槽顺序、闭合的native/dispatch/legacy metadata链。

直接Tensor和TensorList分别保原路径、dtype/device/layout/shape/strides及provider IDs；
zero-dimensional Tensor和空list不同。provider的None也可能表示unsupported/undefined，
保OPAQUE，不能重构成真实None。scalar仅存type tag，不存Tensor或scalar内容。
原生outputs未在固定API暴露，明确UNAVAILABLE；held output-marker是另一份输入见证。

真实CPU新feature实验生成43条TorchOp、22块/47007B。原probe在预期空list操作抛出
ValueError时因只catch RuntimeError退出1，finally已正常关闭；原失败保留。
后继离线strict回读exit0/0.100s、GNU0.17s/RSS23716KiB，无Torch导入或新采集。
40项Tensor metadata、6个TensorList（其中空list3）、47项OPAQUE和30项scalar type tag
均来自完整回读。此feature CPU采集一次，与此前collector来源CPU门分别计数。

三源码及完整小样例存档在`codex/native-scalar-model`的3b16c0d2；实际报告位于该分支
`artifacts/experiments/native_tensor_inputs_probe_20261025/RESULT.md`。
主树[应用收据](../artifacts/experiments/native_tensor_inputs_applied_20261025/receipt.json)
保留准确版本。原URI不因复制目录自动迁移；以上是第一份feature实验的范围。
旧1901项未定Python身份未因此获资格；没有logical version、alias、内容或ready结论。

## 后继owned archive和成员归属

同一闭合native manifest中的显式profile/PID/nonce声明决定companion manifest及
准确chunk表；archiver复用原lossless归档，不递归扫描目录猜成员。坐标binder要求
每个新manifest/chunk有目标进程准确的O_CREAT+O_EXCL证据，再发布
`SCAR_NATIVE_TENSOR_INPUT_MEMBERSHIP_V1`。它只说明原artifact及创建进程归属，
不授原生端口、Python对象、几何、逻辑内容或资源ready资格。strict reader本身
仍不发成员资格；资格由普通CaptureCoordinates提供。

显式`allow_plain_owned_capture=True`只允许归档前闭合事实预检：返回
`PENDING_LOSSLESS_ARCHIVE`、profile为null并保留publication缺口；默认行为仍要求
归档provider证明，预检不发布OS coverage。Run seed算法不变，新成员不加入seed。

唯一CPU CLI采集实际exit0，得到2332条/3块/3014193原始bytes；首次外层gate
exit1/29.344s是脚本误读launch schema2中不存在的`target_argv`字段，原失败未改。
后继只消费同一归档，postflight实际exit0/1.760928s，未导入Torch或重跑目标：
全部4个新artifact的`process_for`与目标一致，3块strict回读通过，归档前后RunID
完全相同。原始CLI0、外层1和离线0分别保留，不能把原gate倒改为PASS。

三文件精确应用及验证范围见
[应用收据](../artifacts/experiments/native_input_membership_applied_20261025/APPLICATION.json)。
旧LeWM capture未含此profile，不因此增加其建模覆盖率；后继仍需准确ETO输入端口
适配及状态/来源/资源关系。

## 规范输入端口子集：真实接线

`bind_native_capture_model_batches`消费准确G1 capture-model/分区收据，正常调用
公共coordinate binder一次，不从JSON恢复owner；复用原V2边界producer，每个已验证
shard同步交给metadata checker。`NativeInputMetadataSession`从真NativeInputRef及
ValueOccurrence追到invoke的原EEG绑定，再核原ETO ordinal/input path和对应
companion/Kineto事实。源指针、几何、对象、逻辑版本及ready是独立资格。

同一已有CPU capture的attempt04实际exit0/19.634582s：261个dispatch全部入账，
260个正常调用形成2个已验shard；2332行/3095个metadata路径完整保留，516个路径
关联实际规范输入端口，2579个路径没有canonical边界而保留frontier。
同Run换producer+ordinal且重新编码candidate的唯一反例被独立语义检查拒绝，
没有依靠旧owner hash失败。未重做G1/native/OS importer或执行目标。

前三次失败原样保留，分别定位并处理三种模型边界：

1. process归属相同不表示artifact可用同一个PID selector；native helper只取其准确
   closed roots和companion成员，不混入用TID选择的OS线程文件。
2. 原ETO仅一条缺父边影响两个节点，对应唯一异常dispatch；其它2330节点父链完整。
   新`SELECTED_NATIVE_PARENT_CLOSURE_V1`完整保存父关系分母和缺失前沿，每个待发
   lease仍严格核其所需祖先；cycle/重复/身份矛盾继续硬拒。全树闭合明确false，
   dispatch分母完整不等于全树完整。异常与缺父的因果仅Inferred。
3. provider的`torch.strided`与已有规范图的`strided`通过准确
   `PINNED_TORCH_LAYOUT_V1` receipt连接。兼容读取必须核provider_layout、实际point、
   固定profile/revision及原normalizer结果；规范记录原样投影，不再次转换。
   其余point/epoch/birth校验保留，V1代码定义静态对比未变。

证据payload预扣及成功完成阶段核算均为67280634B，控制metadata860820B；全部阶段
完成后pending0。它们是明确读遍次和已核字节的账，不是kernel I/O测量。producer源码
hash读取13228666B另计。没有增加B/C、内容/state/ready或旧LeWM1901项资格。

四文件准确应用及main静态/import/V1检查见
[应用收据](../artifacts/experiments/native_input_port_binding_applied_20261025/APPLICATION.json)。
原门和诊断保存在`codex/native-scalar-model`分支
`artifacts/experiments/native_input_port_binding_20261025`，首次三次失败及源快照均保留。
