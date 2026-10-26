# Continuation source-entry publication：schema3接线

只改 `scar/analysis/source_program_publication.py` 与 `program_composition.py`。隔离树原两源与main f946基线不等，已保存双方原字节/SHA并仅将这两源同步到已核main HEAD；基线分别为 `21a99ab7…e53b`／`c0addde6…3cb9`（完整值见BASELINE）。原GPU V2两文件脏改保留，不覆盖、不混stage；main/index不改。

**显式API：** `plan_source_entry_publication(..., publication_version=3)`输出schema3 plan，`publish_source_entries(..., plan=...)`沿该明确版本输出schema3。默认plan仍schema2，无plan仍schema1；schema1/2继续只收原direct-admissions。schema3允许原direct owner及普通 `SourceAttachments(continuation)`，不把continuation重写为direct。

**完整输入和CAS：** 沿现catalog_inputs保完整owner.receipts（exact report locator、真实parent locator、format、原计数）、archives/project/source_inputs；schema3还核continuation原parent字节／locator未变。parent composition／original compiler basis、qualified definition/namespace、原source snapshot/context、ADD或REVISE的expected_parent_body及旧ABI全部沿原机制重算。外部条目没有fi/bi；CP2仍construction-cost UNKNOWN，不造CP1、终态或新graph。

**普通reader/factory：** `CompositionIndex.from_source_entry_publication`显式识别schema3，只对已知精确format选 `SourceAttachments.from_admissions` 或原continuation构造器，再逐项比完整receipts；未知format、半parent、错误report schema、篡改parent/source_inputs、错namespace／CAS拒绝，不catch后fallback。schema3和schema2的parent overlay链可按原reader递归，保存父namespace、旧typed查询和compiler origin，不把catalog原project view改为overlay。

**查询I/O合同：** 已确认原parent为1520506B（continuation元数据2026468B）。完整parent SHA/locator核验留在plan/publish及factory正常reader；factory在完整核验前后绑定一致的dev/ino/size/mtime_ns/ctime_ns到原watched，普通查询只核该stamp，不重复读parent JSON、不memo授权布尔。原4字段watch保持兼容；原SourceAttachments读取report的legacy策略不在本两源扩展内。这是现immutable-local-artifact约定，不是连续全局防篡改证明。

**资格边界：** 只补可被通常factory回读的静态SP5出版链。旧272038 continuation descriptor/source证明不授当前369749调用、FunctionObject、environment、effects或ready；原SameRun／v4/v5 guard不动，不修改source_invocations或CLI，不把旧权重当动态BODY_LINKED。

**验收：** 本步只syntax/import/API小核及精确对main基线diff。后续由Root安排一次自动选择外部body的完整链：普通catalog→正常readonly compiler/archive→保存SP5→schema3 plan/publish→普通CompositionIndex factory→qualified typed body/signature/admission查询；保817/100438原分母及所有未支持项。source/report/parent或CAS唯一真实篡改负例由该整链门处理；不重lower现15个project图、不compile/执行目标、不堆微tests或冒旧terminal。真实门前本步不读取大graph/raw、不创建qualified成果。
