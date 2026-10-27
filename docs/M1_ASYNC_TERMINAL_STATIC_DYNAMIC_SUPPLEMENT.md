# 原 F18：静态路线与动态发生使用同一异常来源规则

2026-10-20。四份旧生产文件范围和原schema/旧测试约束保持。

ordering 修订45项通过后，独立审查指出：静态已识别一般后继 INVOKE own RAISE，
动态仍只识别附有 SessionUpdate 的 helper。一个 existing second helper 没有该
可选附件，真实供采后应接它的新异常包；不能继续接前一个 session helper 的包。

root 在仅有自己拥有的 affected 回归运行36.39秒后，用SIGINT停止自己的pytest
子进程（已核具体PID/PPID与worktree），保 `verified-final/` 的真实returncode2、
379项通过、899稳定源和全部命令/源码/JUnit；它不是最终通过。没有停止其他进程。

随后 `static-dynamic-failure-counterexample` 实测1FAIL：准确模型与实际数据均可
通过各自校验，最终 host.source_value 却错误地来自较早helper。899稳定指纹
`865ef46a6bc17e5bf57e00158218b212977202725032b9029ebbcabb5e2eda3c`。

修订只沿已有actual suffix识别一般 INVOKE 的实际selected RAISE和typed packet
slot；最后一项依原actual visit先后确定，不依赖SessionUpdate存在与否。若该
own packet缺采仍为None，不能旁路回旧body包。request post状态仍依自己的
SessionUpdate准确N/R分支判断，不因普通helper失败便发明session完成事实。

新增一项动态双helper反例，旧单helper selector保留。全部46新增用例及旧2058
精确身份统一验收；本轮最终运行目录改为 `verified-current/`，原中断目录保持。
没有新实体、协议规则、backend或LeWM特化，原F19与整体阶段不由本轮代验。
