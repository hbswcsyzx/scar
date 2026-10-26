# 原证据路径恢复及续跑隔离

2026-10-26。Root归档时执行Git操作，原cone sparse checkout移除了正在被隔离
source209门读取的主树证据文件。这是工作区管理错误。原门48283实际exit1，准确
63 SUCCEEDED/49 UNSUPPORTED/17 FAILED/80 PENDING；17失败均为同一原continuation
文件不存在。原终态及全部结果未改，不通过恢复原件追认旧门成功。

## 实际恢复

1. 保留原sparse patterns，以及原1865个已物化tracked文件；改用non-cone精确文件
   模式，持久保留所有当前物化文件及本次冻结要求的526个主树input/graph路径。
   set实际exit0，原已物化文件丢失0、必需路径缺失0；见RECOVERY.json。
2. 原446个input逐size/SHA全部一致，实际读取19,838,310B；99个selected graph路径
   存在，恢复阶段未解码或核其语义，见ORIGINAL_INPUT_SHA_CHECK.json。
3. 新准备的普通owner还要求完整106个图声明存在，另7个未selected原图也从准确Git
   blob恢复并持久保留；合15,586,802B压缩字节，与原声明size和Git原blob完全相等。
   未解这7图，见OWNER_FULL_DECLARATION_RECOVERY.json。
4. CodeWitnessStore继续要求私有归档权限。仅对新准备所列242个当前用户的恢复
   归档路径收紧权限（3目录700、239文件600），没有改byte/URI或降低owner检查。
   其准确before/after及SHA收据保存在source209-model的resume01准备目录。

Git完整保留每个原件的身份；没有搬迁GraphID/namespace，没有覆盖LeWM或其数据。
原cone模式不再用于这些依赖。后续任何稀疏规则调整必须保留正在被运行读取的所有
路径，并在执行前核对影响，不能只依据代码worktree隔离就认为artifact已隔离。

## 独立后继

Root已检查新97键严格等于原17 FAILED+80 PENDING，原112终态以及更早33终态不重算。
新门为source209-model/artifacts/experiments/source209_resume01_20261026，Root
session6064实际启动；freeze `5628099e686664e3ebc62d744224d3b75ab29cd22544540cd18f4f476db4ab03`，
run `81abd81c7bb7701f5ceaf5bf63334769dcf2cd1275e638b4932eb81704db8b71`。
其新物理stat、源/runtime/输入清单独立冻结；旧freeze/runner/terminal/图均不改。

这只恢复分析所需的证据与可靠执行条件，不是新body准入、当前调用覆盖、LeWM
执行或优化结果。第一阶段仍OPEN；后继结果必须等实际终态和正常读回验收。
