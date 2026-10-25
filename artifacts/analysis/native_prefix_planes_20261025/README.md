# 原生端口资格在真实前缀中的区别

Observed：只统计中止门已完成的20个分片、原sequence 1..5120；不是完整39796次调用。
来源为31198ff9保留的port qualification产物。全部60个输入的receipt与该commit中
terminal-output-inventory一致；没有恢复owner或重放native资格证明。

| 独立项目 | 端口数 |
| --- | ---: |
| 原生Tensor端口已建模 | 11430 |
| 有Python held对象见证 | 11365 |
| 无Python对象资格 | 65 |
| 几何已接原region/allocation | 10664 |
| 有对象见证，但原allocation birth资格缺失 | 701 |
| native-only且无held physical slot | 65 |

这组实际差异说明对象、原生端口和存储资格必须分开。701项不能因为知道Python对象
就补造allocation；65个native-only端口也不能因为缺Python对象而从端口分母删除。
没有据此判断内容版本、alias、效果或ready，全部D项仍为CONTENT_STATE_READY_UNPROVED。

query.py只读已保留的qualification rows：40490465字节、60文件、0.410秒；无raw/数据库/
目标运行。结果是原资格声明的统计，不是对全域或所有原始证据重新验收。
完整成本、准确输入SHA与计数在result.json；输入锚点复核在input-anchor-review.json。
没有优化或加速比结论。
