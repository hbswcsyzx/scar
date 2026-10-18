# D2.1：body outcome publication组件

2026-10-18；依据[冻结合同](M1_DRIVER_LIFECYCLE_CONTRACT.md)§2–3及§7。
**已实施，741项组件/17标准及独立有限审查通过；冻结全仓终态尚待归档。**
本门是静态声明接口，不是完整D2、自动source恢复或运行时生命周期证明。

## 1. 实际连接及代码

```text
DriverLifecycle → 原DriverInterface及其L⊆D
BodyOutcomeCommit → 原BodyDrive、确切source边、私有landing首操作
                  → 原owner Use / 精确edge copy
                  → 原StateAccess.before → 实际after
```

`lifecycle.py`仅三种frozen records；ProgramGraph只增加driver_lifecycles和
body_outcome_commits。不预加未接线的NoBodyFinish、SessionUpdate或release表。

`lifecycle_validation.py`在core/C0/C1/C2B/D1通过后检查完整有限source覆盖、
scope、首位置及owner关系。publication的实际非空写集W⊆L，不强制W=L，
未写域保留current；只读没有伪造after。它允许coarse owner、L≠D、W⊊L、
直接dominating owner与独立edge→formal转发，不猜唯一Create。
Suspend/Return/Raise含义取自真实source，metadata没有可写phase或session后置。

核心BRANCH docstring明确既有两前端的edge0=true、edge1=false约定，wire未改。
后续no-body检查将引用核心真实边，不加可冲突的第二份polarity。

## 2. 严格wire及公开查询

两表的显式能力使用schema v12；旧v1–v11字段集不接受新表，包括空字段偷带。
无新能力的旧wire保持字节。v11 golden独立来自immutable `38d2968`的git archive，
隔离cwd/PYTHONPATH，确认codec文件在历史目录且max版本为11；64,700 bytes，
SHA256 `2342e990c70ce43a1363db82dd5de4d313ce27f8f3acb05ea6ba3e3df9d3e26a`。
生成首败是archive多给了不存在的tests/__init__.py，原脚本/错误保留，未生成fixture。
修正后仅使用历史codec，未使用当前v12代码制造期望；独占临时目录已清理。

```python
index.driver_lifecycle(region_id)       # 原scope record，非runtime证明
index.body_outcome_commit(operation_id) # 原commit record
index.body_publication(operation_id)    # 原UseSite/access/after及源outcome
```

BodyPublication不复制producer或world。PublicationAccess.READ的after=None，
READ_WRITE保留原StateVersionValue与OperationResult身份。CLI只增加
body_publication_structure_validated与两表计数；driver_lifecycle_verified、
source/runtime/exclusivity/transformation标志均不升级。

## 3. 自主验收与原始尝试

门：`gates/m1_body_publication.json`，17项标准/741个唯一test case，最终10.937s；
423个source/gate/test文件前后指纹相同：
`467f6443c4847d28ed773b8fc7c37a1e559d62eb4f7afd5a5a841cf1f9064773`。
包含原D1/C0/C1/C2B/native回归，不把重叠suite相加。

- records首次6PASS。
- graph首次25PASS/0.60s；另48个手工IR组合require_valid及wire往返通过，不算自动建图。
- wire/query/CLI首次38PASS/1FAIL，失败仅因测试读取了不同历史proof的字段名。
  按真实proof字段修正测试，产品/golden不改；终态39PASS/1.49s。
- 综合组件首次741PASS/10.799s；规范化一个新records测试文件末尾空行后，最终
  741PASS/10.937s绑定准确源字节。两次不合计独立覆盖，原记录均保留。
  独立有限审查通过多source错接、双owner formal任选、
  W⊊L省略未访问域、foreign Use及坏metadata不崩溃；九项中首跑八项得到预期，
  一项脚本错误将三域误解包为两域，保留原失败、仅补跑该一项。产品未因审查改动。
  六个被审文件哈希前后一致。单次冻结全仓结果后续在此补齐。

原始脚本、失败、命令、环境、组件及全仓证据在
`artifacts/experiments/b1_call_operands/model_body_publication/`按实际范围归档。

## 4. 后续与明确界限

D2.0已给E/F/P两阶段派生合同及小型方程见证；**这些算法尚未接入产品**。
本门只接publication。D2.2实现真实predicate/BRANCH/no-body，D2.3接session与窄drop、
多锚和状态失效，D2.4完成组合；D3核全family及actual适用。

无新detector/backend、Tensor快照、LeWM profile或clean A/B。没有新的LeWM加速比。
新state、完整effects声明或typed规则都不证明实际native字段、owner/generation、
guard执行或变换合法。完整M0–M2和第一阶段保持未完成。
