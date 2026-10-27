# 第一阶段：生产 dispatch 槽连接的实际 CPU 验收

2026-10-23。一次真实采集，外部 `case/app.py`；未运行 LeWM，未增加测试套件。
conda lewm，Torch 2.13.0+cu132 / revision cf30153c4c131c8164ee7798e5022d810682e2cb。

## Implemented

`DispatchEvidence` 复用当前 CallEdgeRecorder 的真实保留调用和 weak token；每次
dispatch 仅执行一次 `func`，不 clone、读取 `_version`、hash Tensor 或保存数值。
精确 tuple/list/str-key dict 机械平铺，plain Tensor/nn.Parameter 传入 provider
marker 的位置参数；其它叶和预算缺口逐项保存。输入 marker 保持为 dispatch span，
返回值另建 output marker；它的 Tensor 同样位于 **marker.inputs**。

`ExecutionEvidence(..., recorder=recorder)` 在已启动 profiler 后安装 owned mode，
先退出 mode 再关闭 profiler。只退出自己的栈顶；foreign mode 保留，未退出的自身
mode 停止观察。独立 JSONL/meta 有事件、字节、深度、槽数上限，meta 保存自身精确
SHA/字节和最终 native manifest 的精确 SHA/字节；共享随机 nonce 来自该原生采集。

`import_dispatch_bridge` 接受已导入 native result，加显式 sidecar/meta/calls/codes/
call-meta/native-manifest 路径；不跟随 manifest URI。它核验 nonce、producer 配置、
字节、保留祖先的真实 entry/code/thread/事件区间，以及精确 ETO marker 输入槽。
对象连接追加到原 ValueGraph/EvidenceGraph，不另造 Tensor 图。

## Observed / Verified

- 子进程 exit 0；普通结果、view 形状、autograd 梯度、预期异常均通过。
- 18 次 dispatch：17 RETURNED、1 RAISED；53 条 sidecar、35 个实际 provider marker。
- 39 条逐槽对象引用关联；独立原档核对发现 3 处重复 Tensor 参数槽并正确保留。
- 异常 dispatch 没有 output 记录；其 span 正常结束。
- 所有 output marker 的真实 `ctrl_deps` 都指向自己的 span。
- RF 对应的 Kineto 原始 host TID 与 sidecar native TID 一致。
- 零 drop/error，owned mode 已退出；原档保留在 `raw/`，解码及独立检查结果见
  `decoded.json`、`audit-result.json`。首次采集总 wall 14.54 秒，包含导入与插桩，
  不作 benchmark 或加速比。

`decode.py` 对相同原档离线解码；补 native-TID 核验后仅再次离线读取，没有重跑
forward。独立检查直接读取 JSON/JSONL、哈希、重复槽与 provider 祖先链。

## 证明范围

callback 开始时原 dispatcher 的 RF 已经存在。新增 span 只包含实际 redispatch
子树；它的父节点仍是 provider 的 PythonDispatchMode，其上层才是原始 ATen。
因此保留真实 `ctrl_deps` 路径，**不宣称 direct Python→ATen 调用**。bytecode offset
是采样时保留祖先 frame 的准确位置，不等于已证明的 source ast.Call。

本 CPU 采集没有 strace 所属关系收据，`capture_membership_verified=false`。传入
coordinates 时 importer 要求每个 sidecar/call/native artifact 均有共同进程的
已核验 membership。完整线程覆盖、foreign mode/subclass、逻辑版本、写效果、
alias 生命周期和资源 ready 未验收；whole model 与 transformation 均保持 false。
