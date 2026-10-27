# R3.3 P0：有界 OS 见证与真实协议边界

**PROPOSED / 只读设计审查，未执行本轮 OS 实验或测试。**
基线由 root 指定：`bccefcfb65dcdba71c050cbbecadd3b2f30f3fa2`。
本报告只提出下一步可实施的最小探针、原模型关联和验收边界，不新增采集器/backend/native 语言。
只读取当前源码、归档脚本、文档和 conda `lewm` 的 stdlib 源；未运行 Python、pytest、GPU 或 LeWM。

## 1. 已有事实与本轮应补的连接

- `tests/integration/test_execution_validity_witness.py:19–67` 已有真实非阻塞 pipe 短写和消费字节核对，随后把计数放入声明 fixture。
  `M1_VALIDITY_ACCEPTANCE.md §5` 归档请求 131072、返回/读取 65536 的一次观测。本文未重跑。
- `tests/unit/test_execution_produced.py:205–233` 是 **期望总输出 8、原生请求 4、返回 4、外层随后 RAISE**。
  它不是 syscall 请求 8 返回 4；R3.3 不得把这两种部分产出合并。
- 旧 `runtime_witnesses.py:13–87` 已有 dup/shared offset、独立 open、fd 数值复用、rename/replace、buffer→flush→fsync-return。
  同文件 `90–149` 有 running cancel=False、部分效果后 Future 异常、queued cancel=True 不执行。
- 旧 ready witness `witnesses.py:24–80` 用 NumPy/PyTorch CPU 别名说明 tensor 对象/指针/版本计数未变不表示内容稳定。
  新门不必再引入 NumPy/PyTorch依赖；stdlib memoryview 可提供更小的明确借用和别名反例。
- `tests/integration/test_execution_pipeline_composition.py:85–135` 已能声明并查询 host RAISE + pending work、
  terminal/quiescence/borrow/handle-end/retirement 分离，但不是一次真实多函数 IO 流水线的自动恢复。

## 2. 最小四组探针

全部为下一轮 Proposed；不能把预期写成新的 Observed/PASS。每项只存几十字节或有界 pipe 字节的长度/hash。

### W1：文件 load→buffer→consume→write→flush/close

1. 在 exclusively owned TemporaryDirectory 内创建 8–32 字节输入，O_CREAT|O_EXCL、0600；显式核每次原生写返回值。
2. 独立函数 load 用 FileIO/readinto 把实际字节装入一个 bytearray；记录返回长度、内容 hash，不能把请求长度当实读长度。
3. materialize/consume 用 memoryview 与简单 CPU 变换（例如逐字节 XOR 固定常数）；核输入和结果的确定字节。
   若需真实提交，使用下面 W3 相同单 worker/gate；只有实际存在的 Future 才有 WorkTicket。
4. save 用实际 `io.BufferedWriter(io.FileIO(...), buffer_size=8192)` 写小于 buffer_size 的结果。
   记录 write 返回、独立 fd 读的 before-flush 内容、flush 返回后的独立读取；CPython 此窄配置预期 before 为空、after 等于结果。
   “before 为空”只验所选 CPython buffer 路径，不声称任意 buffered write 都不会提前下传。
5. 分别记录 `os.fsync(fd)` 返回、stream.close 返回、关闭后重开读取。关闭后原 fd 的 fstat 应 EBADF。

可证明（本次观测）：实际加载/消费/保存的字节；selected buffer write 与外部 fd 可读不是同一点；flush、fsync 调用、close 各有独立结果。
不能证明：掉电 durability、目录项持久化、设备 cache/coherence 完整性、任意文件系统协议、SCAR 对应已自动恢复。
fsync-return 不是“已做掉电实验”；close-return 不是 fsync，也不证明 allocation retirement。
正常分支已有闭环；故意在保存后抛异常可作为同一流水线的 RAISE 变体，不能把异常当回滚。

身份分支优先复用旧六见证的证据，不为凑数量重跑；若新 pipeline 需要实际接线，可在同 owned input 内加：
dup 共享 offset、独立 open 从头读取、replace 后 old-open 与 new-open 读不同内容。fd integer/path 相同不能连接同一 lifetime/target。
不以 fstat 的同一 inode 数值证明跨 run/跨 lifetime 身份；不靠“下次 open 恰好复用 fd”作概率断言，必要时只对 owned fd 使用 dup2。

### W2：真实 syscall 短写，不能补全请求尾部

Linux profile：独占 pipe，读取 F_GETPIPE_SZ 得 C；设置 writer nonblocking，空 pipe 单次写 `2*C`。
限制 `0<C<=1 MiB`，最多分配 2 MiB；能力不存在/容量超界应准确报告 UNSUPPORTED，不伪造短写或悄悄缩成另一个请求。
预期 `0<n<2*C`，不硬编码 n==C。先关闭唯一 writer，再有界 drain reader 到 EOF，核 received==payload[:n]、长度 n 与 hash。
不能把单次 os.read(n) 一定返回 n 当通用条件；可循环读剩余字节，累计上限严格等于 n。

