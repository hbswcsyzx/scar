# 自动source front-end worklist：单新增模块冻结

2026-10-23。Implemented / 待根源码review与实际plan/batch授权。
只新增`scar/analysis/source_frontend_worklist.py`，原6 source/publication文件保持冻结，
没有修改CLI、runtime消费者或__init__。

`freeze.json`保存新模块SHA、完整新增patch、必要import链源码收据。AST、diffcheck与
minimal import/API schema PASS；`minimal_api.py`没有调用planner/worker，也没有读程序图、
源码或CodeType，没有prepare/compile、目标或测试suite执行。

公共API是SourceFrontendBudget、SourceFrontendPlan、plan_source_frontend与
run_source_frontend。planner完整登记所有静态body与当前group，分片写body/group/dispatch；
只有正规kind/完整source+context+definition+CapturedCode+模块compile variant才进入
PENDING_CODE_RESOLVE，不按reason/业务qualname选择。实际READY仅worker通过owned store
完整descriptor核验后记录，当前没有跑实际batch。

worker按file复用原三图/AST/symtable/sealed context与模块缓存；真实lowerer返回立即保存，
operations_emitted、图大小与保守budget charge分开。成功SourceProgram5引用原graph字段，
自然汇出program_paths；unsupported、exception、预算与失败BUILDING原件保留。同输入失败
resume核work key/原terminal result SHA及成功artifact SHA，已有相同终态不会盲重跑。

## 独立metadata勘误

旧`source_frontend_worklist_20261023`投影/设计保留原样。其源码将所有__future__ flags OR后
与captured.flags相与，误将nested_scopes=0x10当future flag；该bit也表示structural
CO_NESTED。生产planner复用既有compile_cache_key，不复制这条错误规则。

`metadata-correction.final.json`给出完整旧criterion→正规key/hash、2个受影响原body/source shard
收据和当前binding行locator；仅读小元数据，未读source/图/marshal或compile。原发布前
快照正确值为79 metadata candidates/2802 calls/15files，missing10/53calls/8files；
705无captured witness/113files不变。10missing有19个兼容optimize备选；每完整请求选最低
recorded匹配optimize再去重，8个preferred keys覆盖8files，不需把19备选都编译。
这些是旧不可变快照的更正，不是后继实际planner的预设数量。后继从新manifest及新binding
机械derive并守恒，module metadata presence仍不等于nested CodeType已核。

原`freeze.json`记录的`metadata-correction.json`保持当时较早无binding locator版本及其SHA；
后补的`metadata-correction.final.json`保持相同计数与keys、增加binding行定位，最终收据由
`final-artifacts.json`列出，历史freeze不重写。
