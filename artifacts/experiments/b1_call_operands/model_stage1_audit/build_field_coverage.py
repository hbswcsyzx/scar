"""Materialize a manually reviewed field map; reflection checks conservation only."""
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
D = "docs/model/PYTHON_DATA_DEFINITION_PROTOCOLS.md"
C = "docs/model/PYTHON_CONTROL_PROTOCOLS.md"
R = "docs/model/RESOURCE_PROTOCOLS.md"
W = "docs/WHOLE_PROGRAM_MODEL.md"
rows = {}


def entry(phase, rule, section, gap=None):
    return {"status": "GAP" if gap else "COVERED", "phase": phase,
            "rule": rule, "references": section if isinstance(section, list) else [section],
            "gap": gap}


def add(name, section, definitions, node_rule=None):
    fields = {field: entry(*value, section) if len(value) == 2 else
              entry(value[0], value[1], section, value[2])
              for field, value in definitions.items()}
    rows[name] = {"construct": name, "fields": fields,
                  "node_rule": node_rule,
                  "status": "GAP" if any(r["status"] == "GAP" for r in fields.values())
                  or (node_rule and node_rule["status"] == "GAP") else "COVERED"}


def marker(names, section, rule, gap=None):
    for name in names.split():
        add(name, section, {}, entry("COMPILE_PROTOCOL_SELECTOR", rule, section, gap))


