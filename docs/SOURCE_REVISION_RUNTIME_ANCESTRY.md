# Revision后复用source membership：最窄runtime接线设计

**2026-10-25 实际集成补充：** 843快照的fresh联合门已exit0，private factory、
ANCESTRY_V2安装及source/dispatch/SBA公共消费均实际运行；depth2、严格compiler
inventory等式及新namespace均核过。准确结果和有限范围见
[实际报告](../artifacts/experiments/first_stage_source_revision_current_review_20261025/RESULT.md)。
以下保留原设计起点及当时的未运行状态，不作为最新终态。

2026-10-23。**Implemented / 当时真实ancestor query与wrong-ancestor拒绝Verified；private factory/current绑定待运行。**
前置门`first_stage_source_body_revision_20261023`已PASS：ADD218+REVISE65发布为843 active
bodies；下一步只把此已完成batch接回同一既有capture，不重新lower/compile/执行目标。
实现门见 `artifacts/experiments/first_stage_source_membership_ancestor_20261023/README.md`：
真实depth2/两个parent各parse一次，重复query与错误ancestor不新增parent解析；raw仍未读。

## 精确断口与保持不变的条件

`SameRunSourceProof.require_composition`当前对composition3只接受立即parent canonical
SHA等于原source report的composition SHA。新revision的立即parent是原842-body comp3，
而现orchestrator的`previous_source_directory=OLD/result/source`来自更早comp2。原source
报告匹配这个真实ancestor，不能匹配立即parent。

**仍保留 `origin.inventory == priorReport.inventory` 的完整dict严格等式。** 原compiler
origin与OLD source报告都属于原manifest1。没有必要改用较新的manifest2报告，更不需要
为过门放宽compiler origin。当前Run/current raw独立核验、source attachments完整收据、
project root、完整CapturedCode与SourceDefinitionReference membership检查全部照旧。

当前正式parent链为：revision comp3/publication2 → 842-body comp3/publication1 → 原comp2。
这是可从实际parent receipts追溯的关系，不是按文件名、qualname或RegionID文本猜等价。

## 唯一新查询接口：正规source membership ancestor

建议由`CompositionIndex`提供：

```text
require_source_membership_ancestor(expected_composition_canonical_sha256,
                                   expected_inventory_receipt,
                                   max_depth=16,
                                   max_total_decoded_bytes=1_000_000_000)
  -> original ancestor + verified parent-step receipt
```

这只是已存snapshot来源查询，不是另一份图或一个可自证True的cache。沿实际
parent_composition和publication.base_inventory成对检查：

1. 当前文档未变；每步parent stored SHA/size、decoded size/canonical SHA按原receipt核定。
   parent实际inventory receipt必须等于该publication的base_inventory；parent canonical
   SHA必须与该publication已声明/实核的值一致。inventory parent也须为同一个原件。
2. source_layers完整ref、151source文件的有序snapshot/context向量及project root不变。
   SourceDefinitionReference引用的原source archive/namespace仍原件；graph attachment
   的revision不能当成source/provider artifact发生变化。
3. original_code_source_origin完整dict保持不变。找到的ancestor canonical及inventory
   必须同时等于原report声明；找不到、cycle、深度/字节超限全部拒绝。
4. 仅返回原refs/校验路径和范围；不返回旧body为typed合法，不返回旧activation/Use route。

优先复用现`_verify_parent_composition`流式SHA/解压验证与有界`_read`。每个parent index
最多解析一次，提取小metadata/下一parent后释放，不实例化新的CompositionIndex来再次
触发body revision会计，也不解840PG或105依赖source图。解析前按declared decoded bytes
核累计预算；已有canonical字节SHA验证可复用，不必反复序列化大composition document。
若后续实现正规小metadata分片/SQL索引，可在保持同样receipt校验下替换这个读取路径。

结果可在**这个已绑定CompositionIndex实例内**按current canonical+expected ancestor完整
收据保留，供同一次factory/install/accessor重复核；输入/模块/文档变化即不能使用。它
不替代现私有SameRunSourceProof构造，也不允许外部传一份声称已核的dict提升权限。

## runtime proof的最小变更

`current_source_evidence.SameRunSourceProof.require_composition`只用上述正规查询替代
立即parent SHA比较；origin.inventory严格等式、attachments完整相等、project root和
当前owned scan验证保持。receipt增加版本化的`source_membership_ancestry`原ref收据，
明确只复用静态membership。若outer proof rule随新字段升级，应显式换规则版本；旧
source报告仍按原schema3读取，不把旧已完成checkpoint当成新版本输出。

`connect_current_capture`无需新raw reader或新graph：仍用既有原OLD source报告与其固定
producer/participating-producer输入，从当前raw独立read一次后构建私有proof，安装
exact SameRunSourceProof，再运行现source binder/dispatch/SBA。

本次必须`resume_source_directory=None`：pre-revision完成的source report绑定旧inventory/
composition和旧body namespace，不能作为新snapshot的已完成source checkpoint。可复用的
是原完整source definition membership、编译来源和同Run source guard收据；实际body
attachment、RegionActivation、formal/return/environment Use引用必须按新snapshot重派。
bare RegionID相同不授权复用旧namespace的activation。新绑定的原始InvocationKey仍来自
这次current owned raw，不能从历史source报告复制动态事实。

## 最小待改文件与统一门

- `program_composition.py`：正规ancestor查询、独立预算及实例内小收据复用。
- `current_source_evidence.py`：替换一个立即parent前提，明确receipt rule版本与guard范围；
  private factory/current scan/producer来源检查不放宽。
- 如receipt规则有枚举/严格字段消费者，只做明确新版本兼容；SBA新revision cap分支已
  在发布门实施，不能用假schema8或改full canonical graph来绕开来源。

root审查后再集中一次验收：使用已发布843 snapshot、同369749 capture、原20-key readonly
store、原OLD source proof输入和原dispatch bridge。fresh raw读取一次供source/SBA共享，
完整817 groups/100438 calls及operand/environment原分母守恒；每种新/旧namespace的实际
引用范围检查，明确未解析source、无handshake、generator creation/drive等原缺口不丢失。
不为每个body分别扫100k，不重lower/prepare/compile，不重放目标或GPU workload。

必要拒绝仅核一个不在链中的ancestor SHA/库存receipt；另核旧source checkpoint不能以
resume形式用于revision。可用小receipt负例，不加测试suite或改raw facts。发布门的
65/218 source/port/tuple-raise验证不因此升级为完整lifetime，更不产生优化合法性。
