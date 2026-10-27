# 第一阶段：完整 LeWM 的生产 dispatch 与资源证据

状态：**Observed / Verified（限定范围）：联合导入及两项真实原档核对 PASS。**
完整程序模型仍 OPEN，没有变换或加速比。

```bash
python -m scar.cli import-capture \
  artifacts/experiments/first_stage_lewm_dispatch_20261023 \
  --out artifacts/experiments/first_stage_joined_dispatch_20261023/result \
  --max-bytes 2000000000
```

产品 `0259a3f`，exit0，736.98s离线导入。原始命令/模型/环境见
[本次采集](../first_stage_lewm_dispatch_20261023/README.md)。该时间不是目标性能。

## 真实连接

- 264 成员、956,845,156 原始字节、5 ProcessInstance、252 HostThreadInstance。
- 39,796 dispatch、79,592真实marker，109,288逐槽引用关联。
- 480个marker观察未找到保留Python祖先、383个payload叶未满足采集规则，保持缺口。
- 310,410 CPU RF对应包括observer marker、PythonDispatchMode和redispatch层；
  不能说GPU计算执行了两次。实际runtime→GPU对应24,082，依赖provider关联而非名称。
- 74,574内存receipt；253份/906,808行OS记录。
- 12,573 OFD、12,574 handle代次、501 observed handle end、934 private-table IO连接；
  131,069行 outside_fd_profile 保留，资源完整性不因此通过。

## 核验

复用标准库 `../first_stage_joined_capture_20261023/audit.py <本目录>`：12份实际导出
SHA/size核对，223,722内存递归EvidencePoint、113,162 OS递归EvidencePoint与共享
运行身份/原始来源核对，Kineto分类及正/负receipt守恒。`audit.json`为PASS。

`audit_dispatch.py` 独立读取原sidecar、原ETO和导出桥：逐条核所有79,592 marker、
109,288槽的原始路径/序号/Tensor descriptor、真实ctrl_deps祖先链和output所属span，
并保留480/383缺口。39,796个RETURNED，零drop/error，所有marker的RF hostTID
已由导入器核，独立核对报告 `audit-dispatch.json` PASS。

这不证明代码输入内容、状态版本、alias lifetime、物理copy或GPU ready。source
invocation、schema ordered ports与状态/资源边继续接线；whole_model保持false。