可证明：本次 native request/return 和实际被 consumer 收到的 prefix；未返回/未读到的尾部不能声明 produced。
不能证明：prefix 自动对应某 VG Region、读前已完成其他工作、跨 queue/device 可见、文件持久化。
原 `scar.native.byte-prefix-write` 记录必须保留真实 request 与 returned count；结果 0 也是已观察结果，不能删除 Outcome 后改作 whole future。
同步 os.write/read 可以用原 HostWrite/HostConsumer；不为复用 OutcomeProduction 强造异步 ticket。

### W3：host RAISE 时实际 work 仍 pending；部分失败与借用释放分开

用 `io.BytesIO(b'abcdefgh').getbuffer()` 建立明确 memoryview；worker 接收该 view，不读取用户对象。
单 worker 先写前四字节、设置 `published` Event，然后等待 `release` Event，最后抛受控异常。
wrapper 保存 Future 后抛受控 host 异常；outside catch 在 worker gate 尚未释放时核 Future 未完成、running cancel=False、前四字节实际已变。
main 的消费只在 published 后、worker暂停期进行，避免无同步数据竞争。
此时尝试 BytesIO.close 应因仍有导出 view 而 BufferError；它是失败的 close attempt，不能记录成 handle end/retirement。
释放 gate，Future.result(timeout=...) 应得到 worker 异常，前缀效果仍在；host 仍持 view 时 close 仍不能据 Future.done 自动成功。
最后显式 view.release，再 close 成功；分别记录 completion 与显式 borrow-release/close。

可证明：host exception 不消灭已提交工作；FAILED 不回滚已发生的四字节写；Future 完成不替代显式导出 view 释放。
不能证明：通用 executor/native quiescence、所有 Python 引用已耗尽、底层 allocation 已 free；memoryview/export 规则不能无条件套 GPU buffer。
此为 memory assignment 的部分流水线产出，不叫“native 8→4 syscall 短写”。

### W4：确定排队后的取消，不等于产出/成功

单 worker 先运行 gated blocker；收到 started 后才 submit 第二工作，其唯一效果是改 owned buffer 与置 executed 标志。
在 blocker 释放前取消第二 Future：预期 cancel=True、done=True、result 抛 CancelledError；释放 blocker 并收束 executor 后 executed 仍 False、buffer 未变。
view 仍由 host 明确保留，不能从 cancelled/done 推断借用已释放；显式 release 后才尝试 close。

可证明：本次 ThreadPoolExecutor 的 queued task 没执行，cancelled terminal 不是成功写/消费。
不能证明：running cancel 会停下、所有取消协议无部分效果、CUDA cancel/quiescence；不从 Future.cancelled 自动填 native quiescence。
它与 W3 running cancel=False 为必要对照，避免依赖 scheduler 抢跑概率。

## 3. 必须先设好的有界执行和清理合同

- 所有等待用 Events/Future 的明确 timeout（建议每 gate 2 s）；finally 无条件放开所有 gate。
- **还必须有独立子进程的总时限**（建议每探针 15 s）。`Future.result(timeout)` 只约束该 wait；
  `ThreadPoolExecutor.shutdown(wait=True)` 的本机实现逐 thread.join() 没有 timeout（thread.py:254–273）。
  旧脚本只给 gate/result timeout，不足以把所有 OS IO/executor teardown 变成硬有界。
- parent 只管理本次创建的单独 child，不用共享 executor/cache。超时先 terminate、短 wait，再 kill；确认 child 已退出才删其 owned 临时根。
  不发送信号给不属本次的进程，不使用全局 drop_caches/sync，不碰用户路径。常规路径 finally 按精确持有集合关闭 fd/view/stream。
- 文件 bytes<=256，pipe<=2 MiB，无无界 read/write retry；实际 short read/write 按返回长度推进，零进展不无限循环。
- 将脚本与命令/hash/解释器版本/stdout/stderr/退出码/持续时间/实际数字/清理 receipt 原样留 attempt；首失败不覆盖。
  子进程强杀或清理异常记 FAIL/TIMEOUT，不伪报所有 probes 通过。host/fsync IO 即使异常卡住也由外层总时限覆盖。
- 不靠 sleep 假定工作已运行/取消成功；Event 形成可核观察阶段。不得用进程墙钟直接补 WorkStart/WorkEnd 精确原生边界。

## 4. 与原 pipeline 的关联策略

1. probe 记录实际请求/返回/消费 hash 与明确 stage/异常/关闭事件；原始 bytes 按现 inventory builder 封存，保留原 RawRecordRef。
   不把 Result snapshot 自动解释成物理 write；BytePrefix 只解析现 whitelist schema 和准确 raw 行。
2. root 的通用多函数 ProgramGraph 仍保留原 load/transform/submit/await/save/flush/close Operation、Use、StateAccess 与实际 NORMAL/RAISE port。
   动态 CallActivation 逐 occurrence/activation 连接；同名函数/父 EEG span/同 scope 不是选择 child 的依据。
