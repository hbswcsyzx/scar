# R3.3 OS witness 有限独立复审

结论：**PASS_WITH_SCOPE**。没有发现当前三项见证的具体阻断问题。
本次只读 `scripts/witness_io_pipeline.py`、`tests/integration/test_execution_io_pipeline_witness.py`、
对应已存日志和本机 stdlib；本人没有执行测试/OS 操作，也没有改产品或原测试。
这是对他人代码的源审，不把本人 host-order 模块自审充作独立验收。

## 1. 进程结束先于 owned cleanup

- `witness_io_pipeline.py:188–208` 由 parent 创建 TemporaryDirectory，worker 只拿该路径；
  parent 等 subprocess.run 返回/抛异常之后才退出目录 context。固定程序不创建孙进程，executor 只有该 worker 进程内线程。
- 本机 Python3.14 stdlib `subprocess.py:555–571` 的 TimeoutExpired 分支实际先 kill，再 POSIX wait，之后重抛；
  其他 communicate 异常也 kill，并由 Popen context 的 `__exit__:1105–1130` wait。
  因而对本脚本的普通超时分支，不会先删目录再留下该 worker 线程写入。
- `pending_pipeline:177–181` 正常路径 finally 先释放 gate，再 shutdown(wait=True)，再释放本 view。
  thread executor 的无 timeout join 受外层子进程 timeout 包住；没有使用共享 executor/cache/user path。
- **实测范围限定**：当前3个正常退出见证没有强制触发 timeout/kill 分支；上面的 kill→wait→cleanup 是源码核对，
  不能把 cleanup=True 的成功 receipt 写成“已实验覆盖 timeout 分支”。本门不为此扩可选 probe。

## 2. Event 与数据观察

- `127–185` 的 worker 先设置 started，再等 release；host 只有 started 返回后才抛受控异常并记录 done/buffer。
  main finally 释放 release 在这些观察之后，因此 pending/zero-byte 观察不靠 sleep 或调度运气。
- 实际写前4字节、memoryview.release 与 main Future.result 的异常观察分别有 journal sequence。
  `test...:31–45` 核对 hostRAISE < partial write < release < terminal observer，且 final hash 等于 `BCDE + 4个零`。
- `this_view_released` 来自 release 后索引 view 抛 ValueError 的实际检查，不是只把 metadata 状态设为 released。
  worker 的 release 是这个已知 memoryview 的事实，不证明没有其他 alias、allocation free、全部资源 quiet 或 GPU 完成。
- `actual_bytes=4` 在此是对固定 payload 的非零字节变化/完整 hash 的观察，且对应一次4字节 memoryview 赋值；
  不是 syscall 请求8却短写4的见证，不覆盖真实 pipe 短写，也不把 host RAISE 改写成 worker 的失败发生时点。
- gate/start 超时或意外异常会让程序失败，并经 finally 收束；不会走成功文档而掩盖失败。

## 3. File/flush/close/persistence 边界正确

- `85–124` 真实路径 load→upper→逐byte+1→BufferedWriter.write；独占 input/output 各只有少量字节。
  测试核 request/accepted/final 均8、final hash 对应 `BCDEFGHI`，不会仅靠请求长度宣布全量内容正确。
- `os.pread(raw.fileno(),...)` 绕过 Python buffered writer，观察同一底层 FD 的 OS 读取结果。
  它是另一次原 OS 读取，**不是另一个独立 open/process 的可见性实验**；不能把 action 名 `independent_read` 扩读为跨域证明。
- normal 路径显式 flush 后读到8字节，再分别观察 fsync 返回、close 返回。
  file_raise 路径在 save 返回后、显式 flush/fsync 前抛异常；finally 的 close 真实发生，final file 仍有8字节。
  测试明确 explicit_flush_returned/fsync_returned 为 False，因此保留 close 隐式 flush 和显式 flush 的区别。
- 没有模拟 close 自身抛错：file_raise 是外层异常后 close 成功。不能声称涵盖磁盘/flush/close 的所有 IO 错误。
- fsync 返回只观察在 normal 路径；未做断电/崩溃/目录项持久化或设备 cache 实验。
  代码 limitations 没有把 close、flush、可重新读取、持久化合成一个 ready/PROVEN 标记。

## 4. 已保存的实际运行证据（读取，不是本人重跑）

1. **pytest**：`model_pipeline_closure/witness_os/attempt001`。
   command/JUnit/stdout/report 为 **3 PASS /0.33s，exit0**，源码 before/after hash 与当前相符。
   三项是 file、file_raise、pending_raise；没有 failed/error/skipped。
2. **独立 raw capture**：`witness_capture/attempt001/command.json` 与三个 `*.stdout.json`、空 `*.stderr.log`。
   conda lewm Python3.14.7 各执行一次固定脚本case，returncode0，owned_workspace_removed_after_worker_exit=True。
   这些是三次已存实际调用输出，不能重复累计成另一组“pytest3P”或更多建模覆盖率。
3. pending raw：hostRAISE 时 Future.done=False、非零字节0；最终 worker PartialWorkFailure、4个实际非零字节，view released。
   file_raise raw：accepted8、before-flush读取0、explicit_flush=False、fsync=False、close=True、final8。

## 5. 模型对应与未证明事项

script/test 没有建立 SCAR ProgramGraph、塞入 fake WorkTicket、手填 PROVEN 或调用 GPU/LeWM。
journal 的 action、thread id、monotonic timestamp 是选定探针观察；不能自动选择动态 child、
确定资源 generation/Mat/selector、替代原 Use/StateAccess/actual completion 或 whole-work interval。
`source_runtime_verified` 与 `transformation_authorized` 均保持 False；limits 说明真实 OS 行为与 IR 对应分别验收。
后续 pipeline declared fixture/endpoint parser 的正确配对不由这3项 witness 自动证明。
未声称完整 M0–M2、自动源恢复、native coherence、persistence 或任何性能加速结果。

## 6. 本次实际阅读 SHA256

```text
d301a6fb3caad1538138ce10d157d9e73edf6285de3ba26e9d796fa3f1cabf02 scripts/witness_io_pipeline.py
15b152984f1ace67f687bd83120d07ef4a478620b540312d8ab5da017cc31419 tests/integration/test_execution_io_pipeline_witness.py
6628ffdd65c093a6c08cae01ffe82877d3ced515aac9e7be0cff16512c30a7d9 /home/zyf/miniconda3/envs/lewm/lib/python3.14/subprocess.py
7f95079dda8064cd372c9c0ea60c7e172b34c8f2aa0c3d9213e85b8584aa033c /home/zyf/miniconda3/envs/lewm/lib/python3.14/concurrent/futures/thread.py
```

原 P0 中的 teardown 无总时限风险已由实际 subprocess supervisor 接线关闭；timeout 分支仅源审的边界保持明确。
本记录冻结后不再扩实验，等待 root 的其他终态窄复审分工。
