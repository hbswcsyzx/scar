Root确认session64946实际exit1：Root仅向已核本任务PID1520765发送SIGTERM，原因是9个条目实测近37秒/条，剩余17项及独立factory/query预计越过原1200秒预算。不是wall/IO/RSS上限拒绝，不是自动审批拒绝，也不是schema3语义反例。Root决定见原 `ROOT_STOP_DECISION.json`，该文件未改。

producer收据715.035365436s；GNU716.64s、peak1,218,324KiB。普通catalog在215.601869s建立817groups；9条normal VERIFIED ADD_GRAPH/DEPENDENCY_ADMISSION CP2写出，最后689.659183s。第10条在SourceProgram.read_structure中收到终止，其公开reader将中断转为ValueError。9个CP2共15,370B只是未完成门的保留记录，没有manifest，不是已生效的partial publication；独立normal factory/all26 query未运行完成。

实际计额4,320,451,362B，含明确另分桶的准备I/O8,697,188B；runtime读取4,311,754,174B；pending0、budget_refusal=False。另source/control SHA13,534,423B。此前missing闭包恢复179files/7,439,337B（150sources/6,185,966B +29准确组件/CP1引用1,253,371B），264静态引用stat预检；未把JSON重建为owner。原371源码与49787完全一致。全部26原SP5仍是计划分母；本门9/26验证不替代全部26。原50窗口/817groups/100438历史calls和17未尝试项原样保存；没有新的dynamic body-call计数。

已观察到catalog guard重复canonical真实77.6MB document；尚未测量其占37秒的比例，SourceProgram structure校验同样可能占主要成本。后继应按WORK_ORDER分别profile，一次单条诊断后再选修复，不加wall、不缩26名单。

scope仍是历史272038静态来源；current369749绑定、SameRun静态guard、caller routing、wholemodel、content/state/ready均未升级。未lower/执行target/编译。原49787和本门所有冻件、失败、9CP2保留；不自动续跑或覆盖。