3. file/pipe 是独立 Endpoint/Resource；RAM buffer 才有其实际声明的 allocation/Mat。不能为了 G 覆盖把 file FD 伪造成 memory allocation。
   WorkWrite/Outcome 只用于实际异步工作；同步 HostWrite/External establishment 不造 ticket，Host read 不造 WorkStart/End。
4. 写实际 prefix 复用 WriteAssociation + OutcomeProduction/EstablishedProduction 和原 effect、实际 completion poststate。
   任意 Footprint 无字节单位，不能只凭 WHOLE 生成 actual byte Region；若 endpoint selector 还未解析，精确标未决。
5. Q 采用原 ContractRef/required slot 或明确 RequiredEndpoint、真实 observation/read interval/current support。
   “flush 返回”“close 返回”“重新打开读到数据”是不同原事件，不用一个 FactRef/facet 升级 persistence。
6. 对 selected OS probe 与 declared IR 的配对，即使 run/endpoint/count 已明确列出，也保留 conditional source/native applicability；
   报告并列 Observed bytes 与 Declared graph guards。完整捕获、native pairing、物化身份、visibility、transform flags 继续 False。
7. R3.3 验收至少包括这些对应负例：actual4/request8不能whole；hostRAISE不能删pending work；FAILED prefix仍在；
   cancel/done不造产出；borrow未release的close失败；旧event/handle/allocation不能因相同数值/名字复用；删Q/read/source joins不缩分母。
   现 endpoint parser 不支持时记录准确 UNSUPPORTED/MISSING，而非为凑全程正例手填 PROVEN。

## 5. 已读源码指纹（SHA256）

路径除最后四项外相对工作树；stdlib 路径为 `/home/zyf/miniconda3/envs/lewm/lib/python3.14/`。
读取 stdlib 仅支持本机实现设计，不等于本轮已运行其行为；官方 Python/POSIX 文档由 root 独立核对。

```text
61736a74a2a100f17b1772bbf7b36604d463560faa5f0dd282972b9a5f6c3c77 tests/integration/test_execution_validity_witness.py
be46cee7b8c348616026b4890830f67677fe6afc4efc18ba51ec0ebc5be7c4d0 tests/integration/test_execution_pipeline_composition.py
24733d0e3d0eea29438bb371ee13573a3b60c200dcc46088af1f583002a3b546 tests/unit/test_execution_produced.py
149e0fb885b900edafc1b0abd2a6340663de2d81d24a6adef7db86bfda86fb3f artifacts/experiments/b1_call_operands/model_resource_execution_design/witnesses/runtime_witnesses.py
542a80628e5c1046a06e23970bbd387f5f7f00a0e95a8a873510330e887f56da artifacts/experiments/b1_call_operands/model_resource_ready/witnesses/attempt001/witnesses.py
74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729 docs/M1_RESOURCE_EXECUTION_CONTRACT.md
6b03d971cce36a06a13fe80e50675bafe403d1106f69bc33338ddc2ff1b9afb7 docs/M1_PIPELINE_COMPOSITION_PLAN.md
3a0c16835d74135028fd61a891e3fab9e85fb0325001013fed1f8fae25c59923 docs/M1_PRODUCTION_ACCEPTANCE.md
f76512c9611f8e6561fb15e68a616ac8b54c18fb4320b86115bcfb0fc849a15d docs/M1_VALIDITY_ACCEPTANCE.md
7f95079dda8064cd372c9c0ea60c7e172b34c8f2aa0c3d9213e85b8584aa033c concurrent/futures/thread.py
0932abfae68a9bc4807a367ab60bd2ef31d98ae305ee8b70f9e595a747c3b2a1 concurrent/futures/_base.py
e07d55084185e40255084d409a126ab9889c76ff1d9cc67fc9157450e78770f1 _pyio.py
3714372b63f6bc05a5273425d446f6ad3a2112a659c71c321bb4575fd082d634 tempfile.py
```

关键 stdlib 阅读：thread.py:75–93/199–216（submit/task异常）与254–273（shutdown join）；
_base.py:359–376/424–456/495–529（cancel/result/running）；_pyio.py:876–913（BytesIO view/close）、
1234–1319（buffered write/flush/close）。`_pyio` 是解释用 fallback，实际 `io` C 路径行为需下一轮 probe 验，不以其文本代替观测。

本报告到此冻结；等待 root 的明确实施分工，未创建新脚本/测试或执行 OS 操作。

## 追加：root 的 P0 范围决定

上文四组是源审提出的候选，不作为本门四项新实验分母。root 收敛本门必需新见证为：

1. **完整 file/buffer 流水线**，含真实正常/异常退出的 close、flush 与可读性分离；不扩新 native parser。
2. **确定性 host RAISE + pending worker/borrow**，必须有子进程 hard timeout 与 parent exclusively owned cleanup。

实际 short write 复用已封存 pipe witness，不重造/重跑同一探针；queued cancel 仅可选，非本门必需。
后续由 root 编写和执行 OS witnesses；本 agent 等待另一项精确分工，不同时展开多文件实验。
上述范围决定替代“新跑四组”的初始建议；协议和不可证明边界不变。最终 P0 仍纯设计、零新 OS/pytest 运行。
