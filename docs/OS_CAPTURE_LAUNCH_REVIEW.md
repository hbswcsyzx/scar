# OS capture实际launch与coverage接线审查

后继实施与真实CPU验收见[OS_CAPTURE_LAUNCH.md](OS_CAPTURE_LAUNCH.md)；本文保留原只读
方案及当时源码收据，不是当前实现状态摘要。

2026-10-23。**Proposed，仅只读设计，未实现、未新采集。** 本文不为旧Run补造任何
launch/profile。旧context v1已fail closed，当前仅FD_VALUES_ONLY_R2资格有效。

## 现有实际边界

当前产品没有SCAR-owned strace launcher：

- `scar/cli.py:24` `_trace`构造target环境，`:86`只有一次
  `subprocess.run(cmd, env=env)`；`:87`的run.json保存target command/returncode。
  它不拥有外层strace的argv、pid、版本、selection或关闭过程。
- 已成功capture的strace来自实验`first_stage_lewm_physical_20261023/run.sh:21–34`；
  shell文本是配置证据，不是“SCAR实际以此argv调用了这个binary”的运行回执。
- `sitecustomize.py:6–18`在target安装call/operand/evidence；
  `execution_evidence.py:99–114`此后独立生成native nonce和原路径，`:161`起声明收集配置。
  该native nonce目前不与外部OS-launch nonce相连。
- `capture_coordinates.py:232–268`读最终native manifest/retention；`:389–446`核原
  run.json与准确成功target exec/clone；`:491–504`据原receipt生成Run；`:562–586`
  最后构造coordinate document/artifact。
- `capture_import.py:119–124`目前直接bind并写coordinate bytes，然后导入native/OS。
  `os_resources.py:296–344`在interface_work模式保留所有可解析接口及return；未知
  rendering/unfinished等通过原行classification/barrier保存，未变成假Resource identity。

当前源SHA/行依据保存在`first_stage_os_launch_review_20261023/inputs.json`；无producer改动。

## 最短生产边界

建议单个focused `scar/trace/os_capture_launch.py`，由`_trace`一个显式OS采集选项调用，
直接包住其唯一target spawn边界。接口示意：

```python
launch_os_capture(target_argv, *, env, capture_root, strace_executable, budgets)
```

不接受外来“已执行argv”字典作为authority，不调用shell拼接命令；工具实际把准确
argv list传给Popen，记录其正常返回/异常、实际pid、wait状态和关闭窗口。旧默认trace
仍只执行原路径。capture_root必须显式，out精确为其trace/，OS输出为其os/；不从文件名
推测任意root。新接口参数属于通用program+OS provider，无业务名称规则。

最小改动范围：新launcher、`cli._trace`显式路由、`ExecutionEvidence`可选launch-intent
声明、coordinate/coverage的限定receipt接线、capture-import的最终发布顺序。无需改
call/operand/frontend/compiler13模块；sitecustomize也可继续原安装次序。

## 无hash循环的顺序

1. fresh目录与capture nonce先生成。O_EXCL发布不可变**intent**：nonce、计划strace
   argv、target argv、root、选项边界。intent只表配置意图，不是已运行证明。向target
   环境只传该nonce、准确intent URI+SHA；不保存全部环境/secret。
2. launcher实际执行strace，以显式`trace=all`及follow-forks配置运行原target。owned
   producer保存传给Popen的准确argv和binary标识，记录provider spawn失败/返回pid。
   代码不能从run.sh或任意现成json反填“实际调用”。target的native declaration保留
   接收到的intent receipt+capture nonce；native nonce继续独立，用明确关联连接。
3. 待owned strace与target退出且原profiler/artifacts关闭，O_EXCL发布最终**launch
   receipt**：实际调用argv/target边界、intent、nonce、binary/version/architecture、
   Popen结果与wait/return、stderr/log范围及覆盖诊断。该回执不含Run、archive或最终
   coordinates SHA。必要时可另有start记录；最终launch只发布一次，不改历史记录。
4. 对已关闭原OS/native原档做现有lossless归档；archive只列之前已关闭的观察payload，
   不收录尚未生成的profile/coordinate；roundtrip只证明字节保留，不证明runtime无丢失。
