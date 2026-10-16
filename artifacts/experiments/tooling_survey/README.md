# T0：现成工具复用调研证据

2026-10-16。**调研交付；不是 adapter 实现、M1/M2 全门或第一阶段建模完成。**

设计文档：`docs/TOOLING_SURVEY.md`、`docs/MODELING_INTEGRATION.md`。
产品源码仍为冻结 d5311a6 的339文件指纹
`7c2a655a57eb8cdaaf11b0333755852e9dd7b5ecc6f4fc088d2c4e6a0caea3cd`。
源码没有改动，因此不重复跑已完成的2,686项全仓回归。

## 证据分组

| 目录 | 实际工作 | 不代表 |
| --- | --- | --- |
| python_frontend | 标准库 parse/compile/scope/code 的6项检查；临时解包固定LibCST1.9.0的5个parse/roundtrip/metadata样本。 | 全程序依赖恢复或全部LibCST构造验收。 |
| visual_fx | 本机FX CPU probe；torchview/torchviz原仓库与固定revision审查；probe复跑JSON一致。 | torchview/torchviz本机兼容实测。 |
| export_dynamo | 9组CPU观察，包括预期unsupported/guard/alias失败；初始serializer/shared-state错误保留。 | 成功export即纯性/等价性；GPU或LeWM结果。 |
| runtime | 小CPU ETO+Kineto、sys.monitoring；34对正record ID匹配；原始小trace与分析。 | GPU因果、logical version、采集开销或优化加速比。 |

每组probe有自己的版本/命令/输入/范围；不将这些不同分母相加为覆盖率。
`python_frontend` 命令（worktree root，conda lewm）：

```bash
PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/tooling_survey/python_frontend/probe.py
PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/tooling_survey/python_frontend/libcst_probe.py
```

已有证据需保留，不要直接重跑覆盖；复现时复制到新的专属实验目录。
LibCST wheel从PyPI下载并核验SHA，在专用TemporaryDirectory中解包，退出删除，
没有pip安装/更新conda；wheel URL/filename/bytes/hash见libcst-result.json。

## 独立审查与关闭

- Export/Dynamo审查指出三个合同问题：变换表示与原Region混同、lifted state缺少
  实例/本次版本约束、guard失败过度泛化；root已修，`export_dynamo/closure.md`
  确认三项关闭，保留原review。之后survey只补充CUDA构建标记和已有FX实测摘要，
  未改变这些设计接口；当前最终文档由acceptance.json与MANIFEST.json绑定。
- runtime审查未发现对应/范围/成本的实质设计阻断，建议nsys仅写PATH未找到，已修。
- visual/FX reviewer只读核对两文档，未发现实质问题；CUDA措辞建议已修。

M2语言协议的原审计及G1—G6限定修复另在
`artifacts/experiments/b1_call_operands/model_stage1_audit/`保存。该文档审查不充当
工具适配器测试，也未把旧184/12历史结果改为“当时全通过”。

## 归档范围

本包只存小probe、结果、原始小trace、报告、来源URL/hash和审查。
runtime本地下载的第三方完整C++源码仅为ignored审查缓存，不进入Git；
可按official-source-manifest.json中的固定commit URL重新读取并核对hash。
没有新增LeWM profiling、GPU实验、backend、detector或完整Tensor参数快照。

## 自主验收

T0的工具能力/版本/边界调研已完成，设计高/中问题已限定关闭。按本轮文件清单
核对链接、报告hash、最终源码指纹与LeWM clean状态，结果入acceptance.json。
下一步仅在第一阶段继续完善模型与provider字段映射/校验合同，之后先汇报讲解；
新adapter集成、全程序建图和化简属于后续阶段，尚未验收。
