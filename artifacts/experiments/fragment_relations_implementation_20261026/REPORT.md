# Cross-fragment：完整 work 分母与限定静态／动态连接

完整 **24082/24082 work** 关系已发布；原candidate02整门仍 **exit1**。独立normal-reader postflight **exit0**，只证一个真实关系链及同一静态Region membership。整体程序仍OPEN。

| 原窗口 | Root实际终态 | 范围 |
|---|---|---|
| candidate01 / 22743 | exit1，worker900.004s | 未完成work；反复解析已缓存JSON字节导致超时，partial原件保留 |
| candidate02 / 49502 | exit1，outer723.841901758s | 718.480s已产完整关系并进入consumer；随后public static_member错接不存在的codec.from_dict |
| postflight01 / 43950 | exit0，outer3.972053268s / worker3.815688364s | 原7e producer guards下正常work查询 + 独立program.codec.loads核同StaticEntityRef；不调用坏helper |

原五源7e及全部旧freeze/runner/failure不改。public helper在本交付commit明确未通过；后续仅两行API修正另commit，不能把该修正或postflight记回旧门PASS。main须按main自身producer路径/新源码版本fresh全分母验收，旧source-policy/path guard不放松。

## 完整分母与原端点

- 原EEG461242实例、1170339边完整走访，派生索引78171条provider边；native156原shards/39796 INVOKE全部索引；当前source858/runtime858 retained associations79592行完整走访。
- 24082个物理work全都有原provider host关系；其中11541个具有精确canonical native occurrence、retained source invocation和独立CodeVersion/source-definition桥；12541个明确native/source未接。22060 annotations为另一frontier分母，合计46142 GPU candidates。
- STATE_CONTENT_READY_UNPROVED=24082；STATIC_BODY_MEMBER_UNREVIEWED=2391。SUBMITS_WORK和PROVIDER_SCOPE_ASSOCIATION分别核原edge路径/方向，后者不是direct call/submit/parent/order。没有实际参数、world传递、对象身份、内容、ready或child completion的新证明。
- 静态Code/SourceSnapshot/Region/Use/StateLocation和动态Run/process/Invocation/Occurrence/Work保持独立原身份；未执行分支留原静态图，不创造动态occurrence。完整source858 inventory引用保留；本门没有重lower或重新枚举静态源定义。

规范输出为115 work、86 source-retention、25 work-index及80 source-index chunks，stored总67,556,732B；原locator与CodeVersion/source witnesses均可回原qualified URI。所有transport已只按stored bytes/SHA复核且逐文件≤1MB，无重解码全输出。SQLite仅可删重建locator，留本地不入Git。

## 独立读回的实际范围与成本

选中原V2 shard000003第14行work `native-activity:b9d7e51a269902b00048e442a8835c4e3fcb9844a30e76ddaec3ee5b68a935d4`（自动first_static_body_work）：normal reader得到3条host关系、2条source context、1条static binding；独立core codec核原静态Region，原图65ops/1Region/97values/1Location。该源body为既有归档，不是新编译/执行，不把静态membership算AST/source replay、动态分支执行或合法性证明。

postflight实际input161878894B=stored33790076+decoded128088818（core150759054/code11119840），RSS189040KiB；producer/index/lower/prepare/target compile/exec均0。只做selected source/input终检，未重新授予完整runtime participant身份资格。

candidate02失败receipt实际input8015980143B（core8006064595/code9915548）、output含SQLite765252803B、RSS234188KiB；这些是含重复读取的计费字节，不称物理磁盘I/O。900/960秒、9GB core+512MB code-source、1GB output/2GiB预算不变。缓存单真实locator比较为strict_loads20→1、值相同、0.420266→0.032688s；它是leaf测量，不是整模型完成或整体速度证明。原失败未落完整runtime/footer资格保持OPEN。

来源、五源精确SHA与main应用边界见APPLICATION_BASELINE.json；小规范关系清单见RELATION_ARTIFACTS.json；显式stage/保留见STAGE_PATHS.txt、STAGE_MANIFEST.json、RETENTION.json。原EOF/raw/大EEG、静态graph输入及SQLite不复制入Git。source-native class移动保同class re-export，旧派生导航SHA失效，旧843导航未冒充当前858 scope。
