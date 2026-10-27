"""Typed code-observation/source correspondence for automatic inventories.

This bridge retains path candidates and exact code-object witnesses separately.
It does not certify callable bindings, input values, effects or loader identity.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from enum import Enum
import re

from scar.analysis.correspondence_v2 import (
    CodeSourceWitness, CompileContext, JoinStatus, SourceCodeIndex, _qualname,
)
from scar.ir.ids import CodeID
from scar.ir.program.runtime_sources import (
    RuntimeSeed, RuntimeSeedStatus, RuntimeTrace, RuntimeTraceBudget,
)
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.program.ids import RegionID
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


@dataclass(frozen=True, slots=True)
class CompileTrial:
    filename: str
    context: CompileContext
    status: str
    code_objects: int = 0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeCodeBinding:
    observation_index: int
    source_path: str | None
    source_snapshot: SourceSnapshot | None
    status: JoinStatus
    reason: str
    candidate_definitions: tuple[OperationDefinitionID, ...] = ()
    witnesses: tuple[CodeSourceWitness, ...] = ()
    tried_contexts: tuple[CompileTrial, ...] = ()


class RuntimeDefinitionKind(str, Enum):
    MODULE_INITIALIZER = "MODULE_INITIALIZER"
    SOURCE_DEFINITION = "SOURCE_DEFINITION"


@dataclass(frozen=True, slots=True)
class RuntimeDefinitionAnchor:
    definition: OperationDefinitionID
    source_snapshot: SourceSnapshot
    source: SourceReference | None
    kind: RuntimeDefinitionKind
    qualname: str
    inventory_definition: OperationDefinitionID | None = None
    core_region: RegionID | None = None


@dataclass(frozen=True, slots=True)
class RuntimeScope:
    trace: RuntimeTrace
    seeds: tuple[RuntimeSeed, ...]
    bindings: tuple[RuntimeCodeBinding, ...]
    definition_index: tuple[RuntimeDefinitionAnchor, ...]
    max_compile_attempts: int
    compilation_attempts: int

    def __post_init__(self):
        check_compile_limit(self.max_compile_attempts)
        if type(self.compilation_attempts) is not int or not 0 <= self.compilation_attempts <= self.max_compile_attempts:
            raise ValueError("invalid runtime compilation attempt count")
        count = len(self.trace.observations)
        if len(self.seeds) != count or len(self.bindings) != count:
            raise ValueError("runtime scope must account for every code observation")
        if tuple(seed.observation_index for seed in self.seeds) != tuple(range(count)):
            raise ValueError("runtime seeds must correspond to observation order")
        if tuple(binding.observation_index for binding in self.bindings) != tuple(range(count)):
            raise ValueError("runtime bindings must correspond to observation order")
        indexed = {anchor.definition for anchor in self.definition_index}
        if len(indexed) != len(self.definition_index):
            raise ValueError("runtime definition index contains duplicate identities")
        if any(target not in indexed for binding in self.bindings for target in binding.candidate_definitions):
            raise ValueError("runtime source definition link is dangling")

    def summary(self):
        return {
            "trace_records": self.trace.manifest.record_count,
            "code_observation_groups": len(self.trace.observations),
            "trace_issues": len(self.trace.issues),
            "source_selection": dict(sorted(Counter(seed.status.value for seed in self.seeds).items())),
            "code_source_status": dict(sorted(Counter(binding.status.value for binding in self.bindings).items())),
            "code_reproduced_groups": sum(bool(binding.witnesses) for binding in self.bindings),
            "source_definition_links": len(self.definition_index),
            "core_region_links": sum(anchor.core_region is not None for anchor in self.definition_index),
            "compilation_attempts": self.compilation_attempts,
            "all_paths_observed": False, "callable_bindings_established": False,
            "effect_equivalence_established": False,
        }


def check_compile_limit(value):
    if type(value) is not int or value < 1:
        raise ValueError("max_compile_attempts must be a positive exact integer")


def check_runtime_ceiling(requested: RuntimeTraceBudget, ceiling: RuntimeTraceBudget):
    if type(requested) is not RuntimeTraceBudget or type(ceiling) is not RuntimeTraceBudget:
        raise TypeError("runtime budgets must be RuntimeTraceBudget")
    requested.__post_init__()
    ceiling.__post_init__()
    for field in requested.__dataclass_fields__:
        if getattr(requested, field) > getattr(ceiling, field):
            raise ValueError("report exceeds independent runtime verifier budget: " + field)


def available_paths(seeds):
    return tuple(sorted({seed.candidate_path for seed in seeds
                         if seed.status is RuntimeSeedStatus.AVAILABLE_PYTHON}))


class RuntimeScopeBuilder:
    """Attach evidence to the same prepared snapshots used for source lowering."""

    def __init__(self, trace, seeds, max_compile_attempts=1024):
        check_compile_limit(max_compile_attempts)
        self.trace, self.seeds = trace, seeds
        self.max_compile_attempts = max_compile_attempts
        self.compilation_attempts = 0
        self.by_path = defaultdict(list)
        self.bindings = {}
        self.definition_index = {}
        for seed in seeds:
            admitted = seed.status is RuntimeSeedStatus.AVAILABLE_PYTHON
            if admitted:
                self.by_path[seed.candidate_path].append(seed.observation_index)
            self.bindings[seed.observation_index] = RuntimeCodeBinding(
                seed.observation_index, seed.candidate_path or None, None,
                JoinStatus.MISSING if admitted else JoinStatus.OUT_OF_SCOPE,
                "source not prepared: discovery/read/preparation boundary" if admitted else seed.reason)

    def bind(self, context):
        """Return definition candidates to prioritize, without confirming calls."""
        path = str(context.path)
        observations = self.by_path.get(path, ())
        if not observations:
            return frozenset()
        snapshot = context.semantics.sources[path]
        index = SourceCodeIndex(path, context.text, {snapshot.fingerprint})
        source_atoms = {atom.id.wire: atom.reference for atom in context.semantic.source_atoms.values()}
        definitions = defaultdict(list)
        for definition in context.semantic.definitions.values():
            if definition.source_file == path and (name := _qualname(context.semantic, definition)) is not None:
                definitions[name].append(definition)
        contexts = tuple(CompileContext(optimize=level) for level in (0, 1, 2))
        preferred = set()
        for observation_index in observations:
            observation = self.trace.observations[observation_index]
            parsed = CodeID.parse_key(observation.code_id)
            candidates = tuple(sorted((definition.id for definition in definitions.get(parsed.qualname, ())
                if (definition.metadata.get("phase") == "module_initialization" and parsed.line == 1)
                or parsed.line in index.first_lines.get(definition.source_start, {definition.source_start})),
                key=lambda item: item.wire))
            preferred.update(candidates)
            for candidate in candidates:
                definition = context.semantic.definitions[candidate]
                kind = (RuntimeDefinitionKind.MODULE_INITIALIZER
                        if definition.metadata.get("phase") == "module_initialization"
                        else RuntimeDefinitionKind.SOURCE_DEFINITION)
                self.definition_index[candidate] = RuntimeDefinitionAnchor(candidate, snapshot,
                    source_atoms.get(definition.code_id), kind, parsed.qualname)
            trials, witnesses = [], []
            if re.fullmatch(r"pycode-sha256:[0-9a-f]{64}", parsed.version) is None:
                self.bindings[observation_index] = RuntimeCodeBinding(
                    observation_index, path, snapshot, JoinStatus.MISSING,
                    "loaded code digest missing; filename is only a source candidate", candidates)
                continue
            filenames = tuple(dict.fromkeys((parsed.source, *(hint.value for hint in observation.filename_hints))))
            budget_exhausted = False
            for filename in filenames:
                for compile_context in contexts:
                    if (filename, compile_context) not in index.compiled:
                        if self.compilation_attempts >= self.max_compile_attempts:
                            budget_exhausted = True
                            continue
                        self.compilation_attempts += 1
                    compiled, attempted = index.compile(filename, compile_context)
                    trials.append(CompileTrial(filename, compile_context, attempted["status"],
                                               attempted.get("code_objects", 0), attempted.get("reason", "")))
                    if any(digest == parsed.version and name == parsed.qualname and line == parsed.line
                           for digest, name, line in compiled):
                        witnesses.append(CodeSourceWitness(path, snapshot.fingerprint, observation.code_id,
                            parsed.version, filename, compile_context, parsed.qualname, parsed.line))
            if witnesses:
                status = (JoinStatus.VERIFIED if len(candidates) == 1 else
                          JoinStatus.AMBIGUOUS if candidates else JoinStatus.MISSING)
                reason = ("exact code object reproduced; unique source definition" if len(candidates) == 1 else
                          "exact code object reproduced; source definition ambiguous or unavailable")
            elif budget_exhausted:
                status, reason = JoinStatus.MISSING, "runtime code verification budget exhausted"
            else:
                status, reason = JoinStatus.MISMATCH, "exact code digest not reproduced; source/filename/compile context remain unresolved"
            self.bindings[observation_index] = RuntimeCodeBinding(
                observation_index, path, snapshot, status, reason, candidates, tuple(witnesses), tuple(trials))
        return frozenset(preferred)

    def finish(self):
        return RuntimeScope(self.trace, self.seeds,
                            tuple(self.bindings[i] for i in range(len(self.trace.observations))),
                            tuple(self.definition_index[key] for key in sorted(self.definition_index, key=lambda key: key.wire)),
                            self.max_compile_attempts, self.compilation_attempts)

    def file_emitted(self, file):
        definitions = {definition.id for definition in file.definitions}
        bodies = {body.definition: body.graph.root for body in file.bodies if body.graph is not None}
        for identity, anchor in tuple(self.definition_index.items()):
            if anchor.source_snapshot.path == file.snapshot.path:
                self.definition_index[identity] = replace(anchor,
                    inventory_definition=identity if identity in definitions else None,
                    core_region=bodies.get(identity))

    def file_failed(self, path):
        # Retain any exact code-only witness but do not reference definitions
        # from an inventory that was not emitted. Work already spent stays
        # charged to the shared compilation budget.
        for observation_index in self.by_path.get(path, ()):
            binding = self.bindings[observation_index]
            self.bindings[observation_index] = replace(binding, status=JoinStatus.MISSING,
                reason="source preparation/inventory failed; no definition link emitted", candidate_definitions=())
        self.definition_index = {identity: anchor for identity, anchor in self.definition_index.items()
                                 if anchor.source_snapshot.path != path}
