# 有界表示冗余审计（原图不变）

从115成功SP5声明机械选“同file最小两body＋100MB余额内最大项”，实际读10,071,363B stored／84,024,792B decoded；114,979,987B最大项因预算未读。逐样本核原physical/canonical SHA，只按JSON字段边界量字节，不构造/验证大型ProgramGraph。未跑target、worker或fixture。

| 真实样本 | 全文B | semantic＋semantics＋control B |
|---|---:|---:|
| 同file body A（pymunk `moment_for_box`） | 2,813,442 | 2,472,945 |
| 同file body B（`moment_for_poly`） | 2,921,723 | 2,472,945 |
| 预算内大项（typing `_GenericAlias.__hash__`） | 78,289,627 | 78,129,600 |

三者上述整文件上下文共83,075,490B，占**98.87%**。A/B三个字段的各自SHA及字节均完全相同：只扣一次重复副本已是**2,472,945B＝该对全文43.12%**。大项自身上下文占99.80%，不把其独有上下文算重复；每body compiler witness约5.9–6.0KB。当前SP5确实反复内嵌整file context，而非仅body＋共有context引用。

跨片仅取实际v2规范manifest及首chunk各3个work/source完整行：decoded285,995B（行160,353B），两chunk stored545,900B，transport SHA匹配。main稀疏副本缺失，仅读固定Git5a0b50ee原blob；manifest SHA为c1d3fbe9…b594。未重核整chunk canonical EOF或全1.93GB关系。去除嵌套重叠后，精确相同对象的重复载荷为：RuntimeScope12,348B、ProviderArtifact33,797B、FactSource locator35,359B、SourceReference2,928B；合**84,432B＝六行52.65%**。15个scope仅1个精确对象；全部嵌套计数另列，不相加。

**可共享事实：** 同snapshot＋namespace＋hash的整file三层context；精确URI/SHA/size/schema artifact；准确run/process/coordinates的scope描述；原source/FactSource locator；compiler archive/runtime公共头。descriptor→definition映射、flags/optimize与证据端点仍必须完整可查，不能靠shape或成功bool省略验证。

**不可去重语义：** invocation/activation、state/version、Value/Use身份、ordered uses、边及其顺序、completion/cleanup路径、qualified namespace与原证据ordinal。同值/同shape不合并逻辑值；scope数据共享不能恢复live owner或授ready/内容资格。

**下一最小切面：** 先为source-entry输出增加显式、兼容旧SP5的共享context传输：每file只存一次原三层context，以qualified URI＋双SHA引用；每body保graph/interface/metadata及原compiler来源，普通reader按原guard解析。再为关系transport加精确fact表引用。只改表示与reader装配，不新图权威/backend，不改原产物。以上百分比均是样本实测的重复/字段载荷；引用和表开销、压缩后节省、全115／24k总节省**未测且不外推**。精确字段/来源见MEASUREMENTS.json及SOURCE.json；scope和全部第一阶段未闭合义务不变。
