# Native boxed scalar V2 接入

仅应用已通过原门 session68758 的四源。显式 V2 根据原 schema/real-kind 和实际
ETO IValue tag 识别 NumberType 中的 Int/Bool；不将规范化 literal 的 Python 表示
当作原 Python 对象类型。原 V1、默认 capability、静态 ProgramSnapshot 保留。

主树接入核 656122ce 基线与四源冻结 SHA，然后对原 V1 投影做普通 typed 回读；
用实际 V2 已存小结果保留 264=260 roots+4 frontier 的原门证据，不恢复 live owner、
重新 query、producer 或目标。根的上游、Python enum/符号转换、状态/ready 继续 OPEN。
兼容检查直接投影 4MB、外部60s；不会把结构检查当新的内容资格。
