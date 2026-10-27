# 自动source lookup只读可行检索

唯一probe exit0，4.25s、RSS123,916KiB。无生产改动、target/raw重跑或FD资源gate。
原35端口/R1/R2/coordinates全部保持原样。

- 从35selected ports自动分3groups，生成2个birth Needs，未手填TID或ordinal。
- 2次候选均由公共resolver精确核source/row/result/flags；2个chunk共31,998,744decoded bytes。
- 自动识别1个pre-exec required birth；另1个已有post-exec anchor。
- creator缺自身birth明确frontier，没有捏造记录。
- 没有验证全局source排序/唯一性，未命中策略不得推导不存在。

`needs.json`、`queries.json`、`matches.json`和`frontiers.json`保存实际有限证据，
`producer.json`保存脚本/输入及source-order hint版本。`run.*`保存唯一运行。
当前没有新增生产helper；最小API/限制见`docs/OS_SOURCE_LOOKUP_REVIEW.md`。
下一步实现与自动witness publication等待根审查。
