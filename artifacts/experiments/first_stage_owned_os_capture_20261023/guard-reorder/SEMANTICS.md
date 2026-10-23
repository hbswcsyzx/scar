# Guard reorder scope

Root授权额外只修改call_edges.py/call_operands.py的无动作前筛，不修改规范类型、计数或
事件writer，也没有缓存PID、假设不存在raw fork、改变frame/call输入。

| 原动作条件 | 新顺序与保持点 |
|---|---|
| CallEdge c_call/c_return等不记录 | 在PID前按原event类型拒绝 |
| CallEdge项目外call不记录 | 原纯_inside(frame/caller)先判断，真正call仍核PID |
| CallEdge未知return不记录 | 原active在RLock内只读预查，无对应时直接返回 |
| Operand普通C事件无动作 | 先返回；c_call仍全局_profile_setter，不按项目筛掉 |
| Operand项目外call无动作 | 原纯_code_inside先判断，再PID/原处理 |
| Operand未保留return无动作 | 只查自身_frames，父recorder.active已先pop，不能替代 |
| 候选动作/计数/写出 | 全部仍先核当前真实os.getpid，再原锁内逻辑 |
| raw-fork继承锁 | membership预查用原RLock非阻塞；锁不可用先核PID，不新增先阻塞死锁 |
| hook mutation | 项目外实际setprofile(None)仍检测，原interference/stop保持 |
| 写出失败/预算/异常/old-profile forwarding/at_fork | 原路径保持；Operand新增前筛异常记账前也核PID |

preimages保存原完整两个source；revised.py保存新source；guard.patch为exactdiff。
guard_behavior.py是一个真实sys.profile/sys.monitoring/单线程fork的小行为检查，不生成
规范图、不作为production capture证据，不是测试套件。0.53s实际exit0；summary记录
1000外部noise无PID syscall、UNKNOWN exception1、自身frames0、子进程拒绝与全局hook
mutation检测。后续完整CPU采集用独立fresh gate-attempt02和相同预算验收。
