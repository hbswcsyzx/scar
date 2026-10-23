# OS source自动查询与witness准备

**2026-10-23 correction：positive source查找与continuity资格不同。** 本文两条真实
birth selector/result/flags/Run及自动需求生成结果仍成立；旧gate下游FD contexts的
35个container关联因capture filter遗漏`unshare`/`close_range`而不具备连续性资格。
原artifact不改，当前context reader拒绝旧v1；不再将这个局部门称为container已证明。
见[OS_CAPTURE_COVERAGE.md](OS_CAPTURE_COVERAGE.md)。

2026-10-23。新增`scar/trace/os_source_lookup.py`；未修改R1/R2/core、coordinates或
`os_fd_table_contexts.py`。唯一真实自动化gate已exit0，见末节；全模型仍OPEN。

## 接口与职责

```python
find_os_birth_witnesses(
    base, r2_manifest, *, archive, coordinates, context_events,
    budgets=OSSourceLookupBudgets(), progress=None,
)
prepare_fd_context_evidence(
    base, r2_manifest, *, archive, coordinates, r1_summary,
    projection_summary, projection_files, context_events, fresh_out,
    budgets=OSSourceLookupBudgets(), progress=None,
)
```

接口不接受actor、TID、ordinal、函数名或业务条件。find从原R2实际selected handles、
精确归档/R1 artifact映射、原coordinates thread birth机械生成groups与所有needs。
每个positive match必须经原公共selector/resolver核source、完整row、child result/flags、
parent native thread/process、Run及receipts。native TID不是TGID。

路由仅是启发式：优先稀疏anchor行差，其次可在预算内尝试source-order binary hint。
查询失败只能给frontier，不断言absence、source全局排序或唯一性。默认最多8次查询、
64MB声明wholechunk decoded bytes；每次新resolver调用保守收费，重复ordinal复用已验
envelope，底层继续复用OSResourceBase bounded cache。额外metadata/ports/artifacts也有预算。

prepare内部调用公开find，完整保留所有needs/matches/frontiers。仅当有恰好一个
pre-exec需求且有精确、非共享positive birth时，才发布新context-evidence。
零个、多个、未命中或共享pre-exec的consumer限制均有明确frontier，不补无关birth。

## 原始证据与新envelope

metadata为显式路径，URI只用于严格比对，不按URI任意打开文件。归档必须匹配原
coordinates seed SHA，coordinates必须匹配原R1 protocol receipt；R1 source array经过
公共reader整chunk验证。每个原logical/local URI+rawSHA+bytes+schema完整对应。

原成功exec events只用于需求路由，不授权source match或container身份。真正命中的原
birth row再次由公开resolver核验后才发布。原FD consumer仍会独立重验全部小补集、
原R2选择、raw/flags及selected context关联；本模块不替代这些证明。

fresh输出依次保存`lookup.json`、适用时的`context-evidence.json`、最后的
`preparation-report.json`，均使用有界encoder及O_EXCL+fsync+link，拒绝覆盖。没有最终
report时不能声称整个准备阶段完成。frontier报告可以发布，但不会发布假的witness。

context-evidence兼容既有witness wire shape，producer明确为
`AUTOMATIC_SOURCE_LOOKUP`，引用**新lookup artifact**的精确receipt；不冒用旧手工实验
producer或SHA。原FD consumer可直接消费，旧产物不改。

## 模型边界

没有新IR节点/ID/图或mutable state，没有FD内容、offset、别名、纯性、ready、优化审批
或执行变换。自动查到birth witness也不等于全程序建模完成。当前consumer仍只支持
单个pre-exec witness；后续optional/list扩展单列，不在这个helper中伪装支持。

## 唯一真实自动化gate

实验：`artifacts/experiments/first_stage_os_source_lookup_20261023/gate-attempt01/`。
公开prepare内部调用公开find→机器写新witness→原FD builder→原公开reader→全部实际
record/selected_resource验收，实际**exit0**；wall **17.54s**，RSS **122,308KiB**。
没有修代码、重复gate、target/GPU/采集或百万observations扫描。

- 自动从35个原selected端口分3组、生成2个birth需求；2次精确正命中，收费
  31,998,744decoded bytes。全部需求均报告；ancestor缺自身birth单列frontier。
- 唯一pre-exec witness自动选择并发布，未输入TID或ordinal。新envelope的provenance
  明确为AUTOMATIC_SOURCE_LOOKUP，**6,571bytes**，SHA256
  `ef590b5b38f9ad91a409861a3acbfed1d9ef86de36e591e7d09bd4b73626efbf`。
- 原FD consumer独立通过35containers/3观察contexts；13对pipe仍不同OFD且同container，
  原25selected Work、38access与其它handle字段不变。与此前接受的witness gate相比，
  所选35 HandleBinding及3 ResourceInstance逐record完全相同。
- 新FD manifest为**281,314bytes**，SHA256
  `d37eef5881d25a66c7500be2130b4f7af114586e0b8607f81a36ddd359886d84`。
- 11关键源模块SHA前后匹配；实际98个SCAR imports分别冻结当前SHA，无漂移。
  未将其它source任务的新模块伪称为旧freeze版本。

本次验证了这个保留scope内的witness自动发现、准备及原consumer接线；没有证明全局
source排序/唯一性、搜索未命中即不存在、其它程序全部情况、零/多child分支运行结果，
或完整ExecutionModel语义。后两类consumer保护在代码中实现，但未增加额外测试。
第一阶段完整建模与全路径/状态/副作用覆盖仍OPEN。

此前只读可行检索原样保留在`OS_SOURCE_LOOKUP_REVIEW.md`。
