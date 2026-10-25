# 模块入口接入主开发树

仅接入已通过的 candidate04：五个生产文件保留原字节，worklist 只追加独立
`module_entry_catalog`，保留当前 source-entry v2 和原调度逻辑。原真实门 exit0，
保存的 SourceProgram6 为 2 Regions / 9 operations，内部语句展开为 0，REQUIRED
债务保留。前三次候选及实际失败记录由原分支归档，不覆盖。

主树只对同一原 SourceProgram6 做普通读回，并机械核对 catalog 原模块单位；
另外读取一份已通过的 SourceProgram5，检查新 reader 没改变旧入口。
不 lower、compile、执行目标、重新采集或运行全量 LeWM。直接输入 stored+decoded
上限 32 MB；组合/见证 reader 各自保留原 API 上限，累计 I/O 不冒称已计量。
输出 1 MB，外部 60s。原规范产物身份、命名空间和 SOURCE/运行分母
不变。成功仅说明主树接口兼容，不是模块内部、实际 namespace 或全程序完成。
