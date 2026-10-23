# 第一阶段：同次采集的运行身份与资源证据连接

状态：**Implemented / Observed：联合导入成功；完整程序建模 OPEN。**

## 实际命令

在 conda `lewm`、当前 worktree 的 `PYTHONPATH` 中执行：

```bash
python -m scar.cli import-capture \
  artifacts/experiments/first_stage_lewm_environment_mounted_20261022 \
  --out artifacts/experiments/first_stage_joined_capture_20261023/result
```

输出目录必须不存在。`progress.json` 按阶段原子发布，失败会保留失败与部分产物。
本次 exit 0，373.43s；这是离线导入耗时，不是 LeWM 性能。

## 已连接内容

1. 核 native collector nonce、call/operand base manifest、环境原始 SHA、253 份
   OS 原档及目标进程创建/文件发布事实。262 成员、627,001,665 原始字节。
2. 5 个 ProcessInstance、252 个 HostThreadInstance 归属同一个 ExecutionRun。
   不将 Python ident、ETO 线程 token 或 GPU lane 当作 Linux TID。
3. native allocation/lifetime 和 OS file/handle 在构造时引用这些确切声明；
   不在产物 hash 后改 ID，也不把共享运行身份当因果。
4. 保留原 provider CPU RF 对应 151,226、runtime→GPU 对应 24,082；内存记录
   70,872（35,598 正 receipt，35,274 负 receipt）。其身份仍为 profiler
   allocator receipt，不声称物理 cudaMalloc 或 Tensor 内容已连接。
5. OS 720,049 行：603,348 syscall observation、12,569 OFD、12,570 handle
   代次、501 observed handle end、934 private-table IO 连接。116,696 行
   `outside_fd_profile` 与未归属关系保留，未从完整建模分母删除。

## 核验范围

[audit.py](audit.py) 独立使用 Python 标准库重算全部导出文件 SHA/size、坐标声明、
递归 EvidencePoint 的运行/进程及原始 artifact 成员，并与原 Kineto 分类和正/负
receipt 数量核对。它核验连接一致性与记录守恒，不验收 source/state/ready。

首次审核把坐标文件中 `target_process`（ID 引用）误当完整 process record 而失败，
修正审核读取方式，保留 `audit.initial.*`；没有改生产产物迁就审核。
第二次审核错误要求所有原始证据都已有目标进程树成员身份，因外层 tracer 的
原档不属于已证明的目标子树而失败。修正为分别核原始字节与 actor 归属；该文件的
actor 仍未解析，保留 `audit.membership.*`。最终独立审核 PASS：11 份导出文件
SHA/size、212,616 个内存递归 EvidencePoint、113,126 个 OS 递归 EvidencePoint
均核对；OS 中 1,962 处重复嵌套的未解析 actor 对应 654 个端点，未补假身份。

随后仅对本次生成原档做无损压缩，259 文件 626,993,215→30,701,720 字节，
逐份 roundtrip SHA/size 通过后删除生成的未压缩副本。显式 archive index 保留
逻辑原名和物理压缩路径；逻辑证据 URI 和执行身份不因压缩改变。
再次核全部 Run/Process/Thread 声明与原导入逐项相等，见 `retention-identity.json`。

## 尚缺的关系

`capture-model.json` 的五类必需义务保持 OPEN：canonical 全程序组装、Python→Torch
occurrence、逻辑值 provenance、源码状态/effect、资源 lifetime/ready。OS 所检查
的 25,640 个 lifetime/handle 端点中 654 个进程尚未解析，保留 null，不按 PID
补假身份。`whole_model_established=false`、`transformation_authorized=false`。

源码组合与逐槽身份桥继续推进；本次不新增 detector/backend，不报告加速比。
