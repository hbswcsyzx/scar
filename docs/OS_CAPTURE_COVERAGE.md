# OS capture coverage correction

后继 **Implemented + Verified**：SCAR-owned launch/profile v2已在唯一成功的自有CPU
full-profile门中通过。新`--os-capture-root`真实Popen/运行镜像/native intent/归档/一次
最终coordinate发布已接通；旧Run不补造launch、旧35容器资格不恢复。见
[OS_CAPTURE_LAUNCH.md](OS_CAPTURE_LAUNCH.md)。原v1纠错协议与历史说明如下。

2026-10-23。Observed：原capture实际脚本只选择四类
`%file,%process,%memory,%desc`。strace6.8原生amd64 syscall表中unshare/close_range为
flags0；类过滤按mask机械筛选，不能由接口的人类含义推断成员。当前安装包
`strace 6.8-0ubuntu2 amd64`的独立安全probe中，两个child实际调用均成功，原filter各
记录0次，显式二名各记录1次。probe不补采旧episode，也不证明旧episode调用与否。

原证据：`first_stage_fd_interval_review_20261023/capture-coverage-correction.json`。
安装包probe：`first_stage_strace_filter_probe_20261023/`，保存actual argv、binary SHA、
version、child返回、原日志和time。原capture只有version记录，不能反称已核其历史binary SHA。

Primary sources：[amd64 syscall table](https://raw.githubusercontent.com/strace/strace/v6.8/src/linux/x86_64/syscallent.h)、
[common table](https://raw.githubusercontent.com/strace/strace/v6.8/src/linux/generic/syscallent-common.h)、
[class selection](https://raw.githubusercontent.com/strace/strace/v6.8/src/basic_filters.c)。

## 已撤销与保留的结论

- 旧FD-context35端口：byte/typed/FK/preimage检查真实；依赖“无未见table变更”的
  InstanceTarget连续性资格撤销。原artifact不可变；public旧reader显式拒绝v1。
- 12110同区间候选：只是Run/source/line范围候选，**0个新container绑定获批**。
- FD源投影：真实FD输出值、selector、原字段守恒仍保留。新显式schema2
  `FD_VALUES_ONLY_R2`只选原public R2，35个既有端点及其余端点container均Unresolved。
- R1 OFD目标、dup coidentity/end等是保留的baseline declarations，不被FD值证据证明。
  旧filter漏TN-only socket/socketpair/accept/recvmsg等网络接口；其中可出现新FD/SCM_RIGHTS。
  ioctl虽有TD而被选择，其provider特定FD输出仍不等于已解释。未观察到producer不得
  解释为无producer或无FD复用。没有声称任一漏项在旧episode中实际发生。

## 当前最小公共资格API

`scar.trace.os_capture_coverage.OSCaptureCoverage.read(profile, launch=..., coordinates=...,
archive=...)`要求独立的、capture-bound实际collector launch/profile artifact。
coordinate binding必须精确含两者ProviderArtifact、nonce；profile绑定Run/archive/launch。
launch类型为COLLECTOR_EXEC_ARGV，含真实argv、target边界及binary SHA；profile记录
provider version/architecture。严格小语法只承认显式`trace=all`或全部required control
names及`-f/-ff`。类token从不贡献资格，后续trace选项按替换语义解释；不支持的过滤器拒绝。
`known_selection_gaps=[]`只是额外必要声明，不能代替实际argv检查。

`OSFDTableContexts` schema2的builder与reader都要求此对象，并重新核完整artifact
receipts。对象不能由公开构造函数或trust bool创建。没有为旧capture伪造launch/profile，
最初纠错门尚无collector producer集成；后继v2已在真实exec路径生成并通过CPU资格门。
v2额外核owned running image、intent/native准确membership与独立nonce，仍不把selection
资格当完整event/effect证明。旧capture缺这组回执，不能因后继代码存在就获得资格。

coverage是已有scope内continuity检查的**必要条件**，不是全部Linux接口模型：不证明
FD内容/offset、全量OFD alias、ImportedAt前后ready、外部writes或GPU状态。原provider
scope/不完整行/flags/共享线程/区间及所有原守卫仍须独立核对。完整建模阶段继续OPEN。
