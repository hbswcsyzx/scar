# 类型在哪一层，不能混用什么

程序的类型、某个实现是否已展开，以及某项效果是否已证明，是三个问题。不能用一个
`OPAQUE` 标签代替它们，也不能因为知道操作类型就认定操作纯净或输入不变。

当前实现有以下对应层，原记录各自保留身份：

| 层 | 表达内容 | `f(**m)` 的例子 |
| --- | --- | --- |
| 源码结构 | AST/SourceAtom及精确source span、版本与包含关系 | `Call`，含callee、keyword-unpack child |
| 既有SG定义分类 | 原定义的宽分类及元数据，不是全部计算指令枚举 | frontend_v2原样保存`OperationKind.OPAQUE`和`ast_type=Call` |
| 计算语义 | 表达式如何求值、有序输入输出 | `Opcode.CALL`，目标和展开的实际值仍可能未知 |
| 规范ProgramGraph | 广义Operation、有序Uses、Region、状态和完成接口 | pack、建dict、DICT_MERGE、CALL_FUNCTION_EX及normal/raise world |
| 实际执行 | 哪次activation/visit/occurrence实现哪个定义 | 每次真实调用分别有ID；静态Call不等于一次实际执行 |
| 物理与证据 | 对象、逻辑值/版本、表示、资源、活动、来源及资格 | 对象引用不代替内容版本；host Return不代替GPU ready |

这里没有新增规范IR。`OperationKind.FUNCTION/METHOD`是定义分类，不能凭名字拿来表示
所有调用；现有SG中根本没有`OperationKind.CALL`。原源码producer在
`scar/ir/frontend_v2.py`，计算overlay在`scar/analysis/source_semantics_v2.py`。扩展前端时
应核真正producer和字段合同，不能给不存在的枚举写guard，也不能改写旧归档的分类来迁就
新reader。kwargs第一门已暴露并保留这类接线错误；修正使用原OPAQUE/Call atom、精确
source/code_id/output及原Opcode.CALL，再展开为已有core协议。

同理，`x+y`的语法类型已知，并不证明运算无副作用；Python可调用用户协议。`def f`还包括
定义时求值、环境/函数对象与未来执行的body，不能只留下一个函数名。Region的递归展开、
typed data/state/control/resource边负责这种连接，不给每行强贴一个互斥类别。

SourceProgram的结构读取和源码语义复核也须分清。若validator需要源码，应使用明确的
版本化源码输入并核fingerprint，不能把读取机器当前同名路径当作历史源码证据。结构、
source/compiler、局部引用持有、实际effects/lifetime的验收范围分别报告。

已知语法/端口必须保留；未知target、状态、内容或资源关系必须落到具体位置及义务。
反过来，原SG的OPAQUE分类不阻止通用前端依据准确来源作更细的结构展开。它也不授予
任何复用、删除或变换许可。本阶段只补模型和自动恢复，完整性继续按原合同验收。
