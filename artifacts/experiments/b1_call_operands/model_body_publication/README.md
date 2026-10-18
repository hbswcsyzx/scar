# D2.1 body publication实施与自主验收

2026-10-18；规范合同见docs/M1_DRIVER_LIFECYCLE_CONTRACT.md。
实施冻结 `49201e7390e3feea9bfbc70d3336daefaf8e4b4e`。

终态：741组件/17标准与冻结3,776项全仓通过，零失败/错误/跳过，三条既有warning。
全仓459.570s、峰值RSS 1,028,440KiB；HEAD/clean/423源文件/32fixture前后一致。

## 范围与实际交付

本门仅DriverLifecycle、DriveOutcomeRef、BodyOutcomeCommit及两张ProgramGraph表，
连接D1实际source边、private landing首操作、owner Use/copy与当前StateAccess/after。
严格v12保留旧v1–v11字节；query返回原record/UseSite/access/state结果，CLI只报告声明
publication结构。完整NoBody/Session/drop/E/F/P产品及D3仍未完成，不授runtime或transform。

## 分母与保留尝试

- records/：6项constructor/role检查首次通过；原命令与log保留。最终仅规范化该新测试
  文件的EOF空行，产品代码与断言不变；实际冻结字节以component/final绑定。
- graph/：root的48种手工IR组合同时require_valid+wire往返通过；25项graph tests首次
  PASS/0.60s。手工fixture不算自动建图。smoke最初以stdin执行，另存的命令/脚本是
  从实际exec输入恢复的可重放文本；不冒称当时已有可独立绑定的脚本hash。
- codec_queries/：首跑38PASS/1FAIL是proof字段名测试沿用了另一份旧proof，不是wire
  失败。按真实历史proof改测试后39PASS/1.49s；产品与golden未为该失败修改。
- historical/：v11 golden从immutable38d2968 git archive独立生成，确认历史codec路径
  与max版本11，64,700 bytes。首个archive命令误给不存在tests/__init__.py，未生成
  fixture；初稿/错误记录保留。修正后运行隔离历史源码，独占临时目录清理。
- review/：独立有界接线复审。首9项中8项得到预期结果，第9项工厂误将3域解包为2域；
  保存原脚本/输出，仅补跑该一项，得到W=1且省略2个READ仍合法。没有产品修复。
  source错接、两个same-owner formal、foreign Use、坏nested metadata均有实际结果。
- component/initial：741项/17标准/10.799s；EOF规范化后final为741项/17标准/10.937s。
  两次不合计独立覆盖，focused/组件/full均有重叠。
- full/：冻结实现单次pytest tests，保存exact命令/环境、JUnit/cases、source/fixture
  前后清单、时间/RSS及独占临时清理；最终状态/计数以acceptance.json为准。

最终source/gate/test为423文件，指纹
`467f6443c4847d28ed773b8fc7c37a1e559d62eb4f7afd5a5a841cf1f9064773`。
旧29份fixture保持，新增publication工厂及v11 wire/proof，共32份。
全仓耗时仅为验收成本，不是LeWM wall-clock或speedup。本批没有LeWM/GPU新profile、
大Tensor值保存、新detector/backend、source lowerer或runtime adapter。旧测试的执行
内容以原case记录为准，不能冒称D2真实native实现已验证。

只读复核既有证据，不重新执行实验：

```bash
conda activate lewm
python artifacts/experiments/b1_call_operands/model_body_publication/check_evidence.py
```
