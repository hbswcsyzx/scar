# P3 冻结回归失败与版本边界修复门

2026-10-18。原实现`61db593fddbec479d27fa4a46594f62140625788`的唯一一次
`model_body_occurrence/full`真实结果为**5,816通过、6失败、0error/skip**，
562.467s，峰值1,030,792 KiB。全部668注册源前后指纹一致：
`43549a160f4e11005af314efa492659832b7e14f060c72b7caa9e8ab9a308ea9`。
**P3尚未通过；不得覆盖原full或自动重试。**

## 1. 观察与原因

六失败来自三个文件、两类陈旧断言：

| 原case | 实测失败 | 修复所需保持的合同 |
| --- | --- | --- |
| `test_execution_production_codec::test_schema_version_six_remains_unsupported` | 仍将8与bool/string一起当作unsupported；v8现为明确支持能力。 | 旧production自动wire仍5；显式8应roundtrip，9/bool/string仍拒绝。 |
| `test_program_admission_codec::test_sixth_variant_roundtrip_preserves_original_uses_and_branch_without_fake_inputs`两变体 | 跨层断言Execution最高版本必须为7。 | Program新predicate仍准确18，旧execution golden仍准确7且字节不变；最高版本与选中wire分开。 |
| `test_program_protocol_codec::test_f_capability_roundtrips_scope_only_and_n_r_port_graphs`三变体 | 同上。 | 原F Program仍准确17；原execution v7 wire不随最高能力改变。 |

先前兼容搜索只覆盖部分execution codec文件，遗漏production循环以及Program
测试里的Execution别名。组件分母也未包括这三个文件。这是收口审计遗漏；
原组件通过不能否定完整回归失败。不能仅把失败标为测试问题就宣告产品通过。

## 2. 最小修复与自主验收

1. 保留全部原case身份及fixture字节；只迁移上述能力边界断言，不改产品行为。
   Program端保最高Execution支持7，同时实际加载/重编码独立v7 golden，核准确
   version7及原bytes；v8最高版本准确性仍由原P3新能力测试核对。
2. production旧case同时验证原自动v5、显式v8完整roundtrip和future9拒绝；
   bool/string及新字段不能进入旧wire的反例继续保留。
3. 将三个受影响文件共89个原case并入最终定向和原18标准组件。预期255定向、
   606组件；这是被真实失败要求的范围，不删减O01–O16，也不新增模型能力。
4. 独立只读复审所有执行版本引用；干净修复提交后只运行一次新的`repair/full`。
   所有作者停写，无并行SCAR测试/工作负载。原`full`保持FAIL，不能改名替换。
5. 新full通过后，核原5,676与首次5,822 case身份、92旧/99当前fixtures、668源、
   保护目录及两次full各自manifest；归档/commit/push。若失败，留证再审，不自动重试。

修复成功也只关闭P3声明发生关联门。P4/P5、原M2分母、完整M0–M2、自动LeWM
建图/化简和新的clean A/B加速比仍未完成。下一门只读审查不充当本门运行证据。

## 3. 修复冻结前检查点

89受影响case通过；最终255定向/17.29s、606组件/18标准/23.852s通过，
668源前后指纹一致：`b16a1bac16f134c69133f2b0f88a1c291fa0029f9714e95693ae0bdec233f3d4`。
独立只读复核无阻断；`scar/`相对初始实现零修改，旧fixture和case身份未改。
本检查点仍不授P3通过，后续独立`repair/full`必须真实完成。
