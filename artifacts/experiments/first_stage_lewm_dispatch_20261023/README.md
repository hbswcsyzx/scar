# 第一阶段：真实 LeWM 的逐槽 Python/Torch 观察

状态：**Observed：完整 episode 成功，生产参数槽证据已采集；完整模型 OPEN。**

## 运行及环境

原始命令和所有 collector 配置见 [run.sh](run.sh)。SCAR 采集版本 `fa14a2a`，
conda `lewm` / Python 3.14.7 / Torch 2.13.0+cu132 / CUDA 13.2 / RTX 4090。
原 LeWM `f70fed80288462ca4d006cb3607ec6da6eaa851f`，before/after Git 状态为空。
没有修改 LeWM、checkpoint、数据、conda 或驱动。

仍为原 pusht checkpoint、seed42、300 samples、30 CEM steps、单 episode、
eval budget25、goal offset25、horizon5/action block5；没有缩短求解来通过验收。
额外开启 production dispatch bridge，事件/字节上限明确为 2,000,000/1,200,000,000。

## 实际结果

| 项目 | 结果 |
| --- | ---: |
| 返回码 | 0 |
| 插桩墙钟 | 404.858263s |
| 目标 evaluation time | 150.187126s，含插桩 |
| episode | success=True，结果和视频已保存 |
| Python 调用 | 100,438 invocation / 200,876 event / 855 code |
| call drop/error | 0 / 0 |
| dispatch | 39,796 |
| dispatch sidecar | 119,388 行 / 78,870,130 字节 |
| dispatch drop/error/gap | 0 / 0 / 0 |
| owned mode 退出 | true |
| ETO / Kineto | 321,223,330 / 163,177,138 原始字节 |

这些时间不能与干净 benchmark 比较，不能当作加速比；本轮没有性能变换。
成功 episode 也不等于逐动作/状态已与旧运行完全相同。

## 自动接线

同次原档经 `import-capture --max-bytes 2000000000` 核原始 manifest/nonce/SHA、
文件创建与进程所属，得到 264 个成员、253 份/906,808 行 OS 记录。
实际 dispatch importer 已核 39,796 次 dispatch，连接 109,288 条逐槽引用关联。
480 个观察没有保留的 Python 祖先、383 个参数叶子未满足采集规则，保留缺口；
不把它们当作没有数据依赖，也不凭函数名/相邻时间补边。

原 Tensor 仅在 marker 回调期间瞬时持有，使用原 recorder 弱身份。未 clone/hash、
保存 Tensor 内容或读取 `_version` 来建立通用缓存。原祖先 bytecode offset 是
真实采样位置，但祖先不是直接 source callsite，marker span 也不是外层 ATen。

联合导入产物在 `../first_stage_joined_dispatch_20261023/result`，继续核 source、
value/state、alias/allocation、资源 lifetime/ready；第一阶段未完成，不进入化简。
