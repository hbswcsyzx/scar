# 公开原生输入/状态/metadata连通查询

query-native-interface source17 +原navigation真实exit0，CLI79.451900秒。
47节点/47边，全部端点存在、无向连通；真实原引用/Use/原生op、
静态interface/region/抽象state location、metadata leaf及provider epoch同图。
1个输入path精确匹配，其余5个path没有Tensor metadata leaf，不推测它们的类型。
旧canonical unavailable状态保留，本次新canonical input关系不会倒改旧文件。

metadata索引原310410 rows/420444 leaves完整单pass64.622秒，临时330141696B；
normal native reader4.142秒，query内部总68.857秒，CLI退出总79.452秒。
不是轻量局部查询；批次共享session避免每片重载。原source SHA见INPUTS；
后续shared reader已另行实测，不追认本次为其最终源码执行。
conditional输出/state successor不授normal completion/content equality/ready，
没有重跑目标，也没有建立全程序或所有metadata输入关系。
