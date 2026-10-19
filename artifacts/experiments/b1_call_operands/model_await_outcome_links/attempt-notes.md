# 本轮实际尝试与归因

全部由root在lewm环境串行执行，执行期间所有源码作者冻结。每个目录保存
自己的command、stdout/stderr、JUnit及before/after源清单，失败不覆盖。
这里的时间是pytest/runner时长，不是workload性能。

| attempt | 结果 | 源码SHA | 归因 |
| --- | --- | --- | --- |
| first-outcomes | 3P/10F | 78299dcbe48aa5d0ab6e7a7cac54a76d26abeaed7e28640bb440edc818fd341d | 7项缺新接口；2项准确parent RAISE选择仍误证NORMAL，真实旧helper缺口；1项新fixture删row后未删准确receipt，失效FK。 |
| second-outcomes | 13P/0F | 0b5b07351652fac24ccfe9a30473058edac27ff00a4ffa928cf81bada82d217e | 第一版原outcome/失败端点及parent edge guard通过；不是最终字节。 |
| boundary-outcomes | 20P/2F | 8b4f54a0cdcc283c573ae3cbaa0d1f1791d8b914f418eb3a2f34cfac04b1eef5 | 全删producer/final附件、budget1、handoff通过；两个source必要accept边与请求reject边冲突，临时实现抛ValueError而非False。 |
| red-forwarded-state | 1F | 2230e296642a87106083d0d512481f7aa1c18c8ac2b7235bf1d1305b9bf98f33 | 完整core合法、原state由独立edge Use转发；视图错误漏成states空集合，原2项支持变0。 |
| third-outcomes | 23P/0F | 2b37fb50ef8ebba44b4d68245524e24ed9f3ca122da6f78a6543b6c323f115ed | 包含新转发状态及已知source条件冲突；旧1454尚须统一检查。 |
| affected-outcomes | 1477P/0F | 2b37fb50ef8ebba44b4d68245524e24ed9f3ca122da6f78a6543b6c323f115ed | pytest129.30s，runner130.36121185217053s；之后才补最后子项状态汇总，不能归给新字节。 |
| accepted-focused | 1477P/0F | fb0fc2fbaf9292421bc7c873297e77fcad0668a489eeb06f6e4fc831e64061f6 | 最终776源固定；pytest127.76s，runner128.72808583267033s；仅受影响定向。 |

首轮fixture仅在新owned文件清理被删Get RAISE row对应receipt，原core/正常CFG/
各stage均未动。两个wrong-final payload和wrong-parent packet slot反例在首轮
已被原检查拒绝，不冒称本轮首次发现的产品bug。

独立审查还指出HANDOFF/BodyRaise缺准确caller delivery桥、子项False/None上卷
不完整、forwarded state未保原支持等实现风险；源代码修正后才重新运行。每项
源码意见与实际首红分开记录，不把只读推断写成已运行或完整A–H验收。

原16组及完整A–H/P5/M2仍OPEN。后续统一affected和最终源码结果在各独立目录
及最终进度报告中记录；本表不预写尚未完成的运行结果。
