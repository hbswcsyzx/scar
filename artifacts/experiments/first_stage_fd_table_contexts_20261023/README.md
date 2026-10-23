# FD-table context窄模块：静态冻结

本目录保留原static freeze历史；后续唯一真实gate在`gate-attempt01/`，已exit0，
13.67s、RSS188,896KiB。新生产文件仅`scar/trace/os_fd_table_contexts.py`，既有
R1/R2/core/coordinates/import/CLI均未改。

API/schema/限定证明与partial registry见`docs/OS_FD_TABLE_CONTEXTS.md`。
freeze.py只用标准库AST/SHA和read-only Git revision，不执行任何SCAR代码。
static-freeze.json保留新模块与冻结依赖的原字节版本；它本身不是35端口实施验收。
全部35端口/3观察context的真实验收见gate目录及`docs/OS_FD_TABLE_CONTEXTS.md`第6节。

完整建模仍OPEN：该模块消费此前提供并独立核验的childbirth witness，上游自动发现未
完成；本次只精化已知端点container，没有新target/GPU/采集/优化。