add("Module", D + " §2.1", {"body": ("MODULE_EXECUTION", "按语句顺序执行，定义体延迟；各completion保留后态。"), "type_ignores": ("SOURCE_METADATA", "解析器行号/类型检查元数据，不产生运行Value/Operation。")})
add("Interactive", D + " §2.1", {"body": ("INTERACTIVE_EXECUTION", "顺序执行；表达式结果经宿主displayhook等协议观察，不当普通exec。")})
add("Expression", D + " §2.1", {"body": ("CURRENT_EVALUATION", "求值一次；成功传结果，异常和编译失败分离。")})
add("FunctionType", D + " §2.1", {"argtypes": ("PARSE_ONLY", "func_type签名语法，不执行参数类型表达式。"), "returns": ("PARSE_ONLY", "func_type返回签名语法，不制造runtime表达式。")})
f = {"name": ("DEFINITION_BINDING", "装饰器应用完成后绑定最终返回对象，原body code保持独立。"), "args": ("COMPILE_DEFINITION_CALL", "签名结构；defaults/注解环境在定义阶段形成，actual在call绑定。"), "body": ("BODY_ENTRY_RESUME", "定义阶段编译为Region，实际函数进入或resume才执行。"), "decorator_list": ("DEFINITION", "表达式从上到下求值，defaults等完成后decorator反向应用，保留异常。"), "returns": ("DEFERRED_ANNOTATION", "默认懒注解；访问时按协议求值/缓存；future模式为字符串。"), "type_comment": ("SOURCE_METADATA", "只属注释/type-check元数据，不作运行表达式。"), "type_params": ("DEFINITION_DEFERRED", "有序创建generic scope/type参数；bound/default按§4延迟。")}
add("FunctionDef", [D + " §3.1", D + " §3.2", D + " §4", C + " §7.1"], f)
add("AsyncFunctionDef", [D + " §3.1", D + " §3.2", C + " §7.1"], f)
add("ClassDef", D + " §5", {"name": ("DEFINITION_BINDING", "class构造和decorators成功后绑定最终对象。"), "bases": ("DEFINITION_HEADER", "各base求值并可调用__mro_entries__；MRO/metaclass选择可失败。", "G5: 未明确与keywords交错源语法、starred base展开的跨字段实际顺序。"), "keywords": ("DEFINITION_HEADER", "求keyword value，metaclass参与选择，其余传构造。", "G5: class header是否及如何复用Call的positional/starred-before-keywords顺序未写明。"), "body": ("CLASS_BODY", "在__prepare__返回mapping执行，接lookup/Store/类注解与异常。"), "decorator_list": ("DEFINITION", "decorator表达式正序，class构造后反向应用。"), "type_params": ("DEFINITION_DEFERRED", "generic annotation scope及type参数按§4；不同scope不合并。")})
add("Lambda", D + " §3.3", {"args": ("DEFINITION_CALL", "同签名/default规则，创建时求defaults一次。"), "body": ("BODY_ENTRY", "调用时求expression，结果成为call completion，保留closure/globals。")})
add("arguments", D + " §3.2", {"posonlyargs": ("COMPILE_SIGNATURE", "与args连接为位置formals，pos-only限制在实际绑定检查。"), "args": ("COMPILE_SIGNATURE", "普通位置formals；defaults尾部对齐。"), "vararg": ("CALL_BINDING", "可选*args formal，接展开后的剩余位置pack。"), "kwonlyargs": ("CALL_BINDING", "与kw_defaults逐下标配对；独立keyword-only formal。"), "kw_defaults": ("DEFINITION_CALL", "定义时求有值项；None代表必须提供，不是None默认值。"), "kwarg": ("CALL_BINDING", "可选**kwargs formal，接未绑定keyword pack。"), "defaults": ("DEFINITION_CALL", "按源码参数序定义时求一次，位置formal尾对齐；调用复用所存对象。")})
add("arg", [D + " §3.1", D + " §3.2"], {"arg": ("COMPILE_SIGNATURE", "参数名称，不作为Name表达式求值。"), "annotation": ("DEFERRED_ANNOTATION", "3.14懒注解或future字符串模式，读取时才求值。"), "type_comment": ("SOURCE_METADATA", "参数type comment元数据。")})
add("TypeAlias", D + " §4", {"name": ("DEFINITION_BINDING", "Store Name绑定TypeAliasType对象。"), "type_params": ("DEFINITION_DEFERRED", "有序type参数scope。"), "value": ("DEFERRED_ACCESS", "建立thunk，读取__value__等触发时求值和缓存，可raise。")})
add("TypeVar", D + " §4", {"name": ("DEFINITION", "在type参数scope声明类型变量。"), "bound": ("DEFERRED_ACCESS", "bound/tuple constraints thunk，访问时保留成员序与状态。"), "default_value": ("DEFERRED_ACCESS", "default thunk，未设置sentinel与显式None区分。")})
add("ParamSpec", D + " §4", {"name": ("DEFINITION", "参数规格type parameter声明。"), "default_value": ("DEFERRED_ACCESS", "默认值懒求值，未设置单列。")})
add("TypeVarTuple", D + " §4", {"name": ("DEFINITION", "变长type parameter声明。"), "default_value": ("DEFERRED_ACCESS", "type参数default/packing协议，非普通call *args。")})
add("Import", D + " §6", {"names": ("IMPORT_EXECUTION", "按alias顺序加载cache/finder/loader/module/package并绑定，保留部分状态。")})
add("ImportFrom", D + " §6", {"module": ("IMPORT_EXECUTION", "结合当前package context求绝对/相对target。"), "names": ("IMPORT_EXECUTION", "加载后依序解析导出/子模块并绑定；star走__all__/公开名协议。"), "level": ("IMPORT_EXECUTION_PARAMETER", "relative level与package上下文决定target；越界等异常保留。")})
add("alias", D + " §6", {"name": ("IMPORT_EXECUTION_PARAMETER", "dotted module或导出名是请求参数，不作普通表达式求值。"), "asname": ("BINDING_METADATA", "决定目标绑定，import a.b默认顶层a，显式as绑定请求对象。")})
for name, rule in [("Global", "compile scope声明，后续Name转module global，无runtime赋值。"), ("Nonlocal", "compile解析enclosing function cell；缺失SyntaxError，无runtime新local。")]:
    add(name, D + " §2.2", {"names": ("COMPILE_SCOPE", rule)})
