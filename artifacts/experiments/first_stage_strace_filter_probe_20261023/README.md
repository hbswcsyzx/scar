# Installed strace filter probe

2026-10-23，root授权的隔离、无目标状态修改的本机比较。`child.py`只在SCAR自建子进程
调用native-amd64 `unshare(0)`及`close_range(UINT_MAX,UINT_MAX,0)`，没有namespace flags，
没有有效FD被关闭。两mode各自创建新child，均exit0，两个实际syscall都返回0。

相同安装strace与通用采集参数下，原四类filter记录0/0，显式二名记录1/1。
`summary.json`保存binary SHA、version、architecture、actual argv/return以及日志收据；
两目录保原始strace log/stdout/stderr。本次不是旧episode补采、替代trace，也不证明旧
episode是否调用任何遗漏接口；仅确认安装filter确实遗漏已真实调用的两接口。

该结果纠正原“计数0→无变更”的SCAR证明缺陷。后续FD数值与table连续性必须分开资格，
详见`../first_stage_fd_values_correction_20261023/README.md`。
