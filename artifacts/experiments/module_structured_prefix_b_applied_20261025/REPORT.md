# B 模块正文主树接入：有限读回通过

隔离63369 actual0，outer7.126340s/worker6.942416s；交付8078ffde。
主树55827 actual0/4.898593s：六源baseline及after SHA一致，普通原SP8和旧function SP5读回通过。
真实同源码自动展开8顶层接口（另含for体Assign，共9stmt记录），118ops/2regions；
Try/Assert/Expr三条精确suffix仍REQUIRED。没有重lower、compile、capture或执行目标。

主树这次仅consumer；隔离producer实际输入4464710B、原compilation witness1load1match0compile，
AST-only22及target-executable compile/exec/prepare0均见原门收据，不相互替代。
主树直接输入5624711B，内部API累计I/O仍OPEN。

这是保存CPU源码的接口拓扑恢复，不是LeWM覆盖提升。实际namespace/activation/import对象、
映射内容/alias、细粒度effects、C0/C1传播traceback/清理、完整module及第一阶段均OPEN。
