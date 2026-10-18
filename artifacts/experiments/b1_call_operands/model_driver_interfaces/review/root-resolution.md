# C2D原提案的处理决定

2026-10-18；基线`012db08`。原提案不直接实施，C2D.0仍为REVISE。

1. **raw THROW：Rejected旧单packet方案。** 三个原始参数可直接到delegate且没有
   异常构造/traceback校验；改为有序Reference Uses。body ingress才接规范packet。
   不冻结统一normalize/gate/delegate顺序。
2. **epoch/generation/session：Rejected旧混合claim/无条件publish结束全部life。**
   每个短命permit最多一次BodyDrive，新的ingress另得许可；持久session保留为
   普通对象当前state。外部call可以含nested driver epoch，不能按call次数限入口。
3. **Create绑定：澄清而非新增目标类型。** core review指出现bind_call未得到default/
   pack实际值，这是自动前端缺口；它不证明`formal:ValueID`无法表达已绑定Reference。
   现FunctionEntryLayout/EnvironmentInterface已能判角色，故收敛为既有entry ValueID
   与Create owned UseID的准确映射。前置producer必须存在，缺值不得算恢复完成。
   两个Create各保留自己的映射；同site多次对象匹配仍待运行证据。
4. **Start目标：采用body RegionID。** 原creation OperationID限定会迫使共享driver
   拆分。改成body选代码、instance选动态捕获；Create候选列表不作实际实例证明。
5. **outcome：采用source-relative first frontier。** root用已有合法IR运行8个入口/
   无完成检查，另1个仅为extra-domain签名设计。Start仅首Suspend；两次恢复不能
   跨第二Suspend读到之后Return。该关系接现有ProgramIndex及共享派生函数，不造
   第二套图；这是必要实现依赖，不表示完整driver字段已通过。
6. **state域：不人为要求集合完全相等。** body输入必须有current对应，driver额外
   域沿每个outcome独立转发；缺body域或跨域/实例slot不能猜。普通LocationID不证
   对象身份；精确owner/selector关系仍归完整M1。
7. **release：保留不同实际时点和同一native调用边界。** 八组本机断言区分Attached
   rebind/DEL、完成后的owner frame清理及traceback延迟最终化。opaque call展开
   不是再执行一个release，不能重复计效果/时间，Closed不授dead/ready证明。

待共同字段复核的真正未关闭项：两层gate/owner/session参数及parent关系；逐边
current permit与owner的同步传递（不能仅比较origin集合）；状态写后的有效许可；
同一路outcome/commit/no-body-close/release关系；request/session后置表及全家族。
因此不以本文或frontier查询宣布C2D.0/C2.4、自动图恢复或第一阶段完成。

状态分工：本机语言见证是Observed；由其排除旧假设是Inferred/Rejected；字段修订
仍Proposed；只有另行验收的frontier产品能记Implemented/Verified。未跑LeWM/GPU，
不增加detector/backend或性能结论。