add("Name", D + " §2.2", {"id": ("COMPILE_SCOPE_CURRENT_ACCESS", "名字选择compile确定的local/cell/global/class/module/builtins路线。"), "ctx": ("ACCESS_PROTOCOL_SELECTOR", "Load读当前binding，Store重绑，Del解绑；未绑定可异常，引用内容不随重绑变。")})
add("Attribute", D + " §7.1", {"value": ("CURRENT_ACCESS", "owner求值一次；Store在RHS后求owner，AugAssign定位另见§8.3。"), "attr": ("STATIC_SELECTOR", "属性名字符串，不执行Name lookup；descriptor/getattr/setattr协议可调用/写/raise。"), "ctx": ("ACCESS_PROTOCOL_SELECTOR", "Load/Store/Del选择lookup或set/delete，保留真实descriptor协议。")})
add("Subscript", D + " §7.2", {"value": ("CURRENT_ACCESS", "先求owner一次；不同Store/AugAssign遵从各自定位顺序。"), "slice": ("CURRENT_ACCESS", "owner后求key/slice，多维tuple key不是重复getitem。"), "ctx": ("ACCESS_PROTOCOL_SELECTOR", "分别getitem/setitem/delitem；class subscription可dispatch class_getitem。")})
add("Slice", D + " §7.2", {n: ("CURRENT_KEY_CONSTRUCTION", "按lower→upper→step求非空表达式，缺省保留sentinel，形成slice key。") for n in ("lower", "upper", "step")})
add("Assign", D + " §8.1", {"targets": ("CURRENT_UPDATE", "RHS一次后targets左到右Store，tuple/list解包递归写，前项写不因后失败回滚。"), "value": ("CURRENT_EVALUATION", "先完整求值一次，共享结果引用给多target。"), "type_comment": ("SOURCE_METADATA", "type/source comment，不运行。")})
add("AnnAssign", D + " §8.2", {"target": ("CURRENT_UPDATE", "有value时先RHS再赋值；Name annotation归scope。", "G1: 无RHS的Attribute/Subscript仍求owner/key但不最终get/set；本节未规定。"), "annotation": ("DEFERRED_OR_OMITTED", "module/class simple Name延迟映射注解；attribute/subscript/local不执行，不统一按字段求值。"), "value": ("CURRENT_EVALUATION", "存在则按赋值规则求/写；不存在不制造RHS Value。"), "simple": ("COMPILE_ANNOTATION_SELECTOR", "简单Name可收集annotation的条件。", "G1: 未明确0/1及括号Name(simple=0)的处理，不能只按target是Name判定。")})
add("AugAssign", D + " §8.3", {"target": ("CURRENT_LOCATE_READ_WRITE", "定位/读取一次，记owner/key，运算后写回同一位置；inplace异常可部分mutation。"), "op": ("OPERATOR_SELECTOR", "优先inplace，必要时binary/reflected fallback，不是额外表达式。"), "value": ("CURRENT_EVALUATION", "target定位读取后求RHS，再运算和写回。")})
add("Delete", D + " §8.4", {"targets": ("CURRENT_UPDATE", "按序定位/删除，前项成功不回滚；Name/属性/下标各协议不同。")})
add("NamedExpr", D + " §8.4", {"target": ("COMPILE_SCOPE_CURRENT_UPDATE", "合法Name target按scope写；comprehension containing scope特例，非法位置编译失败。"), "value": ("CURRENT_EVALUATION", "先求值，再绑定并返回同一引用。")})
add("Call", D + " §9", {"func": ("CALL_PREPARE", "先求callable，访问/descriptor本身有协议；目标可多态。"), "args": ("CALL_PREPARE", "位置/Starred按协议先求与立即展开，实际occurrences逐个Use，不去重。"), "keywords": ("CALL_PREPARE", "随后keyword表达式/映射展开及冲突检查；绑定/dispatch与body entry分离。")})
add("keyword", D + " §9", {"arg": ("CALL_PREPARE_SELECTOR", "字符串为显式名，None代表**mapping；keys/读取/string校验/重复名保留。"), "value": ("CALL_PREPARE", "keyword value表达式在其位置求值，mapping分支继续展开。")})
add("BinOp", D + " §10.1", {"left": ("CURRENT_EVALUATION", "先求左operand。"), "op": ("OPERATOR_SELECTOR", "实际类型forward/reflected dispatch，子类优先/NotImplemented/raise保留。"), "right": ("CURRENT_EVALUATION", "左之后求右operand，再dispatch。")})
add("UnaryOp", [D + " §10.1", C + " §0.2"], {"op": ("OPERATOR_SELECTOR", "pos/neg/invert或not Truth协议。", "G2: 未给直接条件T(Not e)的continuation取反，不能套值上下文。"), "operand": ("CURRENT_EVALUATION", "普通unary先求operand；值上下文not先V再Truth。", "G2: 直接条件if not(a and b)须递归T并取反，不能先V再Truth。")})
marker("Add Sub Mult MatMult Div Mod Pow LShift RShift BitOr BitXor BitAnd FloorDiv", D + " §10.1", "无字段运算marker，选择父BinOp/AugAssign的类型dispatch，无独立运行值或纯性声明。")
marker("Invert UAdd USub", D + " §10.1", "无字段unary marker，选择invert/pos/neg协议；无独立求值。")
marker("Not", [D + " §10.1", C + " §0.2"], "unary not的协议选择，无独立字段。", "G2: 需要区分V(Not e)与T(Not e)；当前后者未明确。")
add("Dict", D + " §11", {"keys": ("CURRENT_CONSTRUCTION", "逐项key先于对应value，None marker代表**mapping expansion；插入hash/equality可调用。"), "values": ("CURRENT_CONSTRUCTION", "各value在对应key后求值；mapping expansion走映射协议，重复key覆盖最终状态不抹前效果。")})
add("Set", D + " §11", {"elts": ("CURRENT_CONSTRUCTION", "元素源序求值，Starred展开，插入hash/equality和allocation可失败。")})
for name in ("List", "Tuple"):
    add(name, [D + " §11", D + " §8.1", D + " §8.4"], {"elts": ("CURRENT_CONTEXT_DEPENDENT", "Load构造中逐项求/展开；Store作为target递归解包写。"), "ctx": ("CONTEXT_SELECTOR", "应选择构造或target协议。", "G3: 文档未集中明确Load构造、Store解包、Del递归删除；尤其Del不得分配/解包容器。")})
