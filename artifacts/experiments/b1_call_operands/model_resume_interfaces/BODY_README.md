# C2B resumable-body 补充证据归档

本目录的原 `README.md`、`manifest.json` 和 `check_review.py` 保留 `b4bc1a4` 架构
研究的原范围。这里的body组件使用独立 `body-manifest.json` 与验收记录，不改写
或沿用早期23组动态观察/4种静态shape/设计探针来证明新产品实现。

实施提交：`e6b47239c874b179416b2ed5a37bd0bd07b5d2b7`。
最终组件：**499 PASS / 7.077s**，7项标准全部通过，403个源文件哈希前后相同。
冻结全仓：**3,542 PASS / 432.922s / 1,030,184KiB**，零失败/错误/跳过，三条既有
warnings；前后HEAD/clean/source/26份fixture相同，自建basetemp已清理。**C2B
静态body组件PASS；完整C2与第一阶段未完成。**

## 证据位置

- `body-component/final.json`：逐标准/逐测试映射、完整命令/输出与测试源指纹。
- `body-full/`：单次冻结全仓命令、包版本/环境、时间/RSS、JUnit与每项结果、
  HEAD/clean/source/fixture前后快照，以及仅清理自己basetemp的回执。
- `body-records/`、`body-wire/`、`body-graphs/`、`body-forwarding/`、`invoke/`：各
  独立实施者的定向记录，含初始失败/补正；这些历史源状态不替代最终组件/全仓。
- `review/body-contract-review.md`、`body-integration-audit.md`：冻结字段与core接线审查。
- `review/body-adversarial-repro.py/.log`、`body-adversarial-review.md`：F1合法同源
  frame alias被错拒的实际复现；修复前后两个回归在`body-forwarding/`。
- `review/driver-root-review.md`：下一批driver提案的只读复审，不是新增实施能力。

核验完成归档时运行：

```bash
conda activate lewm
python artifacts/experiments/b1_call_operands/model_resume_interfaces/check_body_evidence.py
```

该核验只读报告和哈希，不重新运行pytest、LeWM或GPU采集。

## 范围与失败判定

body的四表、专用Suspend与槽投影、cut availability、current state、上下文附着/
卸载、同一次C1 activation和BOUND局部恢复均连接到同一canonical producer/Use。
manual IR声明及静态结构通过，不代表Create/driver/实例代次/原子互斥、真实异常
上下文、frame release、源码自动建图或变换已验证。完整C2.0/C2.4和第一阶段未关闭。

F1是已确认产品误拒：一个FRAME保存槽导入多个局部formal。最小修复保留同源
aliases，Attach精确选择其一，caller唯一参数及普通逃逸规则不变。其他初始失败
含测试字段/selector/helper拼写和guard隔离错误，均保留原日志，不计作产品漏洞。
caller经INVOKE逃逸的静态疑点被真实正反例排除，报告没有把怀疑写成已发生漏洞。

未新增LeWM规则、detector或backend；无LeWM自动变换/clean A/B加速结论。受保护
原仓与主工作树状态在`body-component/protected-checkouts.json`中记录。
