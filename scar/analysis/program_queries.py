"""Static field and boundary queries using the one dependency session/view."""
from __future__ import annotations

from scar.analysis.program_dependency_session import ProgramDependencySession


def query_program_values(directory, *, file=None, entry=None, kind=None, node=None, roots=None,
                         context=(), budget=None, value_budget=None):
    from scar.analysis.program_value_analysis import ProgramValueAnalysis
    with ProgramDependencySession(directory, budget=budget) as session:
        if roots is None:
            if node is None:
                raise ValueError("value inference needs an original typed root")
            roots = (session.point(file=file, entry=entry, kind=kind, node=node, context=context),)
        return ProgramValueAnalysis(session, budget=value_budget).analyze(roots)


def query_program_boundary(directory, *, file=None, entry=None, kind=None, nodes=(), operations=None,
                           context=(), budget=None, max_members=16384):
    from scar.analysis.program_regions import analyze_boundary
    with ProgramDependencySession(directory, budget=budget) as session:
        if operations is None:
            operations = tuple(session.point(file=file, entry=entry, kind=kind, node=node, context=context)
                               for node in nodes)
        return analyze_boundary(session.graph(), operations, max_members=max_members)
