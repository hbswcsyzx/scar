# 一个完整 retained LeWM fresh linker 门

状态：准备 freeze，NOT RUN。原采集 Run `capture:1ddea1de4990462b59cf5dd24beb3f120156eb47bca68cfb3f1a63f9f73f2cf0`，
source858，全部151 files / 2217 body 分母、100438 frames、100550 attempts。输入、旧 CodeWitness
和 producer archives 原 URI 不变。源端口关系由当前隔离四源生产；不借旧输出恢复 owner。

入口复用 `source858-runtime/.../first_stage_source858_current_20261026/run.py` 的普通
CompositionIndex、同 Run proof、coordinate binder、read-only CodeWitnessStore 和
`connect_current_capture`。只增加同 fresh 会话的可选 source-port consumer，旧 report 的
一次 to_dict/archive 与原动态分母/namespace 审核不变。不新增 target、lower、prepare。

结果单独是 `result/source-ports/model.json.gz`（strict typed v1），不改旧报告 wire。
先实核每项原 attempt 恰有 binding 或具体 issue，再对一个机械选出的真实非零 binding
用同 session checker 正核，并拒绝 call source / formal slot / caller / arity 的具体换置。
新 strict reader 完整读回。旧27 route组必须列交集/遗漏理由，全部丢失则失败；不预设
新覆盖2656组。任一失败保留原 failure/partial，不自动重跑。

边界：SourceArgumentPort 是限定在原静态 body 的有条件语言绑定；actual entry 匹配不
授动态 value identity、contents/state/ready、效果恒等或转换合法性。源 runtime 正式指针
仍858/6882；本门不 publication，不把未匹配的非Python边界当Python漏调。
