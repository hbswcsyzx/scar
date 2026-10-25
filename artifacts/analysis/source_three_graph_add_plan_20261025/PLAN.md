# 三图ADD与单次构建读取复用：仅设计，未运行/未修改生产

当前精确父级是source858：2217 body定义、151文件、858个原active refs。`catalog.v2.json`机械选择两个actual-exit0窗口的3个RECOVERED_WITH_OPEN主体：148/131/312静态ops，3个source文件，原父调用权重32+1+900=933。`ACTIVE_858_REFS.json`完整保留858个准确原qualified checkpoint refs（从小structured component实读，未打开任何checkpoint/graph）；三个新SP5仍仅local，若严格ADD成功应为861，runtime843不变。新Gen的五Region/B+2D+U可由现有SP5/CP2表达：publisher `_program_counts`计真实regions；`validate_body_interface`按root region筛选environment；普通typed reader仍做全部cap/source/core检查，不能把子Region投影掉。

**512MB不可行，先不执行原门。** `io_lower_bound.json`仅用小publication headers/真实收据证明：现有source858 constructor仅composition重复读下界745,106,088B（未计858 decoded等）；理想每URI只读一次后，四ancestor roots376,982,216B + 17历史SP5 265,490,535B +858 stored17,109,069B =659,581,820B；加新三SP5 38,342,793B得697,924,613B。这个唯一必读下界不能靠缓存省掉；可省的是同一exact URI的再次stored hash/decompress/parent验证。未把decoded未知值当0，未放宽任何历史父源/CodeWitness/资格guard。

**最小三生产文件改口，尚未实施：**

| 文件/API | 具体改动与传递 |
| --- | --- |
| `inventory_partitions.py` `_read_receipt`、`InventoryPartitions._read` | 增私有`_ArtifactReadSession`与动态作用域；正常reader第一次完成stored/decode/receipt后记immutable bytes和观察到的hash，cache hit仍执行每个caller的expected-ref、schema、limit校验；每次返回fresh parsed dict，不能把可变dict当缓存。没有expected receipt的原路径仍不得自授权。完整累计stored/decode、cache命中、拒绝原因及watch集合。 |
| `program_composition.py` `_read`、`_verify_parent_composition`、`CompositionIndex.__init__` | 同一session复用第一次正常reader读出的精确URI/payload/receipt；recursive parent改经私有`_parent_index`，仅重用本次普通构造已完整通过的、私有owned parent节点。保留每个expected canonical SHA、inventory/publication/CAS/原compiler源及`validate_body_revision_publication`逻辑；未完成节点绝不能命中。默认public signature不变，单独constructor自动拥有只持续该次递归构建的session。 |
| `source_program_publication.py` 新普通批量coordinator | 新`publish_and_compose_source_programs(base_path, paths, out_dir, *, code_witnesses, limits, progress)`在内部开session，再走普通`CompositionIndex→plan_source_body_publication→publish_source_body_revisions→compose_source_publication→新CompositionIndex/ordinary consumer`。传base **path**，不接受任意caller mutable index或trusted/token。现有public APIs保持；未处于该coordinator的独立调用各有独立scope，不能承诺互相复用。 |

会话只在单个owner thread/一次batch闭包内生效。batch的base/parents由正常constructor构建，内部对象不返回给caller；返回正常artifact/普通消费结果。开始冻结参与源码、receipt/representation、原logical URI、namespace/source/witness及限制；不同URI即使同SHA也不合并身份。bytes可复用，source/compiler/资格验证事实只有同code-policy/receipt/namespace/输入/验证模式和不弱于当前limit才能复用。保留readonly CodeWitness正常解析及当前3个新source/compiler检查，旧历史accounting仍是accounting-only，绝不升级历史source合法性。每个命中先核URI及stat/expected receipt；对可能暴露的mutable index、manifest/cache views、witness document核原canonical fingerprint。中途变异、边界改变、building/cycle或更严格预算都拒绝，不能新SHA自动续用。构建结束/失败清ContextVar及全部私有缓存，无持久token/全局cache/新IR权威。最小后续检查只需exact ancestor复用+变异拒绝，以及不同namespace/limit不能命中；本次未跑。

**publisher→compose→consumer累计预算须同一session，不能每阶段重新开。** 没有coordinator时三个入口仍可能各重读整链；补一个`_read`缓存不足以关闭这个缺口。`READ_PLAN.v2.json`以全部5份小manifest、原1627-return index及858 refs构成1892个URI的保守输入上界：含所有原checkpoint（许多不必实际读）、各版本file shards/components、四ancestor roots、17旧SP5、新3SP5、准确3 context及readonly witness。不得为了budget主动读取上界里未需要的payload。787个非active原return的stored SHA当前未读取，保留原index的decoded SHA和准确URI/stat；第一次实际需要时必须先由已校验source shard取得完整stored expected receipt，再由原normal reader核实，不能凭index或stat授准入。

保守retained stored+decoded上界 **1,557,960,169B**（858 decoded用独立96MB ceiling，未称实测）；owned输出首次普通读取≤256,000,000B，metadata≤16,000,000B，合计1,829,960,169B。再纳入source/runtime两轮SHA读各≤64MB，严格总读上界 **1,957,960,169B**，提出一次 **2,000,000,000B** ceiling供root决定；不是自动重试调高。输出仍≤256MB，3新body/3source、4000ops/body、ordinary每record64MB、composition96MB、outer900s不变。声明最大非composition输入decoded28,456,306B。若为保证只读一次保留payload，decoded缓存上界1,636,815,547B；另有正常JSON/core对象成本，不能称低内存。若实施时选择有界LRU/磁盘spill，必须另计实际重读/写量并重审该上界，不能隐藏cache I/O。实际必要子集与耗时尚未实测。

这仅解决publication/consumer重复I/O与重复校验，不解决模型语义。三图close/throw/whole lifetime/effects/runtime仍OPEN。root新generic CPU八stage门的module/native-entry缺口（另一Run、0defs/0body、271 unresolved calls）与本存储问题并列；不能让本门预算成为第一阶段建模推进的替代目标，亦不把933旧父调用权重并入新Run。root可据此决定先做三文件复用，或先推进module entry。
