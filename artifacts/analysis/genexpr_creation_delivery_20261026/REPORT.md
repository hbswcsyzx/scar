新版 V5 将 generator creation 与外部消费资格分开。同一原入口 `torchvision/transforms/v2/_misc.py:272–291`（ToDtype.__init__）实际 SUCCEEDED：251 ops，37.986973s；普通 STRUCTURE 和独立 source/CodeWitness reader 均通过。readonly 1 load / 2 complete matches，compile/raw/target/publication/current-Run binding 均 0。历史调用权重 2 保留，未计为新增运行时覆盖；原 243/817/100438 分母不变。

图包含 root 与 lazy-body 两个 Region、1 ResumableCreate、1 ResumableBody；driver、drive、request、final gate、outcome commit 均为 0。generator reference 可进入普通 CALL 的不完整 world 接口，未声称消费者内部展开、NEXT 次数、激活路径、对象同一、内容或 finalizer 完备。lazy body 定义不表示已执行。

原 CodeConstantSource 槽 2 对应两个互斥 compiler 路径 LOAD_CONST PC 272/392：新策略复核同槽同 child CodeType、capture ABI、GET_ITER/CALL 及异常 CFG 下的共同入口/互斥性；不选定运行时 PC。原 V1 fixed-unpack producer 文件字节与策略不变。V5 自动 profile 公开于 SOURCE_ENTRY_PROFILES / LATEST_SOURCE_ENTRY_PROFILE，旧 None/V2/V3/V4 选择逻辑保持。

实际原源码还需两处旧 overlay 缺项桥：单 In/NotIn 作为含 contains/迭代 fallback/truth 与失败的 stateful 接口，保左→右 Use/held refs/world 和 PEP479；eager List 复用已有 BUILD_LIST 规则及失败保留输入的生命周期。都以原 AST/SG、原 readonly CodeWitness 定位，不补造旧 computational op。该能力保持单普通 clause/无过滤/同步、真实 cell capture 等边界。

同一入口前三次真实 UNSUPPORTED（128/149/178 prefix ops）及 code-occurrence 诊断完整保留；第四次完整返回后即收口，未重跑其他 5 个原 generator 前沿。原 SP5 1,585,561 compressed bytes / 14,810,739 decoded bytes 只保原 URI/双 SHA，不重复 vendor。正常 reader 已验证原产物，本交付未再次解图。累计 stored+decoded I/O 与 runtime 二进制执行字节证明仍 OPEN；整个程序/动态消费/状态证据未因此闭合。
