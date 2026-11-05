"""Bind existing F4 query rules to an explicit compiler service.

No target AST, old module global or builtin is changed. The two trusted query
methods receive a private globals mapping with compile bound to the service;
their original bytecode and all other rule dependencies are reused. This
keeps sealed source-only stores readable while new context stores evolve.
"""
import __future__
from types import FunctionType,MethodType

from scar.analysis.source_compilation_contexts import CompilationContextIndex
from scar.analysis.source_scope_annotation_interfaces import ScopeAnnotationIndex
from scar.analysis.source_root_interfaces import RootInterfaceIndex
from scar.analysis.source_productions import ProductionSourceIndex
from scar.ir.program.source_context_variants import SourceContextVariant


class ContextCompiler:
    def __init__(self,context,source_path):
        self.context,self.source_path=context,source_path

    def __call__(self,source,filename,mode,flags=0,dont_inherit=True,optimize=-1,**kwargs):
        if not dont_inherit:
            raise ValueError('source compiler queries require explicit caller-independent flags')
        if mode!=self.context.mode:
            raise ValueError('source compiler query changed its compilation mode')
        filename=self.context.filename if filename==self.source_path else filename
        return compile(source,filename,mode,flags=flags | self.context.compiler_input_flags,
            dont_inherit=True,optimize=self.context.optimize if optimize==-1 else optimize,**kwargs)


def _bind_query(index,compiler):
    original=type(index)._collect
    environment=dict(original.__globals__,compile=compiler)
    function=FunctionType(original.__code__,environment,original.__name__,
        original.__defaults__,original.__closure__)
    function.__kwdefaults__=original.__kwdefaults__
    index._collect=MethodType(function,index)
    return index


def install_compile_context(source,variant):
    """Use only a context whose C1 material is the source's actual parent."""
    if type(source) is not ProductionSourceIndex or type(variant) is not SourceContextVariant:
        raise TypeError('original production source and verified context variant required')
    if source.context.material!=variant.material:
        raise ValueError('F4 source and effective context have different C1 parents')
    compiler=ContextCompiler(variant.context,source.input.path)
    source._scope_annotations=_bind_query(ScopeAnnotationIndex(source),compiler)
    source._compilation_contexts=_bind_query(CompilationContextIndex(source),compiler)
    source._roots=RootInterfaceIndex(source)
    source._roots.future=bool(variant.context.compiled_future_flags & __future__.annotations.compiler_flag)
    return source
