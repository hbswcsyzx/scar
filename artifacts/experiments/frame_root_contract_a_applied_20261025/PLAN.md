# 通用 frame 根 A 接入

接入已通过隔离门的七份冻结源码：core29 的 typed frame/source subject、codec、
validator，以及旧 source1–7 能力守卫。主树基线须与8f066a0f逐字一致；新
source_subjects 是真实新增文件，ModuleUnitSource re-export 保留原类和旧 wire。

主树仅普通读回原 SP7/SP6/SP5；检查两处 ModuleUnitSource 导出是同一个类、旧图
不带 frame_roots。不 lower、不执行目标、不构造完整模块或动态 activation。
新 core29 的类型/codec资格来自原 A 门，不把主树旧图兼容检查当新 source/runtime
证明。直接输入32MB、外部60s；其它 reader 保原 API 限制，累计 I/O 单列 OPEN。