add("Starred", [D + " §8.1", D + " §9", D + " §11"], {"value": ("CONTEXT_DEPENDENT", "Load在call/container展开iterable，Store将剩余元素list交target。"), "ctx": ("COMPILE_CONTEXT_SELECTOR", "选择展开/解包target。", "G3: 缺独立ctx合法位置与Del禁止规则；不可由通用child求值。")})
add("Constant", D + " §11", {"value": ("LITERAL_DEFINITION", "精确保留builtin literal，identity/interning由compile/runtime合同，不按字面相等共享。"), "kind": ("SOURCE_LITERAL_METADATA", "保留源前缀信息，不作为另一次表达式求值。")})
add("JoinedStr", D + " §12.1", {"values": ("CURRENT_FORMATTING", "按文本顺序组合literal/FormattedValue；每项的转换、格式和异常保留。")})
add("FormattedValue", D + " §12.1", {"value": ("CURRENT_FORMATTING", "先求要格式化的值。"), "conversion": ("CURRENT_FORMATTING_SELECTOR", "存在转换时在format_spec之前调用str/repr/ascii，可写状态/raise。"), "format_spec": ("CURRENT_FORMATTING", "转换后求nested spec，再最终format；本机已测该顺序。")})
add("TemplateStr", D + " §12.2", {"values": ("CURRENT_TEMPLATE_CONSTRUCTION", "文本序构造Template与Interpolation，非立即输出已格式化字符串。")})
add("Interpolation", D + " §12.2", {"value": ("CURRENT_TEMPLATE_CONSTRUCTION", "构造时立即求值并保留引用，未调用该值str/repr/format。"), "str": ("SOURCE_EXPRESSION_METADATA", "保存插值表达式源码文字，不将文字作为表达式重新执行。"), "conversion": ("DEFERRED_CONSUMER_SELECTOR", "保存conversion供后续消费者，构造点不对value做该转换。"), "format_spec": ("CURRENT_TEMPLATE_CONSTRUCTION", "构造时求嵌套spec，保存结果；后续消费另有protocol。")})
add("Expr", [D + " §2.1", R + " §2.2"], {"value": ("CURRENT_EXPRESSION_STATEMENT", "模块/函数表达式语句应求值并处理结果生命周期，交互模式另有displayhook。", "G4: 分册未明确Expr.value的discard/释放与interactive输出连接；只能借catalog条目。")})
marker("Pass", D + " §2", "无字段语句应仅Fallthrough并保留source。", "G4: 三分册没有Pass的明确phase/Fallthrough规则，catalog分类不能替代。")
add("TypeIgnore", D + " §2.1", {"lineno": ("SOURCE_METADATA", "应是parser类型忽略条目的源行号。", "G4: Module.type_ignores仅泛称行号/type metadata，未给TypeIgnore.lineno字段归属。"), "tag": ("SOURCE_METADATA", "应保存类型忽略标记文本/限定。", "G4: TypeIgnore.tag未给精确metadata规则。")})
marker("Load Store Del", [D + " §2.2", D + " §7", D + " §8"], "无字段context marker，选择父节点访问/target协议而非独立执行；对应父节点遗漏另记GAP。")

