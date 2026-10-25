# Callee 入口参数对应接入

原隔离树基于 bc139/core28，真实门93681 exit0/38.8904s：271次入口、566个参数
观测中260次入口/520 formal ports可对应，11次缺规范body。输入frame536684B与
operand13285B只完整读取一次；caller表达式、对象/内容身份、环境/状态等不因此成立。

主树已新增core29类型，默认旧body仍读取原core wire。三源接入先核原bc139基线；
共享source_invocations已与project代理协调，后者只在新基线上修改project选择分支。
本次应用仅核准确三源与默认v4/显式cap接口，并普通读取原SP5及参数projection的
typed ReferenceOccurrence；不恢复live session，不把兼容检查当新的520路由资格。
直接输入32MB、外部60s；必要原body/code reader保各自原预算，无新target/capture。
