# FD namespace连续性临时隔离

2026-10-23。**Implemented + Verified拒绝边界；namespace闭包仍OPEN。**

唯一生产改动为`scar/trace/os_fd_table_contexts.py`。新增公共同一guard
`require_fd_namespace_continuity`先实际核selection coverage，再抛专用
`FDNamespaceContinuityUnproven`，reason code
`FD_NAMESPACE_CONTINUITY_QUALIFICATION_NOT_IMPLEMENTED`，status OPEN。
guard位于_prepare的raw replay、ResourceInstance及InstanceTarget构造之前。
build/read共享_prepare，旧schema1 reader版本拒绝未改变。没有caller trust bool、
complete标记、资源改名或创建新的真假proof类型。

这是对缺独立identity-continuity前提的临时quarantine，**不是最终解决方案**。后继实际
producer/有限合同路线见[SCOPED_FD_CONTROL_QUALIFICATION.md](SCOPED_FD_CONTROL_QUALIFICATION.md)，
缺口审计见[FD_CONTINUITY_PREMISES_REVIEW.md](FD_CONTINUITY_PREMISES_REVIEW.md)。

必要核验只消费已保存的真实CPU coverage2：公共回读通过后，该公共同一guard明确
拒绝；audit hook禁止原archive全部logical/local raw路径，打开0次。未构造假Base/
ProgramSnapshot，未导入R1，未跑target。AST对照证明public build/read bodies、旧
schema1版本guard不变，_prepare仅替换guard调用。FD_VALUES_ONLY_R2源字节不变，
数值路由独立，不重跑13k codec或声称它已在本门重新执行。

实验：`first_stage_fd_namespace_quarantine_20261023/`，实际exit0，wall0.72s，
RSS44416KiB。八个owned-launch模块准确匹配原freeze；一次过严要求旧19依赖全冻的
preflight发现共享store已更新，失败保留；随后明确绑定当前store SHA再运行唯一核验，
没有修改store或假称旧字节。原CPU门、producer、staging list均未改。

当前source SHA：`ad34367fa2ee403ad3354920a96481604616e58e0954c2044a00a1230aff42ad`。
拒绝PASS只证明不会由selection推无证coidentity，不表示资源模型完成。
