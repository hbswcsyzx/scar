# 全量原生边界构建

RUNNING，当前仅确认已启动并有真实存活进程。冻结版本312ab664，
范围为原port index全部230,818 operator rows，不手选业务函数或源ordinal。
准确命令、原index/bundle/coordinates收据及源码archive SHA见INPUTS.json。
首片实测17.393秒/2,545ops/116.72MB后，输出预计约10.6GB，
本次有界16GB输出、8GB累计输入、1800s内部/2100s外部期限。
结果以RESULT.json和普通producer manifest为准；启动不是通过。
这是既有LeWM记录的offline canonical boundary构建，未重跑target。
metadata/内容/资源依赖、完整LeWM新采集及第一阶段均未完成。
