# SCAR-owned OS capture

2026-10-23。Implemented；当前真实gate状态见末节。旧capture不会被补造launch。

显式入口：

```bash
python -m scar.cli trace --call-operands --execution-evidence \
  --os-capture-root /absolute/fresh/capture --out /absolute/fresh/capture/trace \
  --project-root /source/project -- python program.py
```

没有`--os-capture-root`时继续原target subprocess路径，不导入OS launcher。新选项要求
fresh root与明确ROOT/trace，只启动自己的strace和新target，不能attach现有process。
`--max-os-bytes/--max-os-lines/--max-capture-bytes/--max-archive-bytes/--os-timeout`
分别限制OS文件、归档与wall预算；OS文件/诊断字节有50ms周期的软上限检查，触发只终止
自建process group并保存失败launch，不声称严格瞬时磁盘上限。native provider内存预算
仍有原声明前沿。预算/启动失败不会出版合格profile。

## schemas与单向发布

1. `scar.os-capture-intent/1`：fresh nonce、计划argv、target边界、root与预算。O_EXCL
   原子发布；是配置意图，不是发生过执行。只把其URI/SHA/nonce交给target。
2. native原schema1 configuration可选`os_capture_intent`，绑定准确intent receipt与
   capture nonce，同时保留独立native nonce。无该环境时不增加该字段或launcher依赖。
3. `scar.os-capture-launch/2`：SCAR实际传给Popen的argv、target边界、owned child pid、
   binary/version/architecture、真实wait状态、budget/异常与诊断范围。`/proc/<ownpid>/exe`
   存活镜像bytes与预检查binary一致时才OBSERVED；不能核时保OPEN。它是固定producer
   调用边界的可信回执，不声称对任意篡改有密码学防护。
4. 原`scar.lossless-capture-archive/1`：复用store的有界`_Sink`/JSON encoder、gzip
   与原logical/local映射。先核全部raw→gzip→decoded roundtrip，再原子发布manifest，
   最后仅删除本fresh capture生成的重复plain文件。预算失败保留原档与失败输出，不
   发布index。io_accounting明确包括raw读取与decoded roundtrip读取；不是零IO。
5. `scar.os-capture-coverage/2`：binder同一次正常扫描得到Run后才派生，引用已固定
   archive/launch/intent/native receipts，不引用最终coordinate SHA。
6. 最终coordinates一次发布，包含profile/launch/nonce与UNKNOWN observation状态。
   Run seed不含新增profile/coordinate hash，无hash循环。后续public import可复核已发布
   profile；不重写它。`capture_import`在首次需要时允许显式完成该派生，但没有真实
   native intent与owned launch的旧输入始终走旧路径、不能获得资格。

CLI调用完整流程至最终coordinates；非零target/provider返回保launch与raw，保持真实
返回码。成功target但收集/归档失败仍保原证据，SCAR命令明确失败，不能冒充成功建模。

## selection、payload与effects分开

实际使用`-ff -ttt -T -s256 -e trace=all`，不使用class猜测、status/FD/path过滤。
单独`raw=`只影响IO数据rendering：read/write与iovecs、socket消息/buffers、getdents、
getrandom、process_vm IO、socket options、ioctl；准确名单保存在intent和代码常量。
exec/path/clone flags保持解码，供原exec/membership证据规则使用。不是任意Tensor内容
保存器。新增未知接口/未知provider payload仍须保frontier，不能声称此有限名单涵盖
所有可能设备协议。混合tracer/target stderr独立留存，不能当纯tracer loss诊断。

profile的`known_selection_gaps=[]`仅由严格实际argv语法得到；
`observation_completeness=UNKNOWN`与`os_event_loss_not_established`始终保留。
strace退出0、字节roundtrip、空selection gaps均不证明无事件丢失、所有actor闭包、
纯性、FD/OFD alias/end、canonical effects或GPU ready。

interface_work原scanner保全部已解析新增接口/result的Work及原source；未知参数/行形、
unfinished/resumed、人格迁移等保原classification/gap。没有为了trace=all增加资源解释器。
当前primitive selected filter资格只是后续continuity证明的必要条件，旧35结论不因此恢复。

## 公共回读与版本边界

```python
coverage = OSCaptureCoverage.read(
    profile_path, launch=launch_path,
    coordinates=capture_root / 'capture-coordinates.json',
    archive=capture_root / 'archive-index.json',
)
```

新v2额外检查准确native member、intent/capture/native nonce、actual argv/target边界、
proc运行镜像与closed receipt；v1仍保持其原始严格协议，旧context/schema1拒绝不弱化。
不从外来provider URI任意开文件；intent/launch/profile是根目录内固定nonce命名，native
从准确coordinate membership的local路径读取。当前显式不支持此新增链的隐式relocation。

## 当前验收

首门`first_stage_owned_os_capture_20261023/gate-attempt01`实际预算失败：runner exit1，
CLI241，owned provider -15；OS_BYTES达到64MB后只终止自建组，非正常target退出。
wall46.96s/RSS427600KiB。native仍WAITING_FOR_TORCH，无archive/profile/coordinates。
存活镜像已OBSERVED；原档与有限样本/失败收据保留，未抬预算或重跑。

末尾128KiB的2182完整调用均getpid；源码中call/operand观察器在event/path筛选前
调用getpid，inferred为Torch import期间主要观察膨胀原因。有限样本不当全局分母。
这不是端到端资格PASS。root审查后保留原full profile，只前置证明无动作的callback
筛选：普通C事件/项目外调用、未保留return不用PID syscall；真正动作仍先核真实PID。
全局hook/monitoring mutation检测、原锁、fork拒绝、budget/error路径与原schemas均保留。
没有native-only新profile、没有伪造空calls/operands。

独立必要guard行为门exit0：1000次项目外noise为0个getpid；真实异常UNKNOWN return1、
自身frames清空；无SCAR at_fork的子进程仍被PID guard拒绝；项目外setprofile修改仍被
识别。原source/preimages、exactpatch和语义对照保存在实验guard-reorder/。

**第二独立full-profile门Verified**：`gate-attempt02`，同64MB/120s预算，CLI/runner
均exit0；wall27.86s，GNU进程树maxRSS805588KiB（runner自身130752KiB，二者不混报）。
11档8,344,309decoded/916,903stored bytes全部原收据核对；4 OS档81,185lines，解析
81,180interfaces、70,190旧outside_fd_profile、0parser frontier。安全unshare/close_range
各真实1次。保26call/43operand/3environment/12dispatch事件，0declared drops/errors；
不由此声称所有事件无丢失。public coverage2回读和错误nonce拒绝通过。

最终coords SHA `51c3d55c4492ff2f4f769d53f41ebb465a5529620b314b8d334d0f8be8ff9920`；
profile SHA `603ecfabb1c97436048d67b93960762d3ba3dd38f235b53c9f72f4f796badfea`。
全部新profile依然observation_completeness UNKNOWN，完整模型OPEN。该成本是采集链
资格验收，不是LeWM wall-clock/优化加速比；本轮无LeWM episode或历史raw重读。