# Control mappings below were assigned by reading the actual per-field protocols.
add("If", C + " §1.1", {"test": ("CURRENT_CONDITION", "先T(test)，后态接所选suite，异常/挂起不执行suite。"), "body": ("TRUE_BRANCH", "仅true边Suite；Return等不回普通merge。"), "orelse": ("FALSE_BRANCH", "仅false边Suite，elif为嵌套If，空即Fallthrough。")})
add("IfExp", C + " §1.1", {"test": ("CURRENT_CONDITION", "先T(test)，不按字段排列求body。"), "body": ("SELECTED_BRANCH", "true才V或T(body)，返回实际引用。"), "orelse": ("SELECTED_BRANCH", "false才V或T(orelse)，未执行支无运行结果。")})
add("BoolOp", C + " §1.2", {"op": ("CONTROL_SELECTOR", "And假短路/Or真短路，无独立求值。"), "values": ("SHORT_CIRCUIT_EVALUATION", "源序按V/T continuation组合，值上下文末项不额外Truth，返回选中operand引用。")})
marker("And Or", C + " §1.2", "无字段控制marker，选择And/Or的短路方向；不单独求值。")
add("Compare", C + " §1.3", {"left": ("CURRENT_EVALUATION", "先V(left)。"), "ops": ("COMPARISON_SELECTORS", "与comparators对齐，具体rich/identity/membership协议；无独立marker效果。"), "comparators": ("SHORT_CIRCUIT_EVALUATION", "逐项求一次，保留中间引用作下一左值，中间结果按Truth决定继续；最后V/T上下文分开。")})
marker("Eq NotEq Lt LtE Gt GtE Is IsNot In NotIn", C + " §1.3", "无字段比较marker；选择rich-comparison/reflected、身份或membership协议，Truth/异常等在父Compare保留。")
add("While", C + " §2.1", {"test": ("REPEATED_CONDITION", "每次用最新carried状态T；零次false可到else。"), "body": ("LOOP_BODY", "true才执行；Fallthrough/本loop Continue回test。"), "orelse": ("NATURAL_EXIT", "test false进入，Break绕过，其他completion经cleanup。")})
for name, sec, iter_rule in [("For", "§2.2", "V(iter)/GetIterator一次；只Advance的StopIteration为exhaustion。"), ("AsyncFor", "§2.3", "V(iter)/__aiter__一次，__anext__调用与Await；只该advance的StopAsyncIteration为exhaustion。")]:
    add(name, [C + " " + sec, C + " §2.2"], {"target": ("EACH_ITEM_STORE", "每个item后Store，可解包/部分写；零次不新绑定。"), "iter": ("LOOP_ENTRY", iter_rule), "body": ("LOOP_BODY", "target成功后Suite，Continue回advance而非重求iter。"), "orelse": ("NATURAL_EXHAUSTION", "仅自然exhaustion，Break不走；body同名异常不吞。"), "type_comment": ("SOURCE_METADATA", "静态类型/source元数据，不求值。")})
