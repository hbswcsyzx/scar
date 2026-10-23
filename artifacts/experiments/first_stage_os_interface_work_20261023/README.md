# R1：原369749 OS接口/work完整scope验收

2026-10-23。唯一公共CLI **exit0**；audit03 **exit0**。
范围：全部11表字节/ordinal/count、全量work wire连接与实际结构分支代表codec。
完整ExecutionModel语义、source/effect/共享FD/VM仍OPEN。

## 运行输入与身份

```bash
bash artifacts/experiments/first_stage_os_interface_work_20261023/run.sh
```

`run.py`先保存producer/code/input command收据，再以同PID exec正式公共CLI：
`scar.cli import-os-resources .../first_stage_lewm_physical_20261023/os`
`--capture-root .../first_stage_lewm_physical_20261023 --interface-work --root-tid 369749`
`--max-bytes 2000000000 --max-lines 2000000 --out .../result`。

启动revision为`c2578996ccd5d796e8f913d17ddaa3ed83a8f304`，搭配原patch和三个冻结模块SHA；
后续HEAD提交没有改变运行producer。原OS/CLI只执行这一次，不含目标、GPU、native
重导、源码prepare或测试套件。新输出不得覆盖本次目录。

## 实际分母

| 表/范围 | records |
| --- | ---: |
| observations | 1,067,768 |
| line_classifications | 1,067,773 |
| resources | 12,683 |
| handles | 12,684 |
| target_lifetime_events | 12,683 |
| processes | 5 |
| threads | 252 |
| artifacts | 253 |
| gaps | 47 |
| submissions | 1,067,768 |
| outcomes | 1,067,539 |

合计4,309,455records、681chunks；decoded10,778,976,676bytes，stored260,737,882bytes。
manifest SHA256为`cbc6dcfd78ccca0961bdabecce94bc747b7b281fdbc3f49228c8b52b9b3aec14`，
316,803bytes。chunk保本机，以manifest已有逐chunk receipts引用，不再另打包/重压缩。

54种实际syscall、8类接口。旧FD子集915,204与40类outside152,564完全保留。35个新增
producer ports是13个pipe2的两个不同OFD端点、5个eventfd2、4个epoll_create1。
handle ends570→573、connected IO1064→1065，只对应已证明私有表。

229条没有普通return outcome：7条成功exec、217条exit请求、5条poll/epoll原return未恢复。
UNKNOWN effects/dependencies/materializations/retention/quiescence全部保持；没有GPU-ready
或全效果完成记录。

## 验收与审计纠偏

- audit01：完整前8表后在membership假设处失败（36.74s）。原失败日志/producer保留。
- diagnosis：唯一无membership的是collector/context actor369747；精确archive logical/
  physical path与rawSHA/bytes对上coords.seed.target_birth，open明确该actor未归属。
  原process/thread缺该actor，不能把它猜成目标process。所有OS与membership的hash/bytes
  collision groups均0，见`audit-membership-diagnosis.json`。
- audit02：只修上述严格例外，完成140,000 submissions/139,997 outcomes全codec前缀；
  因重复验证未改codec成本过高，按明确指示SIGINT，exit130。cmdline核验/stop receipt保留。
- audit03：读同一已发布681chunks，所有11表每个chunk完整SHA/size/line/ordinal/count，
  所有work原ID/source/Run/process/thread/UNKNOWN及普通outcome一对一wire关系均核过。
  仅实际101结构分支的代表进行公共codec：101 submissions、94 outcomes。不是全2.13M
  work codec PASS，不是完整ExecutionModel语义PASS。

`audit-attempt03-summary.json`、`-codec-representatives.json`、`-table-receipts.json`、
`-query-results.json`保存范围、variant数量和真实locator；scripts/producer/time/progress
均保留。attempt03输入/模块没改R1 producer，原01/02文件不覆盖。

原未定process观察3340（均来自actor369747），旧FD子集1194；不同OS点统计中的861
不能当作相同分母。没有为消除数字而更改原coordinates或归属。

## gap与成本

`gap-comparison.json`核原metadata stored SHA，只读取有界gaps前缀，没有重导OS：
groups50→47、occurrences899118→899089。25次failedexec的错误FD参数gap修复；
4次FD选择获得真实producer。exec继承、dup来源、shared table和canonical bridge前沿保持。

CLI：wall22:01.83、peakRSS4,285,356KiB；audit03：wall4:30.61、peakRSS800,140KiB。
扫描仍保calls/observations；work导出与reader有界，不声称整个importer恒定内存。
这是离线建模成本，不是LeWM性能或加速比。

R1源码/CLI已冻结；R2设计在`docs/OS_RESOURCE_ASSOCIATIONS_R2.md`，未实施。
`whole_model_established=False`、`full_execution_model_semantics=OPEN`、无优化授权。
