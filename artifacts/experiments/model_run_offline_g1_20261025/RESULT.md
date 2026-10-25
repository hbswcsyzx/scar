# G1 actual offline orchestration result

Root session9006实际exit0，GNU wall125.90s/RSS872320KiB；内部wall124.585290s。
状态为`COMPONENTS_LINKED_WITH_OPEN`。**本次源码定义0、GraphBodies0、实际尝试body0、
construction operations0；271次调用全部UNRESOLVED，body-linked0、source-only0。**
这是现有公共组件自动接线的实际通过，未验证非空canonical body准入/reader或完整模型。
主生产source858/runtime843及原6699 body-linked calls不变。

## 271调用的实际缺口

| code组 | calls | source-status | 准确归因 |
| --- | ---: | --- | --- |
| `find_torch_dispatch_rule` | 260 | INCOMPLETE | 原project root外；未admit |
| `ExecutionEvidence.__init__.<locals>.importing` | 4 | INCOMPLETE | 原project root外；未admit |
| `Path.write_text` | 1 | INCOMPLETE | 原project root外；未admit |
| `PurePath.__init__` | 1 | INCOMPLETE | 原project root外；未admit |
| `Path.__new__` | 1 | INCOMPLETE | 原project root外；未admit |
| `_Environ.__getitem__` | 1 | INCOMPLETE | frozen/pseudo filename；文件源码未证 |
| `dumps` | 1 | INCOMPLETE | 原project root外；未admit |
| `OpOverload.__call__` | 1 | INCOMPLETE | 原project root外；未admit |
| `<module>` | 1 | VERIFIED | module无definition接口 |

9个完整CapturedCode descriptor及原source-link/anchors保存在RETENTION.json。
269calls/7groups是绝对Python源码文件位于记录的project boundary之外，公共source matcher
保存`SOURCE_BOUNDARY: code filename is outside project root`，未进入dependency admission。
其中Torch `find_torch_dispatch_rule`占260calls；其它为SCAR importing4、pathlib3、json1、
Torch OpOverload1。未读这些源文件，故不声称它们的采集时或当前文件字节已验证。
另外1call的`<frozen os>`属于非文件filename，当前source matcher同样先停在root boundary；
不能据此伪造os.py映射、源码丢失或native内容。剩余1call是586B本地probe的VERIFIED
`<module>`：准确snapshot和compiler descriptor已匹配，但无function/class DefinitionID，
因此保留`VERIFIED_CODE_WITHOUT_DEFINITION_WITNESS`。270不能统归因module。
这9项都是Python CapturedCode；该分母没有证明builtin/native operator的完整调用分母。

source inventory仅1文件/95coverage atoms：86 INVENTORY_ONLY、9 UNSUPPORTED、4 discovery
EXTERNAL_OR_UNAVAILABLE gaps。旧source/control层仍有92 semantic operations、45 CFG nodes/
56 CFG edges/6 control regions；这不是canonical body。composition保留
MODULE_INITIALIZER_BODY_NOT_RECOVERED1、CROSS_FUNCTION_BINDING_NOT_ESTABLISHED1、
SOURCE_CONTROL_GAP2、SOURCE_SEMANTICS_GAP81。source binding9code groups/271enter/271exit，
raw descriptor replay matches9、orphan exits0；source compilation/source match并非9项全成立。
270调用保有RECORDED_FRAME_INTERVAL_MATCH parent资格，1无parent entry；它们不授direct
callsite、actual/formal、return routing、function environment、state effects或ready事实。

下一优先项应为**通用external-source admission/entry接线**（269call的主缺口，含260call的
一个外部Python code），复用`admit_dependency_sources(trace_directory, project_root,
out_directory, *, call_budget, budget, context_budget, progress)`，由matching interpreter/provider
边界和原descriptor机械选择，而不是扩大project_root至任意公共祖先或手列Torch函数。
这仍需root另批预算/接口，不保证269均可接body。module initializer entry的1call是独立
建模接口缺口；frozen1call需精确provider/source合同。此次不改code、不补raw/target或重跑。