for name, result_fields in [("ListComp", ("elt",)), ("SetComp", ("elt",)), ("DictComp", ("key", "value")), ("GeneratorExp", ("elt",))]:
    defs = {n: ("RESUME_ITERATION" if name == "GeneratorExp" else "FILTERED_ITERATION", "通过全部filters才求结果；Dict key先value后；set/dict插入含hash/equality；GeneratorExp逐次Yield。") for n in result_fields}
    defs["generators"] = ("NESTED_ITERATION", "按外到内嵌套，最外iter/iterator在创建上下文，其余到到达/恢复；scope不泄漏，状态/异常保留。")
    add(name, [C + " §3.1", C + " §3.2"], defs)
add("comprehension", [C + " §3.1", C + " §3.2"], {"target": ("EACH_ITEM_STORE", "当前item写iteration scope，walrus containing-scope另有compile限制。"), "iter": ("OUTER_CREATION_OR_INNER_ITERATION", "第0在外层创建时求/建iterator，第i>0在前层filters成功后每次求。"), "ifs": ("FILTER_CONDITIONS", "target成功后依序T，首false跳本层advance，后续不执行。"), "is_async": ("COMPILE_PROTOCOL_SELECTOR", "0/1选择同步或async advance，非运行Truth；不能单独决定全表达式同步性。")})
for name, sec in [("Try", "§4.1"), ("TryStar", "§4.4")]:
    add(name, [C + " " + sec, C + " §4.3"], {"body": ("CURRENT_SUITE", "先Suite，只有body Raise进入本handlers；已发生状态保留。"), "handlers": ("EXCEPTION_DISPATCH", "Try首匹配；TryStar split/merge并继续原剩余组，matcher失败与body失败区分。"), "orelse": ("BODY_FALLTHROUGH", "仅body普通完成执行，异常不交本兄弟handlers。"), "finalbody": ("CLEANUP", "包围所有出口；接pending及当前state，普通完成保留pending，transfer替换，Suspend保存。")})
