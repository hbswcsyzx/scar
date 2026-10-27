# 实际交付与保留范围

原 README 是开跑前准备记录；实际终态见 [RESULT.md](RESULT.md)，独立核验见
[REPORT.md](../modeling_scope_retained_review_20261025/REPORT.md)。本门只通过原成员归属，
完整程序模型仍 OPEN。

Git 保存 producer、入口/预算/freeze、catalog、实际日志、结果、完整 ledger root manifest
和独立审查脚本/收据。`DELIVERY.json` 逐项固定这些小交付文件的字节和 SHA；它是交付
记录，不是程序图的新权威。源码实测版本为 `9ed26f5a`。

637 个 derived data/index 压缩块共 126695719 字节保留在本机 `attempt01/ledger/`，不再
复制进 Git。全部逐块 receipt 在已版本管理的 `attempt01/ledger/manifest.json` 中，独立
审查实际核过全部 stored 字节；它未重解全量 4268542417 decoded 字节。公共 query 需要这些
实际块；只有 root manifest 的 clone 不能查询本次成员数据。

大 upstream invocation archive、原 LeWM capture 仍沿用本机既有保留档，不重复存储。
重现入口和固定输入在 catalog/freeze/run_gate.py；runner 拒绝覆盖已有 attempt01。新运行
须建立新 gate 目录、明确新输入和 freeze，不得改写本次。原 logical URI 参与成员身份，
当前版本没有隐式 retention relocation 协议；换工作区重跑不能伪称原 ScopeRevision。

本次没有目标重跑、优化变换或加速比测量。
