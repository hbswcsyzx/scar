# 唯一35端口context gate

实际exit0；wall13.67s，RSS188,896KiB。builder→公开reader→全部35实际typed端口/
3实际typed观察context通过，无修代码/重跑，无target/GPU/采集。

`result/manifest.json`：281,281bytes，SHA256
`6084ad77231fd9790bd4706966ceb7d44370f58b3c5d47bcc3b660ca7941ee8c`。
它是原R2选择视图上的固定只读精化，不是另一个可修改的IR根。

- `selected-handle-proofs.json`：35个原R2 ID/canonical preimage、真实原selector/row SHA、
  新container；除container外全部原字段不变。
- `resources.json`：3个role/realm/ImportedAt/FK通过的真实资源，端口分母3/31/1。
- `pipe-pairs.json`：13对双端不同原OFD、同container。
- `work-receipts.json`：原25个selected Work不变；原38access与3executor选择亦未变。
- `unselected-query.json`：原公共reader已证存在、但不在selected registry的资源ID及
  locator；NOT_IN_SELECTED_REGISTRY不被解释为不存在。
- `imported-sources-before/after.json`：本次实际97个SCAR源模块当前SHA，运行无漂移。
  原10模块freeze SHA亦前后匹配；没有把新source模块归入旧freeze。
- `producer.json`、`frozen-implementation.py`：运行前revision/脚本/模块收据和真实源副本。
- `run.stdout.jsonl`、`run.stderr.txt`、`run.time.txt`：唯一运行日志，time footer与外部
  exec均实际exit0。summary中的`actual_gate_exit_expected`只是footer前预期，实际退出
  单列于`completion-receipt.json`。

新模块仍是proof-consuming adapter：childbirth selector由此前小证据提供并独立核验，
其从ports+coords birth自动反查R1source的上游接线尚未实现。完整ExecutionModel语义与
第一阶段仍OPEN，未构造fakeProgramSnapshot、未报告性能优化或加速。
