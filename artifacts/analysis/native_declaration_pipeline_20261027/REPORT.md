# marker-independent native interfaces：整片自动建图

公开CLI `build-native-interfaces --shard 0` 实际exit0，17.392630秒。
原首片全部2,545操作均产生规范occurrence；11,738输入/1,753条件输出，
10个执行片段共享一个catalog，总stored116,719,872B。原完整分母230,818，
未处理228,273；没有把条件输出当实际normal return，completion-selected=0。
没有重跑目标或读取raw ETO，基于既有port/bundle/coordinate记录。

普通reader独立读回首个完整256-op片段，6.814478秒、issues0，
687inputs/183conditional outputs/0transfers，来源与ABI/core一致。
其余片由同次producer的core validator检查；未声称全部普通reader独立回读。

Implemented：共享catalog、按源分片自动遍历、规范input/invoke/world、条件output源；
公开独立命令和model-run自动stage已接。Verified：本次公开独立命令首片和普通读回。
完整model-run组合/全部源分片尚未实测。metadata/physical join、content/state/ready
仍未闭合；不是整个LeWM图完成，不是性能加速。首片输出117MB，不能称轻量存储。

精确运行命令及源SHA见INPUTS.json；运行后只在pipeline报告中追加
classification_counts字段，未重新执行首片。bulk execution留本地，不随本报告提交。