5. 正常offline importer按既有扫描获得真实target exec/clone/nonce/publication与Run，
   此时coordinate report仍在内存，未发布。核owned launch/intent/target声明/准确exec
   完全一致后，用该Run与archive receipt**派生coverage profile**，原子发布。
   这是由真实launch证据派生的selection资格，不能反向补造launch observation。
6. 最终coordinate report附`os_capture_provider={launch,profile,nonce}`，两个artifact
   都是完整URI/schema/SHA/bytes，之后只写一次coordinate bytes。profile引用Run与
   archive/launch，不引用最终coordinate SHA；Run seed不引入profile/coordinate hash。
   后续R1只绑定这一个最终coordinate receipt。原Run不能被“多加一个字段”换身份。

实现可将binder末尾“已核Run/成员→最终document”提取成小的纯finalization步骤供
同一次扫描使用；不要重复扫描百万行，也不要先写coordinate再改它。独立复读时应按
明确provider schema验证已存在profile/launch，并重建相同限定document；无launch的
旧输入保持无资格，绝不自动生成一个看似完整的profile。

## 真实执行来源与binary限定

Popen回执是**固定producer实际调用API的观察**，不是任意输入文本/完整kernel证明。
保留producer源码SHA、Python/strace executable解析路径、ELF bytes SHA、版本与machine
architecture。仅在启动前读binary SHA可能有file-to-exec race；可在owned provider
存活时核`/proc/<provider_pid>/exe`对应实际执行镜像，或采用经审查的held-executable
fd执行方案；未核不得把“预检查path hash”标为运行镜像已证明。短命/不可访问等情况
明确frontier。目标是否真正exec仍由原OS准确argv/source与native nonce的现有绑定核实。

这里需要新增runtime实际launch边界，不是让AI编辑脚本后给自己发trust bool。
固定producer行为仍是显式信任假设，不能声称可抗任意进程篡改或root级攻击。

## selection与完整事件流分开

`os_capture_coverage.py`当前小语法允许显式all或全部required control names，且必须
follow-forks；class token不贡献资格。下一joint capture优先`trace=all`，这样新接口
不会因错误的人类分类直接消失。raw资格只是rendering，不把接口加入trace selection。

**`known_selection_gaps=[]`只说明已解释argv没有已知selection缺口，不证明event无丢失。**
profile/报告要分别列：

- 真实selection/options及provider版本、architecture/personality范围；
- spawn/wait、tracer异常/终止/stderr、attach/follow/detach与actor reachability前沿；
- 每原档stored/raw SHA/bytes/line、完整末行与unfinished/resumed/格式前沿；
- budgets/磁盘写失败/截断/未知provider丢失状态；
- owner scope和canonical effects/外写/contents/ready未知状态。

strace正常exit、archive roundtrip、空known-selection-gap三者均不能合并为“全程序
资源模型完整”。CLONE_UNTRACED/ptrace限制、compat personality切换、未解析身份控制
或范围外actor等仍需显式frontier；不按TID数值/相近时间授予membership。

`trace=all`增加的接口在R1 interface_work保原SourceFact、参数rendering资格、返回
rendering和typed Work/Outcome；语法不能解析的保原行gap/barrier。未知FD producer、
unknown ioctl、network SCM_RIGHTS等不得由普通return制造OFD、aliases、GPU ready。
下一capture也须明确payload omission/rendering策略，避免trace=all顺带把缓冲区内容
当模型输入保存；接口name/result和地址/身份字段应与payload值分开。该策略本轮未实现。

## 下一joint capture所需最小字段与验收

新增实际launch与关闭回执、capture nonce/intent/native关联、运行镜像资格、准确argv/
target边界、selection与observation-gap分别报告；保现有call/operand/native/physical/
OS raw与全部收据。先在owned通用极小例核真实spawn→close→archive→一次coordinate
发布的hash DAG及失败路径，再经root明确授权采新完整episode。本轮没有执行这些操作。

验收不能只看profile已发布：必须public coverage reader实际通过、coordinate/Run/
archive/nonce精确绑定；删launch/换argv或错误class-only filter应拒绝，预算/未知格式
保OPEN。任何更强的FD-table连续性资格仍要单独通过既有区间/共享/ImportedAt守卫。