add("ExceptHandler", [C + " §4.2", C + " §4.4"], {"type": ("EXCEPTION_DISPATCH", "搜索到才V/type检查/匹配；bare标记或except*限制；错误结束当前分派。"), "name": ("HANDLER_BINDING", "identifier，命中绑定异常并设置handled context，退出清除不恢复旧绑定。"), "body": ("MATCHED_HANDLER", "命中后Suite；保留新异常/后态，退出恢复外层handler context。")})
add("Raise", C + " §5", {"exc": ("CURRENT_EVALUATION", "None走bare-raise context；否则V，类/实例normalization及错误保留。"), "cause": ("CURRENT_EVALUATION", "exc表达式后求cause再normalize；None显式抑制，保留context/traceback状态。")})
add("Return", C + " §5", {"value": ("CURRENT_EVALUATION_CLEANUP", "先求或用None，再带引用Return到所属函数边界，经介入cleanup；异常/挂起不提前Return。")})
marker("Break", C + " §5", "无字段；属于活动loop的typed BreakTarget，经cleanup到after，跳本loop else。")
marker("Continue", C + " §5", "无字段；typed ContinueTarget经cleanup到test/advance，不重求for.iter。")
for name, sec in [("With", "§6.1"), ("AsyncWith", "§6.3")]:
    add(name, [C + " " + sec, C + " §6", C + " §6.2"], {"items": ("NESTED_ENTER", "逐项求manager/lookup/enter，成功后注册cleanup；AsyncWith的aenter/aexit另接Await。"), "body": ("ENTERED_SUITE", "所有items成功且target写完后Suite，退出反序；pending抑制/替换按退出协议。"), "type_comment": ("SOURCE_METADATA", "类型comment不运行。")})
add("withitem", [C + " §6.1", C + " §6.3"], {"context_expr": ("EACH_ENTER", "V得manager，类型特殊方法lookup保存exit；enter成功才注册本项cleanup。"), "optional_vars": ("PROTECTED_STORE", "非空Store enter结果，失败仍在本项exit保护；为空也处理引用生命周期。")})
add("Yield", C + " §7.2", {"value": ("CURRENT_EVALUATION_SUSPEND", "先V或None，输出Suspend；下一resume请求成为表达式结果/异常，保存frame而接当前共享state。")})
add("YieldFrom", C + " §7.3", {"value": ("DELEGATION", "先V/GetIterator，按next/send/throw/close委托，StopIteration.value为最终表达式结果，保存父/子状态。")})
add("Await", C + " §7.4", {"value": ("AWAIT_DRIVE", "V并验证awaitable/iterator，drive中间yield为scheduler请求，StopIteration.value为结果，可零次Suspend。")})
add("Match", C + " §8.1", {"subject": ("CURRENT_EVALUATION", "一次V并保留引用，非每case重求。"), "cases": ("CASE_SELECTION", "按序Pattern，再可选guard，选中body后不再下一case；NoMatch/guard假保留状态。")})
add("match_case", C + " §8.1", {"pattern": ("PATTERN_DISPATCH", "Match/NoMatch/Raise三分支，结构提取与子匹配分开，失败binding受策略约束。"), "guard": ("AFTER_PATTERN_MATCH", "匹配成功才T，可异常/挂起，假不回滚capture。"), "body": ("SELECTED_CASE", "guard通过后Suite，完毕不继续下一case。")})
add("MatchValue", [C + " §8.2", C + " §8.3"], {"value": ("PATTERN_REACHED", "合法literal/dotted value lookup，equality/Truth匹配，有限缓存需版本化规则。")})
add("MatchSingleton", C + " §8.2", {"value": ("STATIC_PATTERN_SELECTOR", "None/True/False按identity匹配，不调用equality。")})
add("MatchSequence", [C + " §8.2", C + " §8.3"], {"patterns": ("PATTERN_MATCH", "sequence资格/长度/结构提取后按序子匹配；提取可预先读取后项，至多一star，非任意iterable。")})
add("MatchMapping", [C + " §8.2", C + " §8.3"], {"keys": ("PATTERN_KEY_PROTOCOL", "mapping/长度满足后求key；动态重复ValueError，字面重复compile拒绝。"), "patterns": ("PATTERN_MATCH", "get(key,sentinel)取值，缺键NoMatch，hash/get异常传播；允许先批量提取。"), "rest": ("PATTERN_BINDING", "有名构造剩余dict并绑定，缺省不绑定，**_非法。")})
add("MatchClass", [C + " §8.2", C + " §8.3"], {"cls": ("PATTERN_CLASS_PROTOCOL", "到达才求class并验证type/isinstance，metaclass效果/异常保留。"), "patterns": ("PATTERN_POSITIONAL", "__match_args__转属性，tuple/string/长度校验；builtin self-match单列。"), "kwd_attrs": ("STATIC_ATTRIBUTE_SELECTORS", "字符串与positional名去重，冲突TypeError，不独立求表达式。"), "kwd_patterns": ("PATTERN_MATCH", "与kwd_attrs对齐，属性先取可批量，AttributeError为NoMatch，其他异常传出。")})
add("MatchStar", C + " §8.2", {"name": ("SEQUENCE_REST_BINDING", "sequence中有名则中段新list绑定，None wildcard无绑定。")})
add("MatchAs", C + " §8.2", {"pattern": ("PATTERN_MATCH", "非空先子匹配，成功才as；空为capture/wildcard。"), "name": ("PATTERN_BINDING", "有名绑定当前subject引用，不复制；都空为_。")})
add("MatchOr", C + " §8.2", {"patterns": ("ALTERNATIVE_SELECTION", "依序首Match胜出，编译要求同名集合，失败状态不能按名字去重。")})
add("Assert", C + " §9", {"test": ("COMPILE_GATED_CONDITION", "先按optimize/__debug__决定存在；启用才T，true直接过。"), "msg": ("FALSE_ASSERT_BRANCH", "仅test false才V；失败先传播，不再构造AssertionError；缺省无参数。")})

