# 通用OS source自动查询：实际资源接线

唯一生产新文件`scar/trace/os_source_lookup.py`；旧R1/R2/core/coordinates/FD consumer均未改。
`static-freeze.json`保留AST阶段11个Python模块版本；后续真实运行在`gate-attempt01/`。

唯一gate实际exit0，17.54s、RSS122,308KiB；没有修代码或重跑。
自动find→prepare新witness→原builder/publicreader→35containers/3contexts通过。
没有手填actor/TID/ordinal，没有target/GPU/采集或百万表重扫。

source-order仅查询启发式，未命中只能保frontier；零/多pre-exec需求的旧consumer限制保留。
本次只验证实际单required-child路径，完整模型仍OPEN。
API及结果见`docs/OS_SOURCE_LOOKUP.md`，只读设计历史另见`OS_SOURCE_LOOKUP_REVIEW.md`。
