# 第一阶段：当前调用复用精确代码来源证明

状态：**Observed：全部调用记录已保存并连接可用来源；完整模型 OPEN。**

使用公共 `bind-source-invocations`，显式 `--witness-mode reused_code`，输入为原151
文件/54局部body的composition和最新272038 capture。只复用完整descriptor与
pycode-v2都相同的静态代码来源；当前所有调用、计数、父子与运行身份来自当前raw。
115个当前源文件的fingerprint均一致；没有重新prepare/编译/执行目标。

| 当前原始分母 / 结果 | 数量 |
| --- | ---: |
| code capture / entered code group | 855 / 817 |
| 完整descriptor匹配的entered group | 812 |
| frame entry / exit / orphan exit | 100,438 / 100,438 / 0 |
| body引用：code group / frame record | 34 / 4,948 |
| source-only：code group / frame record | 391 / 3,838 |
| 未连接：code group / frame record | 392 / 91,652 |
| recorded direct / retained ancestor | 96,799 / 3,638 |
| frame区间匹配 / 未资格化 | 96,416 / 4,022 |

parent interval不证明source ast.Call或actual/formal/return，挂起/恢复连续性与65个
未知退出等条件保留。全部记录均保持参数/返回、环境、状态/effect、canonical完成
接口未连接；body引用不等于完整执行模型。未保存Tensor内容。

加权未连接原因已逐项审查，详见 [SOURCE_RECOVERY_FRONTIERS.md](../../../docs/SOURCE_RECOVERY_FRONTIERS.md)：
71,368次被原project root边界拒绝（70,565次实际源码文件存在）；16,137次为5个旧
witness不存在的新code；4,147次是已验证但module/genexpr/lambda/延迟annotation尚无
对应定义。1,905次代码明确属于SCAR回调，不能无条件当作目标源码缺失；14,224次
Torch callback的observer来源尚需class身份边，未据此删除记录。

原旧inventory只有256 body/10000 op预算，其缺口不是当前实现的最新全量覆盖率。
正在进行的新全量会另做same_capture绑定，不把两次不同范围相加。