abstract = {"AST", "mod", "stmt", "expr", "expr_context", "boolop", "operator", "unaryop", "cmpop", "excepthandler", "pattern", "type_ignore", "type_param", "slice"}
compat = {"Index", "ExtSlice", "Suite", "AugLoad", "AugStore", "Param"}
canonical = {name: value for name, value in vars(ast).items()
             if isinstance(value, type) and issubclass(value, ast.AST)
             and value.__module__ == "ast" and name == value.__name__
             and name not in abstract | compat}
assert set(rows) == set(canonical), (set(canonical) - set(rows), set(rows) - set(canonical))
for name, cls in canonical.items():
    assert set(rows[name]["fields"]) == set(cls._fields), (name, cls._fields, rows[name]["fields"])
    rows[name]["canonical_fields"] = list(cls._fields)
    rows[name]["canonical_attributes"] = list(cls._attributes)
    rows[name]["has_fields"] = bool(cls._fields)
    assert cls._fields or rows[name]["node_rule"]

documents = {p: hashlib.sha256((ROOT / "documents.initial" / Path(p).name).read_bytes()).hexdigest() for p in (D, C, R, W)}
field_rows = [r for node in rows.values() for r in node["fields"].values()]
out = {
    "schema": "scar.model-stage1.manual-field-coverage", "version": 1,
    "status": "GAP", "scope": "M2 protocol specification only; no M1/M3 implementation claim",
    "python": sys.version, "canonical_selection": {"excluded_abstract": sorted(abstract), "excluded_compat": sorted(compat)},
    "method": "Manual per-field reading; reflection checks field conservation, not semantic coverage. References target documents.initial snapshot, not keyword matching.",
    "document_snapshots_sha256": documents,
    "summary": {"constructs": len(rows), "fields": len(field_rows), "construct_gaps": sum(r["status"] == "GAP" for r in rows.values()), "field_gaps": sum(r["status"] == "GAP" for r in field_rows), "fieldless_constructs": sum(not r["fields"] for r in rows.values())},
    "source_attributes_rule": {"phase": "SOURCE_METADATA", "references": [D + " §2.1", D + " §13", W + " §7"], "rule": "lineno/col_offset/end_lineno/end_col_offset等来源属性不属于_fields；保留归属/源码版本，不按属性求值或新建运行计算。"},
    "constructs": [rows[name] for name in sorted(rows)],
}
(ROOT / "field_coverage.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
print(json.dumps(out["summary"], indent=2))
