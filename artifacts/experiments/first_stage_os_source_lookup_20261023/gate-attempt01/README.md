# 唯一自动witness→原FD consumer gate

实际exit0，wall17.54s，RSS122,308KiB。未修代码/重跑，无target/GPU/采集/百万表扫描。

自动链路：prepare内部调用公开find，从35原端口自动分3组、生成2个birth需求；2次
精确正命中（31,998,744charged decoded bytes）。唯一pre-exec需求自动生成新envelope，
新producer明确AUTOMATIC_SOURCE_LOOKUP，没有手填TID/ordinal或冒用旧手工producer。

- `automatic-witness/lookup.json`：完整groups/needs/matches/queries/frontiers与输入SHA。
- `automatic-witness/context-evidence.json`：6,571bytes，SHA256
  `ef590b5b38f9ad91a409861a3acbfed1d9ef86de36e591e7d09bd4b73626efbf`。
- `automatic-witness/preparation-report.json`：整个准备阶段的最后发布报告。
- `result/manifest.json`：281,314bytes，SHA256
  `d37eef5881d25a66c7500be2130b4f7af114586e0b8607f81a36ddd359886d84`。
- `selected-handle-proofs.json`、`resources.json`、`pipe-pairs.json`：35实际typed端口、
  3观察context、13对pipe不同OFD同container；除container外原handle字段不变。
- `work-receipts.json`：25原selected Work、38access与3executor选择不变。
- `unselected-query.json`：确有原base ID未selected，不将查询coverage当作不存在。
- producer/frozen source snapshots/imported-sources记录本次实际字节；11关键SHA匹配，
  实际98个SCAR源模块无漂移，不冒充其它source任务的旧版本。
- `completion-receipt.json`单列实际exit0；summary中的expected字段只是footer之前预期。

本次新typed selections与此前接受的35端口/3context gate逐record完全相同，变化是witness
发现和准备已机械完成。ancestor无自身birth仍frontier；全局排序/唯一性、零/多child运行
分支、其它程序全部情况、完整ExecutionModel语义都没有由本门证明。第一阶段仍OPEN。