## 阶段、成本与预算边界

| 阶段 | wall s | post-check文件数 | 当时attempt累计stored B | 输出解压检查读B |
| --- | ---: | ---: | ---: | ---: |
| capture-import | 121.561873 | 94 | 25,637,755 | 999,064,422 |
| source-coordinates | 0.810654 | 2 | 25,870,331 | 0 |
| source-seeds | 0.424622 | 2 | 25,875,146 | 18,313 |
| source-inventory | 0.583260 | 2 | 25,886,053 | 107,405 |
| source-layers | 0.309280 | 3 | 25,964,731 | 840,089 |
| source-composition | 0.361008 | 3 | 25,975,959 | 40,161 |
| source-bindings | 0.287668 | 6 | 26,238,482 | 1,483,570 |
| workload-witness | 0.042773 | 5 | 26,247,872 | 0 |

capture-import 121.561873s，其余7阶段共2.819265s。
末次post-stage snapshot 26,247,872B；
最后terminal加入后，新attempt stat 26,310,070B，加当前导航root为26,370,476B。
post-stage仅输出解压检查共1,001,553,960B；该数不等于全流程input I/O。

* Metadata planning45,799B包含原导航root1,845B与capture metadata43,954B；规划raw0。
  最后capture metadata重核43,954B。报告本身只读小metadata，未重读bulk/chunks。
* raw64MB分别传每次公共调用；重复coordinate/seed/inventory/binding读取真实存在。
  累计stored+decoded input I/O保持OPEN，没有全局64MB I/O帽。
* record64MB/output128MB为实际post-stage检查，非连续硬上限；检查失败应保FAILED partial。
  本门未触发超限。180s由root外部timeout；默认calls256仍保留，本门显式512。
* workload CodeWitness新archive1compilekey、586B source、1455B marshal，writer
  complete_descriptor_matches1；只读重开module_loads1/matches1/compile0/source_read0。
  未借collector archive；这些archive keys不计数其它source matcher的离线compile工作。

## 原门、导航root与OPEN

原G0 session63296 exit2/BLOCKED：271declared calls超过256，4个metadata43,954B/raw0，
原attempt文件全部保留。G1使用--resume创建全新attempt，不复原serialized ownership或
重写旧terminal。唯一当前`model/model-run.json`是可更新导航；G0旧导航字节已保存为
G0_NAVIGATION_BEFORE_RESUME.json，各attempt started/terminal仍不可变。

G1 root SHA `1cfaab57341b132b715e5aaab3bfac4d5c0a72efc892cdaefccf122b838340b6`；terminal SHA `a61b3d1ba30e9411aed726a882253aa92b5682a5872fdcf889326e55983433e0`；
360-source freeze SHA `9a84d54248e1713c9def8f5fee6b77ce4be396c839262e17a0757857e3d1ba0e`（root另持独立source hash对照，不冒用其未来结论）。
原Run被capture/source两个普通coordinate binder精确保持。root只链接原规范产物，
whole_model_established=false/target_executed=false；没有新graph authority、CP1或source2/3。

最终root的open文本沿G0规划，部分仍写“await public checks”；应结合completed stage
receipts读作历史规划frontier，不能说G1未执行coordinate/source discovery，也不能因此
关闭source coverage债。target exec cwd/command entry、collector历史实现/持续mutation、
external source entry、module body、Python↔Torch occurrence、content/state/object identity、
ready/resource completeness、nativeV2/统一scope ledger均未闭合。入口成功不等于phase1完成。

RETENTION.json与STAGE_PATHS.txt列出小文件和全部bulk精确local receipts。本报告没有重解
native/OS/bundle/chunks，也没有执行producer/target/新测试或Git。所保metadata依赖原CAP、
原URI/source namespaces及local bulk/库；不是可脱离这些依赖的完整可搬运模型。
