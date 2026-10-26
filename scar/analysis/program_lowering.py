"""Automatically connect versioned Python source to the program core.

The result is a conservative model of a selected function body. Python
dispatch, external effects and live call targets are not certified by parsing.
All target code is read as source; construction never imports or executes it.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, replace
from functools import cached_property
import hashlib
import json
from pathlib import Path
import symtable
import tokenize
from types import MappingProxyType

from scar.analysis.control_flow_v2 import _build_generated_source_layers, validate_source_control_flow
from scar.analysis.source_semantics_v2 import validate_source_semantics
from scar.ir.program.codec import dumps as dump_graph, _has_frame_root_capability
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.functions import BodyEntryInterface, BodyLoweringProfile, FormalPort
from scar.ir.program.module_entries import (ModuleBodyOverlay, ModuleEntryProfile,
    ModulePrefixOverlay, ModuleBodyExpansionProfile, StructuredFrameBodyOverlay, FrameBodyProfile)
from scar.ir.program.frames import (
    FrameBind, FrameDiscard, FrameEnter, FrameExit, FrameFormal, FrameModel,
)
from scar.ir.program.structured import StructuredBodyModel
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, LiteralOrigin, Operation,
    OperationResult, ProgramGraph, ReferenceValue, Region, Stability, StateAccess, StateLocation,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    ValueKind, ValueType,
)
from scar.ir.program.source import (
    CallTarget, CandidateArgument, CandidateResult, GapKind, LoweringGap,
    LoweringMetadata, OperationSource, SourceRole,
    UseSource, ValueSource,
)
from scar.ir.program.source_language import SourceLanguageOverlay, reject_extended_protocols
from scar.ir.program.validation import require_valid
from scar.ir.record_codec import encode
from scar.ir.semantics_v2 import Opcode, SourceExecutionPrecondition
from scar.ir.v2._validation import record_errors
from scar.ir.v2.common import EvidenceKind
from scar.ir.v2.common import SourceReference


_ASSUMPTIONS = (
    SourceExecutionPrecondition.STANDARD_FUNCTION_LOCALS,
    SourceExecutionPrecondition.NO_EXTERNAL_NAMESPACE_MUTATION,
)
_REF = ValueType(ValueKind.REFERENCE)
_BOOL = ValueType(ValueKind.DATA, "builtins.bool")


def _key(*parts):
    return hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()[:32]


def _span(node):
    return (type(node).__name__, node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)


@dataclass(frozen=True)
class SourceProgram:
    graph: ProgramGraph | None
    metadata: LoweringMetadata
    semantic: object
    semantics: object
    control: object
    profile: BodyLoweringProfile | ModuleEntryProfile | ModuleBodyExpansionProfile | FrameBodyProfile = BodyLoweringProfile.LEGACY
    interface: BodyEntryInterface | None = None
    frame: FrameModel | None = None
    structured: StructuredBodyModel | None = None
    language: SourceLanguageOverlay | None = None
    module: ModuleBodyOverlay | ModulePrefixOverlay | StructuredFrameBodyOverlay | None = None

    def summary(self):
        """Separate declaration/link counts from program and effect coverage."""
        if type(self.module) is StructuredFrameBodyOverlay:
            from scar.ir.record_codec import encode
            return {'entry_kind':'MAPPING_FRAME','entry':self.metadata.entry,
                'body_status':self.module.status.value,'graph_present':self.graph is not None,
                'entry_regions':len(self.graph.regions) if self.graph else 0,
                'construction_operations':self.module.operations_emitted,
                'top_level_statement_interfaces_expanded':len(self.module.prefix.statements) if self.module.prefix else 0,
                'expanded_statement_records':len(self.module.expansions),
                'remaining_statement_count':len(self.module.remaining.subject.statements) if self.module.remaining else 0,
                'required_body_expansion':'REQUIRED' if self.module.remaining else 'SOURCE_PROTOCOL_INTERNALS_REMAIN_OPEN',
                'source_census':encode(self.module.census),'namespace_policy':self.module.namespace_policy.value,
                'completion_profile':self.module.completion_profile.value,
                'namespace_content_established':False,'namespace_alias_established':False,
                'runtime_target_verified':False,'import_module_object_established':False,
                'whole_program_coverage_established':False,'fine_grained_state_effects_established':False,
                'transformation_authorized':False}
        if type(self.module) is ModulePrefixOverlay:
            from scar.ir.record_codec import encode
            return {"entry_kind": "MAPPING_FRAME", "entry": self.metadata.entry,
                "body_status": self.module.status.value, "graph_present": self.graph is not None,
                "entry_regions": len(self.graph.regions) if self.graph else 0,
                "source_statement_interfaces_expanded": 1, "body_internal_operations_recovered": 0,
                "remaining_statement_count": len(self.module.remaining.subject.statements),
                "required_body_expansion": self.module.remaining.required_expansion.value,
                "import_internal_expansion": "REQUIRED", "namespace_content_established": False,
                "source_census": encode(self.module.census), "construction_operations": self.module.operations_emitted,
                "frontier_counts": dict(sorted(Counter(row.kind for row in self.module.frontiers).items())),
                "whole_program_coverage_established": False, "runtime_target_verified": False,
                "namespace_alias_established": False, "import_module_object_established": False,
                "fine_grained_state_effects_established": False, "transformation_authorized": False}
        if self.module is not None:
            from scar.ir.record_codec import encode
            return {"entry_kind": "MAPPING_FRAME", "entry": self.metadata.entry,
                "body_status": self.module.status.value, "graph_present": self.graph is not None,
                "entry_regions": len(self.graph.regions) if self.graph is not None else 0,
                "body_internal_operations_recovered": 0,
                "required_body_expansion": (self.module.unexpanded_body.required_expansion.value
                    if self.module.unexpanded_body is not None else None),
                "source_census": encode(self.module.census),
                "construction_operations": self.module.operations_emitted,
                "frontier_counts": dict(sorted(Counter(row.kind for row in self.module.frontiers).items())),
                "whole_program_coverage_established": False, "runtime_target_verified": False,
                "namespace_alias_established": False, "import_module_object_established": False,
                "fine_grained_state_effects_established": False, "transformation_authorized": False}
        graph = self.graph
        return {
            "entry": self.metadata.entry,
            "graph_present": graph is not None,
            "counts": {
                "regions": len(graph.regions) if graph else 0,
                "blocks": sum(len(region.blocks) for region in graph.regions) if graph else 0,
                "operations": len(graph.operations) if graph else 0,
                "values": len(graph.values) if graph else 0,
                "uses": sum(len(operation.uses) for operation in graph.operations) if graph else 0,
                "state_locations": len(graph.locations) if graph else 0,
                "incomplete_effect_operations": sum(not op.effects_complete for op in graph.operations) if graph else 0,
                "operation_source_links": len(self.metadata.operation_links),
                "value_source_links": len(self.metadata.value_links),
                "use_source_links": len(self.metadata.use_links),
                "candidate_calls": len(self.metadata.call_targets),
                "candidate_interfaces": sum(bool(target.arguments) for target in self.metadata.call_targets),
                "parsed_source_atoms": len(self.semantic.source_atoms),
                **({"binding_definitions": len(graph.binding_definitions) if graph else 0,
                    "binding_reads": len(graph.binding_reads) if graph else 0,
                    "typed_protocols": len(self.structured.protocols) if self.structured else 0,
                    "loops": len(self.structured.loops) if self.structured else 0}
                   if self.profile in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV) else {}),
            },
            "gap_counts": dict(sorted(Counter(gap.kind.value for gap in self.metadata.gaps).items())),
            "source_selection": ("one file parsed; selected structured synchronous body; unsupported protocols remain coverage failures"
                                 if self.profile in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV) else
                                 "one file parsed; selected bound-frame body only; candidate calls remain interfaces"
                                 if self.profile is BodyLoweringProfile.BOUND_FRAME else
                                 "one file parsed; selected body and available same-file call candidates lowered"),
            "whole_program_coverage_established": False,
            "fine_grained_state_effects_established": False,
            "runtime_target_verified": False,
            "transformation_authorized": False,
        }

    def to_dict(self):
        if type(self.module) is StructuredFrameBodyOverlay:
            from scar.ir.program.module_entries import encode_frame_body
            if (self.profile is not self.module.profile or self.profile not in (
                    FrameBodyProfile.STRUCTURED_MAPPING_314_V1,FrameBodyProfile.STRUCTURED_MAPPING_PROPAGATION_314_V1) or self.graph is None
                    or any(value is not None for value in (self.interface,self.frame,self.structured,self.language))):
                raise ValueError('SP8 requires its explicit core FrameRoot/source overlay only')
            return {'schema':'scar.source-program','schema_version':8,'entry_kind':'MAPPING_FRAME',
                'profile':self.profile.value,'status':self.module.status.value,
                'scope':'structured source mapping frame; exact remaining source and runtime/effect debt retained',
                'metadata':encode(self.metadata),'module':encode_frame_body(self.module),
                'graph':json.loads(dump_graph(self.graph)),'semantic':self.semantic.to_dict(),
                'semantics':self.semantics.to_dict(),'control':self.control.to_dict(),'summary':self.summary(),
                'runtime_target_verified':False,'transformation_authorized':False}
        # Every implemented wrapper is historical source1-7. A future source8
        # must enter its explicit new branch rather than upgrade an old ABI.
        if self.graph is not None and _has_frame_root_capability(self.graph):
            raise ValueError("historical source1-7 writer cannot contain frame-root core capability")
        if type(self.module) is ModulePrefixOverlay:
            from scar.ir.program.module_entries import encode_module_prefix
            if (self.profile is not ModuleBodyExpansionProfile.IMPORT_PREFIX_314_V1 or self.interface is not None
                    or self.frame is not None or self.structured is not None or self.language is not None):
                raise ValueError("v7 prefix requires its separate capability and unchanged mapping ABI")
            return {"schema": "scar.source-program", "schema_version": 7,
                "entry_kind": "MAPPING_FRAME", "profile": self.profile.value,
                "status": self.module.status.value,
                "scope": "one original Import interface and exact residual module statement slice; runtime/content/effects remain OPEN",
                "metadata": encode(self.metadata), "module": encode_module_prefix(self.module),
                "graph": json.loads(dump_graph(self.graph)) if self.graph is not None else None,
                "semantic": self.semantic.to_dict(), "semantics": self.semantics.to_dict(),
                "control": self.control.to_dict(), "summary": self.summary(),
                "runtime_target_verified": False, "transformation_authorized": False}
        if self.module is not None:
            from scar.ir.program.module_entries import encode_module_overlay
            if (self.profile is not ModuleEntryProfile.EXEC_MAPPING_314_V1 or self.interface is not None
                    or self.frame is not None or self.structured is not None or self.language is not None):
                raise ValueError("v6 mapping entry cannot acquire function ABI overlays")
            return {"schema": "scar.source-program", "schema_version": 6,
                "entry_kind": "MAPPING_FRAME", "profile": self.profile.value,
                "status": self.module.status.value,
                "scope": "selected exec-root mapping frame; body/runtime/effects debt remains explicit",
                "metadata": encode(self.metadata), "module": encode_module_overlay(self.module),
                "graph": json.loads(dump_graph(self.graph)) if self.graph is not None else None,
                "semantic": self.semantic.to_dict(), "semantics": self.semantics.to_dict(),
                "control": self.control.to_dict(), "summary": self.summary(),
                "runtime_target_verified": False, "transformation_authorized": False}
        if self.language is None:
            reject_extended_protocols(self.structured)
        elif self.profile is not BodyLoweringProfile.STRUCTURED_ENV:
            raise ValueError("extended language wrapper requires the unchanged environment entry ABI")
        document = {
            "schema": "scar.source-program", "schema_version": (5 if self.language is not None else
                1 if self.profile is BodyLoweringProfile.LEGACY else
                4 if self.profile is BodyLoweringProfile.STRUCTURED_ENV else
                3 if self.profile is BodyLoweringProfile.STRUCTURED_BODY else 2),
            "status": ("UNSUPPORTED" if self.graph is None else
                       "LOWERED_WITH_GAPS" if self.metadata.gaps else "LOWERED"),
            "scope": "selected synchronous function bodies, conservative completion/effect model",
            "metadata": encode(self.metadata),
            "graph": json.loads(dump_graph(self.graph)) if self.graph is not None else None,
            "semantic": self.semantic.to_dict(), "semantics": self.semantics.to_dict(),
            "control": self.control.to_dict(),
            "summary": self.summary(),
            "runtime_target_verified": False, "transformation_authorized": False,
        }
        if self.profile is not BodyLoweringProfile.LEGACY:
            document.update(profile=self.profile.value, interface=encode(self.interface),
                            frame=encode(self.frame))
        if self.profile in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
            document["structured"] = encode(self.structured)
        if self.language is not None:
            document["language"] = encode(self.language)
        return document

    @classmethod
    def from_dict(cls, document, *, max_operations=10000, language_options=None, verification="SOURCE_REPLAY",
                  source_texts: dict[str, str] | None = None, module_code_evidence=None):
        from scar.ir.program.codec import loads as load_graph
        from scar.ir.record_codec import decode
        from scar.ir.semantics_v2 import SourceSemanticsGraph
        from scar.ir.control_flow_v2 import SourceControlFlowGraph
        from scar.ir.v2.codec import semantic_from_dict

        expected_fields = {"schema", "schema_version", "status", "scope", "metadata",
                           "graph", "semantic", "semantics", "control", "summary", "runtime_target_verified",
                           "transformation_authorized"}
        if type(document) is not dict:
            raise ValueError("source program fields mismatch")
        if verification not in ("SOURCE_REPLAY", "STRUCTURE"):
            raise ValueError("source program verification mode must be explicit")
        _check_structure_source_texts(verification, source_texts)
        version = document.get("schema_version")
        if type(version) is int and version == 8:
            from scar.ir.program.module_entries import decode_frame_body
            if (set(document) != expected_fields | {'entry_kind','profile','module'}
                    or document['schema'] != 'scar.source-program' or document['entry_kind'] != 'MAPPING_FRAME'
                    or document['profile'] not in (FrameBodyProfile.STRUCTURED_MAPPING_314_V1.value,
                        FrameBodyProfile.STRUCTURED_MAPPING_PROPAGATION_314_V1.value)
                    or language_options is not None or verification != 'STRUCTURE'
                    or module_code_evidence is None or type(document['graph']) is not dict
                    or document['graph'].get('schema_version') != 29):
                raise ValueError('SP8 requires explicit source/core capability and readonly whole-root evidence')
            result=cls(load_graph(_canonical(document['graph'])),decode(LoweringMetadata,document['metadata']),
                semantic_from_dict(document['semantic']),None,SourceControlFlowGraph.from_dict(document['control']),
                FrameBodyProfile(document['profile']),module=decode_frame_body(document['module']))
            result=replace(result,semantics=SourceSemanticsGraph.from_dict(document['semantics'],result.semantic))
            if _canonical(result.to_dict()) != _canonical(document):
                raise ValueError('SP8 canonical source capability/summary differs')
            checked=validate_source_program(result,max_operations=max_operations,verification=verification,
                source_texts=source_texts,module_code_evidence=module_code_evidence)
            if not checked['valid']:raise ValueError('; '.join(checked['errors']))
            return result
        if type(version) is int and 1 <= version <= 7:
            graph_wire = document.get("graph")
            if type(graph_wire) is dict:
                core_version = graph_wire.get("schema_version")
                if ("frame_roots" in graph_wire
                        or type(core_version) is int and core_version >= 29):
                    raise ValueError("historical source1-7 reader cannot contain frame-root core capability")
                scopes = graph_wire.get("control_scopes")
                for scope in scopes if type(scopes) is list else ():
                    if type(scope) is not dict:
                        continue
                    source = scope.get("source")
                    if (scope.get("kind") == "FRAME" or type(source) is dict
                            and (source.get("source_kind") == "MODULE_UNIT" or "snapshot" in source)):
                        raise ValueError("historical source1-7 reader cannot contain frame-root core capability")
        if type(version) is int and version == 7:
            from scar.ir.program.module_entries import decode_module_prefix
            if (set(document) != expected_fields | {"entry_kind", "profile", "module"}
                    or document["schema"] != "scar.source-program" or document["entry_kind"] != "MAPPING_FRAME"
                    or document["profile"] != ModuleBodyExpansionProfile.IMPORT_PREFIX_314_V1.value
                    or language_options is not None or verification != "STRUCTURE"):
                raise ValueError("v7 prefix fields/capability/verification differ")
            result = cls(load_graph(_canonical(document["graph"])) if document["graph"] is not None else None,
                decode(LoweringMetadata, document["metadata"]), semantic_from_dict(document["semantic"]),
                None, SourceControlFlowGraph.from_dict(document["control"]), ModuleBodyExpansionProfile.IMPORT_PREFIX_314_V1,
                module=decode_module_prefix(document["module"]))
            result = replace(result, semantics=SourceSemanticsGraph.from_dict(document["semantics"], result.semantic))
            if _canonical(result.to_dict()) != _canonical(document):
                raise ValueError("v7 prefix scope/status/authority differs")
            checked = validate_source_program(result, max_operations=max_operations, verification=verification,
                source_texts=source_texts, module_code_evidence=module_code_evidence)
            if not checked["valid"]:
                raise ValueError("; ".join(checked["errors"]))
            return result
        if type(version) is int and version == 6:
            from scar.ir.program.module_entries import decode_module_overlay
            if (set(document) != expected_fields | {"entry_kind", "profile", "module"}
                    or document["schema"] != "scar.source-program" or document["entry_kind"] != "MAPPING_FRAME"
                    or document["profile"] != ModuleEntryProfile.EXEC_MAPPING_314_V1.value
                    or language_options is not None):
                raise ValueError("v6 mapping entry fields/capability differ")
            if verification != "STRUCTURE":
                raise ValueError("v6 uses explicit retained-source structure plus optional independent root evidence; function replay is unsupported")
            result = cls(load_graph(_canonical(document["graph"])) if document["graph"] is not None else None,
                decode(LoweringMetadata, document["metadata"]), semantic_from_dict(document["semantic"]),
                None, SourceControlFlowGraph.from_dict(document["control"]), ModuleEntryProfile.EXEC_MAPPING_314_V1,
                module=decode_module_overlay(document["module"]))
            result = replace(result,
                semantics=SourceSemanticsGraph.from_dict(document["semantics"], result.semantic))
            if _canonical(result.to_dict()) != _canonical(document):
                raise ValueError("v6 mapping entry scope/status/authority differs")
            checked = validate_source_program(result, max_operations=max_operations, verification=verification,
                source_texts=source_texts, module_code_evidence=module_code_evidence)
            if not checked["valid"]:
                raise ValueError("; ".join(checked["errors"]))
            return result
        if module_code_evidence is not None:
            raise ValueError("module root evidence cannot alter historical function verification")
        if type(version) is not int or version not in (1, 2, 3, 4, 5):
            raise ValueError("source program schema/version mismatch")
        if version < 5 and verification != "SOURCE_REPLAY":
            raise ValueError("historical source program replay policy is unchanged")
        if version in (2, 3, 4, 5):
            expected_fields |= {"profile", "interface", "frame"}
        if version in (3, 4, 5):
            expected_fields.add("structured")
        if version == 5:
            expected_fields.add("language")
        if set(document) != expected_fields or document["schema"] != "scar.source-program":
            raise ValueError("source program fields mismatch")
        profile = BodyLoweringProfile.LEGACY
        interface = frame = structured = None
        if version in (2, 3, 4, 5):
            profile = BodyLoweringProfile(document["profile"])
            expected_profile = (BodyLoweringProfile.STRUCTURED_ENV if version in (4, 5) else
                                BodyLoweringProfile.BOUND_FRAME if version == 2 else
                                BodyLoweringProfile.STRUCTURED_BODY)
            if profile is not expected_profile:
                raise ValueError("source-program version requires its exact lowering profile")
            interface = decode(BodyEntryInterface, document["interface"]) if document["interface"] is not None else None
            frame = FrameModel.from_dict(document["frame"]) if document["frame"] is not None else None
        if version in (3, 4, 5):
            structured = decode(StructuredBodyModel, document["structured"]) if document["structured"] is not None else None
        language = decode(SourceLanguageOverlay, document["language"]) if version == 5 else None
        if version < 5:
            reject_extended_protocols(structured)
            if language_options is not None:
                raise ValueError("historical source wrapper cannot accept extended language inputs")
        metadata = decode(LoweringMetadata, document["metadata"])
        semantic = semantic_from_dict(document["semantic"])
        semantics = SourceSemanticsGraph.from_dict(document["semantics"], semantic)
        control = SourceControlFlowGraph.from_dict(document["control"])
        graph = load_graph(_canonical(document["graph"])) if document["graph"] is not None else None
        result = cls(graph, metadata, semantic, semantics, control, profile, interface, frame, structured, language)
        if _canonical(result.to_dict()) != _canonical(document):
            raise ValueError("source program scope/status/authority or canonical fields differ")
        checked = validate_source_program(result, max_operations=max_operations, language_options=language_options,
                                          verification=verification, source_texts=source_texts)
        if not checked["valid"]:
            raise ValueError("; ".join(checked["errors"]))
        return result

    @classmethod
    def read_structure(cls, document, *, max_operations=10000, source_texts: dict[str, str] | None = None,
                       module_code_evidence=None):
        """Read v5; optional retained texts feed the existing source/CFG checks.

        This grants no CodeWitness or runtime proof. Omission preserves the
        existing source-reader policy; provided texts are fingerprint-checked
        and replayed by the ordinary semantics/control validators.
        """
        return cls.from_dict(document, max_operations=max_operations, verification="STRUCTURE",
                             source_texts=source_texts, module_code_evidence=module_code_evidence)


@dataclass(frozen=True)
class LoweredSourceBody:
    """Body and correspondence, interpreted in its shared PreparedSource."""
    graph: ProgramGraph | None
    metadata: LoweringMetadata
    operations_emitted: int
    interface: BodyEntryInterface | None = None
    frame: FrameModel | None = None
    structured: StructuredBodyModel | None = None
    language: SourceLanguageOverlay | None = None


@dataclass(frozen=True)
class PreparedSource:
    path: Path
    root: Path
    text: str
    semantic: object
    semantics: object
    control: object
    tree: ast.Module
    symbol_tables: dict

    @cached_property
    def _lowering_index(self):
        # Used only by the isolated, explicitly sealed lowering session.
        # Ordinary PreparedSource inputs remain mutable and do not reuse it.
        return _source_lowering_index(self.path, self.tree, self.semantic, self.semantics)

    def seal_for_lowering(self):
        """Snapshot current source inputs for one isolated construction session.

        The session owns private copies and returns only constructed body
        records. Later mutation of this PreparedSource does not alter that
        explicit snapshot; ordinary lower() always checks current source inputs.
        """
        return _SealedLoweringSession(self)

    def lower(self, entry, *, source: SourceReference | None = None, max_operations=10000,
              expand_candidates=True, profile=BodyLoweringProfile.LEGACY, language_options=None):
        return _lower_prepared(self, entry, source=source, max_operations=max_operations,
                               expand_candidates=expand_candidates, profile=profile, language_options=language_options)

    def lower_entry(self, selection, *, code_evidence, max_operations=10000,
                    profile=ModuleEntryProfile.EXEC_MAPPING_314_V1):
        """Explicit mapping-root capability; never changes function defaults."""
        from scar.analysis.source_module_lowering import lower_module_entry
        return lower_module_entry(self, selection, code_evidence=code_evidence, max_operations=max_operations,
                                  profile=profile)


def _lower_prepared(context, entry, *, source, max_operations, expand_candidates, profile,
                    sealed_source=None, language_options=None):
    _check_arguments(entry, max_operations)
    if language_options is not None and profile is not BodyLoweringProfile.STRUCTURED_ENV:
        raise ValueError("extended source language requires environment entry ABI")
    if profile is BodyLoweringProfile.STRUCTURED_ENV:
        if expand_candidates:
            raise ValueError("environment source bodies require root-only expansion")
        from scar.analysis.environment_lowering import StructuredEnvironmentBuilder
        builder = StructuredEnvironmentBuilder
        if language_options is not None:
            from scar.ir.program.source_language import SourceLanguageCapability
            if SourceLanguageCapability.FUNCTION_TRY_314_V1 in language_options.capabilities:
                from scar.analysis.source_function_try_lowering import FunctionTryBuilder
                builder = FunctionTryBuilder
        return builder(context, entry, source=source, max_operations=max_operations,
                                             sealed_source=sealed_source, language_options=language_options).run()
    if profile is BodyLoweringProfile.STRUCTURED_BODY:
        if expand_candidates:
            raise ValueError("structured source bodies require root-only expansion")
        from scar.analysis.structured_lowering import StructuredBuilder
        return StructuredBuilder(context, entry, source=source, max_operations=max_operations,
                                 sealed_source=sealed_source).run()
    builder = _Builder(context.path, entry, context.text, context.semantic, context.semantics,
                       context.control, max_operations, selected_source=source,
                       tree=context.tree, symbol_tables=context.symbol_tables,
                       expand_candidates=expand_candidates, profile=profile)
    return builder.run()


class _SealedLoweringSession:
    """Private source snapshot, with no public graph getters or graph output.

    Construction executes no target code or callbacks. Builders only read the
    private source layers; emitted body records contain frozen IDs/references,
    never mutable source definitions, graph registries or source AST objects.
    This is local construction validation, not public source replay authority.
    """

    __slots__ = ("__prepared", "__validated")

    def __init__(self, prepared):
        self.__validated = False
        semantic, semantics, control, tree = deepcopy((
            prepared.semantic, prepared.semantics, prepared.control, prepared.tree))
        expected_tree = ast.parse(prepared.text, filename=str(prepared.path))
        if ast.dump(tree, include_attributes=True) != ast.dump(expected_tree, include_attributes=True):
            raise ValueError("sealed source AST differs from the fixed source text")
        fingerprint = "sha256:" + hashlib.sha256(prepared.text.encode()).hexdigest()
        snapshot = semantics.sources.get(str(prepared.path))
        if snapshot is None or snapshot.fingerprint != fingerprint:
            raise ValueError("sealed source layers differ from the fixed source text")
        # Validate every source layer and both cross-layer digests once. These
        # mutable copies never escape this session, so per-body construction
        # need not repeat that same source-only work.
        semantic.assert_valid()
        semantics.assert_valid(semantic)
        control.assert_valid(semantic, semantics)
        self.__prepared = PreparedSource(prepared.path, prepared.root, prepared.text,
            semantic, semantics, control, tree, _symbol_tables(prepared.text, prepared.path))
        self.__validated = True

    def lower(self, entry, *, source=None, max_operations=10000, expand_candidates=True,
              profile=BodyLoweringProfile.LEGACY, language_options=None):
        if profile not in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
            raise ValueError("sealed construction is limited to structured source profiles")
        return _lower_prepared(self.__prepared, entry, source=source, max_operations=max_operations,
            expand_candidates=expand_candidates, profile=profile, sealed_source=self,
            language_options=language_options)

    def _require_inputs(self, semantic, control):
        if (not self.__validated or semantic is not self.__prepared.semantic
                or control is not self.__prepared.control):
            raise ValueError("source validation receipt belongs to a different sealed snapshot")


@dataclass(frozen=True)
class _SourceLoweringIndex:
    atoms: object
    by_atom: object
    old_by_atom: object
    slots: object
    functions: object
    function_candidates: object
    function_nodes: tuple


def _source_lowering_index(path, tree, semantic, semantics):
    """Build file-wide read-only lookup tables once for each prepared source."""
    atoms = {_span_atom(atom): atom.reference for atom in semantic.source_atoms.values()
             if atom.reference.path == str(path)}
    by_atom, old_by_atom, candidates = defaultdict(list), defaultdict(list), defaultdict(list)
    for definition in semantic.definitions.values():
        by_atom[definition.code_id].append(definition)
    for operation in semantics.operations.values():
        old_by_atom[operation.source.atom_id].append(operation)
    functions = {}

    def collect(statements, prefix=""):
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                candidates[name].append(node)
                functions[name] = node
            elif isinstance(node, ast.ClassDef):
                collect(node.body, prefix + node.name + ".")

    collect(tree.body)
    return _SourceLoweringIndex(
        MappingProxyType(atoms),
        MappingProxyType({key: tuple(value) for key, value in by_atom.items()}),
        MappingProxyType({key: tuple(value) for key, value in old_by_atom.items()}),
        MappingProxyType({(slot.owner, slot.name): slot.slot_id for slot in semantic.slots.values()}),
        MappingProxyType(functions),
        MappingProxyType({key: tuple(value) for key, value in candidates.items()}),
        tuple(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))),
    )


def _canonical(document):
    return json.dumps(document, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


class _Unsupported(Exception):
    def __init__(self, kind, node, detail):
        self.kind, self.node, self.detail = kind, node, detail


@dataclass
class _Cursor:
    block: BlockID
    env: dict[str, ValueID]
    state: ValueID


class _Builder:
    def __init__(self, path, entry, text, semantic, semantics, control, max_operations,
                 selected_source=None, tree=None, symbol_tables=None, expand_candidates=True,
                 profile=BodyLoweringProfile.LEGACY, source_index=None):
        if type(expand_candidates) is not bool:
            raise ValueError("expand_candidates must be an exact boolean")
        self.expand_candidates = expand_candidates
        if type(profile) is not BodyLoweringProfile:
            raise ValueError("body lowering needs an explicit profile")
        if profile is not BodyLoweringProfile.LEGACY and expand_candidates:
            raise ValueError("bound-formal bodies require root-only expansion")
        self.profile, self.interface = profile, None
        self.frame = None
        self.frame_transitions = []
        self.path, self.entry, self.text = path, entry, text
        self.semantic, self.semantics, self.control = semantic, semantics, control
        self.max_operations = max_operations
        self.snapshot = semantics.sources[str(path)]
        self.tree = tree if tree is not None else ast.parse(text, filename=str(path))
        self.symbol_tables = symbol_tables if symbol_tables is not None else _symbol_tables(text, path)
        index = source_index if source_index is not None else _source_lowering_index(
            path, self.tree, semantic, semantics)
        self.atoms, self.by_atom, self.old_by_atom = index.atoms, index.by_atom, index.old_by_atom
        self.slots = index.slots
        # Selecting a nested definition adds an entry alias only to this body.
        self.functions = dict(index.functions)
        self.function_candidates = index.function_candidates
        if selected_source is not None:
            if selected_source.path != str(path) or selected_source.fingerprint != self.snapshot.fingerprint:
                raise ValueError("selected definition source differs from prepared snapshot")
            selected = [node for node in index.function_nodes if self.source(node) == selected_source]
            if len(selected) != 1:
                raise ValueError("selected source must identify exactly one function definition")
            self.functions[entry] = selected[0]
        elif len(self.function_candidates.get(entry, ())) > 1:
            raise ValueError("ambiguous function entry; source-position identity is required")
        self.regions, self.operations, self.values = [], [], []
        self.operations_emitted = 0
        self.values_by_id = {}
        self.value_positions = {}
        self.operation_links, self.value_links, self.use_links = [], [], []
        self.value_link_set = set()
        self.targets, self.gaps = [], []
        self.world = LocationID(_key("python-world", str(path), self.snapshot.fingerprint))
        self.state_type = ValueType(ValueKind.STATE, location=self.world)
        self.serial = 0
        self.function_context = None
        self.block_operations = {}
        self.block_arguments = {}
        self.function_blocks = []
        self.pending_targets = []

    def source(self, node):
        try:
            return self.atoms[_span(node)]
        except KeyError:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "source atom is not uniquely represented")

    def old_operation(self, node):
        records = self.old_by_atom.get(self.source(node).atom_id, ())
        if len(records) != 1:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "expression needs one source computational record")
        return records[0]

    def definition(self, node):
        choices = [d for d in self.by_atom.get(self.source(node).atom_id.wire, ())
                   if d.metadata.get("phase") == "call_time"]
        if len(choices) != 1:
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "function body needs one versioned source definition")
        return choices[0]

    def fresh(self, cls, tag):
        self.serial += 1
        return cls(_key(self.snapshot.fingerprint, str(self.function_context), tag, self.serial))

    def gap(self, kind, node, detail):
        gap = LoweringGap(kind, self.source(node), detail)
        if gap not in self.gaps:
            self.gaps.append(gap)

    def link_value(self, value, node, role, *, slot=None, semantic_value=None):
        link = ValueSource(value.id, self.source(node), role, slot, semantic_value)
        if link not in self.value_link_set:
            self.value_links.append(link)
            self.value_link_set.add(link)

    def add_value(self, value):
        self.value_positions[value.id] = len(self.values)
        self.values.append(value)
        self.values_by_id[value.id] = value

    def replace_value(self, value):
        self.values[self.value_positions[value.id]] = value
        self.values_by_id[value.id] = value

    def pop_value(self):
        """Remove the trailing value and its trailing correspondence together."""
        value = self.values.pop()
        link = self.value_links.pop()
        if link.value != value.id:
            raise ValueError("trailing value/source correspondence differs")
        self.value_link_set.remove(link)
        del self.value_positions[value.id]
        del self.values_by_id[value.id]
        return value

    def clear_value_links(self):
        self.value_links.clear()
        self.value_link_set.clear()

    def new_block(self, node, *, named=(), role=SourceRole.CONTROL, extra_types=()):
        block = self.fresh(BlockID, "block")
        self.function_blocks.append(block)
        self.block_operations[block] = []
        args, env = [], {}
        for name in named:
            value = ReferenceValue(self.fresh(ValueID, "argument"), self.function_context,
                                   BlockArgument(block, len(args)))
            self.add_value(value); args.append(value.id); env[name] = value.id
            self.link_value(value, node, role)
        for kind in extra_types:
            from scar.ir.program.control import ProtocolValueType
            from scar.ir.program.model import ProtocolValue
            if type(kind) is ProtocolValueType:
                value = ProtocolValue(self.fresh(ValueID, 'completion-protocol'), self.function_context,
                                      BlockArgument(block, len(args)), kind.protocol)
            elif kind.kind is ValueKind.REFERENCE:
                value = ReferenceValue(self.fresh(ValueID, "completion-reference"), self.function_context,
                                       BlockArgument(block, len(args)))
            elif kind.kind is ValueKind.DATA:
                value = DataValue(self.fresh(ValueID, "completion-data"), self.function_context,
                                  BlockArgument(block, len(args)), kind.data_type)
            else:
                raise ValueError("completion state is added by the block interface")
            self.add_value(value); args.append(value.id)
            self.link_value(value, node, role)
        state = StateVersionValue(self.fresh(ValueID, "world-state"), self.function_context,
                                  BlockArgument(block, len(args)), self.world)
        self.add_value(state); args.append(state.id)
        self.link_value(state, node, SourceRole.STATE)
        self.block_arguments[block] = tuple(args)
        return _Cursor(block, env, state.id)

    def use(self, operation, value, node, role, index, *, semantic_value=None):
        record = self.values_by_id[value]
        kind = (UseRole.REFERENCE if isinstance(record, ReferenceValue) else
                UseRole.STATE_CONTENT if isinstance(record, StateVersionValue) else UseRole.DATA)
        use = Use(self.fresh(UseID, "use"), value, kind)
        self.use_links.append(UseSource(operation, use.id, self.source(node), role, index, semantic_value))
        return use

    def emit(self, cursor, operation, node, role, old=None):
        if self.operations_emitted >= self.max_operations:
            raise _Unsupported(GapKind.BUDGET, node, "program operation budget exceeded")
        self.operations_emitted += 1
        self.operations.append(operation)
        self.block_operations[cursor.block].append(operation.id)
        self.operation_links.append(OperationSource(operation.id, self.source(node), role,
                                                     old.operation if old else None,
                                                     old.opcode if old else None))

    def invoke(self, cursor, node, inputs, *, role=SourceRole.EXPRESSION, old=None,
               result_type=_REF):
        """Attempt one source operation, keeping its state and exception paths."""
        operation_id = self.fresh(OperationID, "invoke")
        uses = [self.use(operation_id, value, child, operand_role, index, semantic_value=static)
                for value, child, operand_role, index, static in inputs]
        uses.append(self.use(operation_id, cursor.state, node, "state", 0))
        normal = self.new_block(node, role=role, extra_types=(result_type,) if result_type else ())
        failure = self.new_block(node, role=SourceRole.EXCEPTION, extra_types=(_REF,))
        signatures = (
            CompletionSignature(ExitKind.NORMAL, ((result_type,) if result_type else ()) + (self.state_type,)),
            CompletionSignature(ExitKind.RAISE, (_REF, self.state_type)),
        )
        edges = tuple(CompletionSuccessor(signature.kind, target.block,
                      tuple(CompletionResult(i) for i in range(len(signature.types))))
                      for signature, target in zip(signatures, (normal, failure)))
        operation = Operation(operation_id, role.value, (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
                              tuple(uses), effects_complete=False,
                              terminator=Terminator(TerminatorKind.INVOKE, edges),
                              completions=signatures, invoke_arguments=tuple(u.id for u in uses))
        self.emit(cursor, operation, node, role, old)
        exception = self.block_arguments[failure.block][0]
        self.finish_exit(failure, node, exception, ExitKind.RAISE)
        normal.env = dict(cursor.env)
        value = self.block_arguments[normal.block][0] if result_type else None
        if value is not None and old is not None and old.result is not None:
            actual = self.values_by_id[value]
            self.link_value(actual, node, role, semantic_value=old.result)
        return normal, value, operation_id

    def finish_exit(self, cursor, node, value, kind):
        frame_operation = frame_uses = None
        if self.profile is BodyLoweringProfile.BOUND_FRAME:
            frame_operation, frame_uses = self.frame_step(
                cursor, node, ((value, node, "held-payload", 0, None),),
                role=SourceRole.RETURN if kind is ExitKind.NORMAL else SourceRole.EXCEPTION)
        operation_id = self.fresh(OperationID, "exit")
        uses = (self.use(operation_id, value, node, "result", 0),
                self.use(operation_id, cursor.state, node, "state", 0))
        term_kind = TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE
        operation = Operation(operation_id, kind.value, (Behavior.CONTROL,), uses,
                              terminator=Terminator(term_kind, exit=kind.value.lower(),
                                                    values=tuple(u.id for u in uses)))
        self.emit(cursor, operation, node, SourceRole.RETURN if kind is ExitKind.NORMAL else SourceRole.EXCEPTION)
        if frame_operation is not None:
            self.frame_transitions.append(FrameExit(frame_operation, self.source(node),
                                                    operation_id, frame_uses[0].id))

    def frame_step(self, cursor, node, references, *, role):
        """Conditional nonthrowing frame transition; unknown effects may diverge.

        This does not add a second binding or a runtime reference count action.
        It makes the frame's existing hold changes depend on the coarse world.
        FrameRules retains the unproved interposition and lifetime conditions.
        """
        operation_id = self.fresh(OperationID, "frame-transition")
        references = tuple(self.use(operation_id, value, child, use_role, index,
                                    semantic_value=static)
                           for value, child, use_role, index, static in references)
        before = self.use(operation_id, cursor.state, node, "state", 0)
        after = StateVersionValue(self.fresh(ValueID, "frame-world"), self.function_context,
                                  OperationResult(operation_id, 0), self.world)
        self.add_value(after)
        self.link_value(after, node, SourceRole.STATE)
        operation = Operation(
            operation_id, "frame-lifetime", (Behavior.READ, Behavior.WRITE, Behavior.MEMORY),
            references + (before,), results=(after.id,),
            accesses=(StateAccess(self.world, before.id, AccessMode.READ_WRITE, after.id),),
            effects_complete=False)
        self.emit(cursor, operation, node, role)
        cursor.state = after.id
        return operation_id, references

    def literal(self, node, value):
        try:
            origin = LiteralOrigin(value)
        except (TypeError, ValueError):
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "literal is outside exact scalar support")
        record = ReferenceValue(self.fresh(ValueID, "literal"), self.function_context, origin, targets=())
        self.add_value(record)
        old = self.old_operation(node) if isinstance(node, ast.Constant) else None
        self.link_value(record, node, SourceRole.EXPRESSION, semantic_value=old.result if old else None)
        return record.id

    def expr(self, node, cursor):
        old = self.old_operation(node)
        if isinstance(node, ast.Constant):
            return cursor, self.literal(node, node.value)
        if isinstance(node, ast.Name):
            if node.id in cursor.env:
                value_id = cursor.env[node.id]
                value = self.values_by_id[value_id]
                self.link_value(value, node, SourceRole.EXPRESSION, semantic_value=old.result)
                return cursor, value_id
            if node.id in self.locals:
                raise _Unsupported(GapKind.UNBOUND_LOCAL, node, "local has no definition on every incoming path: " + node.id)
            self.gap(GapKind.EFFECT_SUMMARY, node, "global/builtin name lookup remains an effectful source operation")
            cursor, value, _ = self.invoke(cursor, node, (), old=old)
            if node.id in self.functions and len(self.function_candidates.get(node.id, ())) == 1:
                self.reference_candidates[value] = node.id
            return cursor, value

        children = []
        if isinstance(node, ast.BinOp):
            children = [node.left, node.right]
        elif isinstance(node, ast.UnaryOp):
            children = [node.operand]
        elif isinstance(node, ast.Compare) and len(node.ops) == 1:
            children = [node.left, node.comparators[0]]
        elif isinstance(node, ast.Attribute):
            children = [node.value]
        elif isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            children = [node.value, node.slice]
        elif isinstance(node, (ast.Tuple, ast.List)):
            children = list(node.elts)
        elif isinstance(node, ast.Call) and not any(isinstance(arg, ast.Starred) for arg in node.args) and all(k.arg is not None for k in node.keywords):
            children = [node.func, *node.args, *(keyword.value for keyword in node.keywords)]
        else:
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "expression is not yet connected: " + type(node).__name__)
        if len(children) != len(old.operands):
            raise _Unsupported(GapKind.SOURCE_MAPPING, node, "source operand list differs from ordered semantics")
        inputs = []
        for child, operand in zip(children, old.operands):
            cursor, value = self.expr(child, cursor)
            inputs.append((value, child, operand.role, operand.index, operand.value))
        self.gap(GapKind.DYNAMIC_DISPATCH, node,
                 "source opcode is known; runtime dispatch, effects and exact exceptional behavior remain unverified")
        cursor, value, operation_id = self.invoke(cursor, node, inputs, old=old)
        if isinstance(node, ast.Call):
            callee = inputs[0][0]
            candidate_name = self.reference_candidates.get(callee)
            self.pending_targets.append((operation_id, callee, candidate_name, node))
            self.gap(GapKind.DYNAMIC_TARGET, node,
                     "source binding candidates are not live runtime target verification")
        return cursor, value

    def store(self, target, value, cursor):
        if not isinstance(target, ast.Name):
            raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, target, "only ordinary local name assignment is connected")
        if self.profile is BodyLoweringProfile.BOUND_FRAME:
            slot = self.slots.get((self.function_definition.id, target.id))
            if slot is None:
                raise _Unsupported(GapKind.SOURCE_MAPPING, target, "missing ordinary local source slot")
            operation, uses = self.frame_step(cursor, target,
                ((value, target, "assigned", 0, None),), role=SourceRole.LOCAL_BINDING)
            self.frame_transitions.append(FrameBind(operation, self.source(target), slot, uses[0].id))
        elif target.id in cursor.env:
            cursor, _, _ = self.invoke(cursor, target,
                ((cursor.env[target.id], target, "previous", 0, None),
                 (value, target, "assigned", 0, None)), role=SourceRole.LOCAL_BINDING, result_type=None)
            self.gap(GapKind.FRAME_EFFECT, target, "rebinding may release an existing reference; completion is conservatively modeled")
        cursor.env[target.id] = value
        current = self.values_by_id[value]
        old = self.old_operation(target)
        self.link_value(current, target, SourceRole.LOCAL_BINDING,
                        slot=self.slots.get((self.function_definition.id, target.id)), semantic_value=old.result)
        return cursor

    def jump(self, cursor, target, names, node):
        operation_id = self.fresh(OperationID, "jump")
        uses = [self.use(operation_id, cursor.env[name], node, "merge", index) for index, name in enumerate(names)]
        uses.append(self.use(operation_id, cursor.state, node, "state", 0))
        operation = Operation(operation_id, "join", (Behavior.CONTROL,), tuple(uses),
                              terminator=Terminator(TerminatorKind.JUMP,
                                  (Successor(target.block, tuple(use.id for use in uses)),)))
        self.emit(cursor, operation, node, SourceRole.CONTROL)

    def statements(self, statements, cursor):
        for node in statements:
            if cursor is None:
                if self.profile is BodyLoweringProfile.BOUND_FRAME:
                    self.check_frame_statements((node,))
                # Preserve source diagnostics rather than claiming dead code.
                self.gap(GapKind.SOURCE_COVERAGE, node, "statement follows a closed return path; not lowered as executed work")
                continue
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                cursor, value = self.expr(node.value, cursor)
                cursor = self.store(node.targets[0], value, cursor)
            elif isinstance(node, ast.Expr):
                cursor, value = self.expr(node.value, cursor)
                if self.profile is BodyLoweringProfile.BOUND_FRAME:
                    operation, uses = self.frame_step(cursor, node,
                        ((value, node.value, "discarded-temporary", 0, None),), role=SourceRole.EXPRESSION)
                    self.frame_transitions.append(FrameDiscard(operation, self.source(node), uses[0].id))
            elif isinstance(node, ast.Pass):
                continue
            elif isinstance(node, ast.Return):
                if node.value is None:
                    value = self.literal(node, None)
                else:
                    cursor, value = self.expr(node.value, cursor)
                self.gap(GapKind.FRAME_EFFECT, node, "frame/reference-release effects remain conservative at return")
                if self.profile is BodyLoweringProfile.BOUND_FRAME:
                    returned = value
                else:
                    cursor, returned, _ = self.invoke(cursor, node,
                        ((value, node.value or node, "return", 0, None),), role=SourceRole.RETURN)
                self.finish_exit(cursor, node, returned, ExitKind.NORMAL)
                cursor = None
            elif isinstance(node, ast.If):
                cursor, condition = self.expr(node.test, cursor)
                self.gap(GapKind.DYNAMIC_DISPATCH, node.test,
                         "Python truth conversion may execute code or raise; no parameter type is assumed")
                cursor, boolean, _ = self.invoke(cursor, node.test,
                    ((condition, node.test, "predicate", 0, None),), role=SourceRole.TRUTH, result_type=_BOOL)
                yes = self.new_block(node, role=SourceRole.CONTROL)
                no = self.new_block(node, role=SourceRole.CONTROL)
                operation_id = self.fresh(OperationID, "branch")
                uses = (self.use(operation_id, boolean, node.test, "condition", 0),
                        self.use(operation_id, cursor.state, node, "true_state", 0),
                        self.use(operation_id, cursor.state, node, "false_state", 0))
                branch = Operation(operation_id, "if", (Behavior.CONTROL,), uses,
                    terminator=Terminator(TerminatorKind.BRANCH,
                        (Successor(yes.block, (uses[1].id,)), Successor(no.block, (uses[2].id,))), condition=uses[0].id))
                self.emit(cursor, branch, node, SourceRole.CONTROL)
                yes.env, no.env = dict(cursor.env), dict(cursor.env)
                yes = self.statements(node.body, yes)
                no = self.statements(node.orelse, no)
                if yes is None or no is None:
                    cursor = yes or no
                else:
                    common = sorted(set(yes.env) & set(no.env))
                    merged = [name for name in common if yes.env[name] != no.env[name]]
                    join = self.new_block(node, named=merged, role=SourceRole.MERGE)
                    join.env.update({name: yes.env[name] for name in common if name not in merged})
                    self.jump(yes, join, merged, node)
                    self.jump(no, join, merged, node)
                    cursor = join
            else:
                raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "statement is not yet connected: " + type(node).__name__)
        return cursor

    def check_frame_statements(self, statements):
        """Reject unsupported frame/control syntax, including closed paths.

        This profile is a whole-body source rule. Keeping an unreachable
        lifetime construct as a coverage gap must not imply that it was modeled.
        Historical profiles preserve their original coverage behavior.
        """
        for node in statements:
            if isinstance(node, ast.If):
                self.check_frame_statements(node.body)
                self.check_frame_statements(node.orelse)
            elif isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                                       "frame profile requires single ordinary local Name assignment")
            elif not isinstance(node, (ast.Return, ast.Expr, ast.Pass)):
                raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node,
                                   "whole frame profile does not model " + type(node).__name__)

    def function(self, name, root):
        node = self.functions[name]
        definition = self.definition(node)
        self.function_context = self.region_id(definition)
        self.serial = 0
        self.function_definition = definition
        self.reference_candidates = {}
        self.function_blocks = []
        if (self.profile is BodyLoweringProfile.LEGACY and
                (isinstance(node, ast.AsyncFunctionDef) or node.decorator_list or node.args.defaults
                 or node.args.kw_defaults or node.args.kwonlyargs or node.args.vararg or node.args.kwarg)):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node,
                               "defaults, decorators, async and variadic/keyword-only interfaces need explicit binding rules")
        if isinstance(node, ast.AsyncFunctionDef):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node,
                               "async invocation/suspension requires a distinct completion and lifetime model")
        def body_nodes(statements):
            for child in statements:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                yield child
                yield from body_nodes(ast.iter_child_nodes(child))
        if any(isinstance(child, (ast.Yield, ast.YieldFrom)) for child in body_nodes(node.body)):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node,
                               "generator invocation/suspension requires a distinct completion and lifetime model")
        if self.profile is not BodyLoweringProfile.LEGACY:
            from scar.analysis.function_interfaces import formal_nodes
            parameters = [argument for argument, _ in formal_nodes(node)]
        else:
            parameters = node.args.posonlyargs + node.args.args
        # Python determines scope before execution, including unreachable imports,
        # deletion and exception-handler targets. Reuse compiler symbol analysis.
        table = self.symbol_tables[(node.name, node.lineno)]
        self.locals = {symbol.get_name() for symbol in table.get_symbols() if symbol.is_local()}
        if any(symbol.is_free() or symbol.is_nonlocal() for symbol in table.get_symbols()):
            raise _Unsupported(GapKind.UNSUPPORTED_SIGNATURE, node,
                               "closure/cell bindings need explicit state-location interfaces")
        cursor = self.new_block(node)
        # Function entry has parameters followed by the explicit world state.
        state = self.pop_value()
        args, ports = [], []
        cursor.env = {}
        for index, parameter in enumerate(parameters):
            value = ReferenceValue(self.fresh(ValueID, "parameter"), self.function_context,
                                   BlockArgument(cursor.block, index))
            self.add_value(value); args.append(value.id); cursor.env[parameter.arg] = value.id
            slot = self.slots.get((definition.id, parameter.arg))
            if slot is None:
                raise _Unsupported(GapKind.SOURCE_MAPPING, parameter, "missing formal source slot")
            self.link_value(value, parameter, SourceRole.PARAMETER, slot=slot)
            ports.append(FormalPort(slot, value.id))
        state = StateVersionValue(state.id, state.region, BlockArgument(cursor.block, len(args)), state.location)
        self.add_value(state); args.append(state.id); cursor.state = state.id
        self.link_value(state, node, SourceRole.STATE)
        self.block_arguments[cursor.block] = tuple(args)
        entry = cursor.block
        if self.profile is not BodyLoweringProfile.LEGACY:
            self.interface = BodyEntryInterface(definition.id, self.function_context, tuple(ports), state.id,
                                                self.profile)
        if self.profile is BodyLoweringProfile.BOUND_FRAME:
            operation, uses = self.frame_step(cursor, node,
                tuple((port.value, parameter, "bound-formal", index, None)
                      for index, (port, parameter) in enumerate(zip(ports, parameters))), role=SourceRole.PARAMETER)
            self.frame_transitions.append(FrameEnter(operation, self.source(node),
                tuple(FrameFormal(port.slot, use.id) for port, use in zip(ports, uses))))
            self.gap(GapKind.FRAME_EFFECT, node,
                     "frame lifetime condition is unproved; finalizer/external effects, retention and noncompletion remain unknown")
        self.gap(GapKind.CODE_VERSION, node, "source body version is bound; live function object/code and definition-time effects remain unobserved")
        statements = node.body
        if (self.profile is BodyLoweringProfile.BOUND_FRAME and statements
                and isinstance(statements[0], ast.Expr) and isinstance(statements[0].value, ast.Constant)
                and type(statements[0].value.value) is str):
            # A leading function docstring initializes declaration metadata;
            # it is not evaluated/discarded on each call of this Python body.
            statements = statements[1:]
        cursor = self.statements(statements, cursor)
        if cursor is not None:
            implicit = self.literal(node, None)
            if self.profile is BodyLoweringProfile.BOUND_FRAME:
                value = implicit
            else:
                cursor, value, _ = self.invoke(cursor, node,
                    ((implicit, node, "return", 0, None),), role=SourceRole.RETURN)
            self.finish_exit(cursor, node, value, ExitKind.NORMAL)
        blocks = tuple(Block(block, self.block_arguments[block], tuple(self.block_operations[block]))
                       for block in self.function_blocks)
        exits = (ExitPort("normal", ExitKind.NORMAL, (_REF, self.state_type)),
                 ExitPort("raise", ExitKind.RAISE, (_REF, self.state_type)))
        if self.profile is BodyLoweringProfile.BOUND_FRAME:
            # A local/reference-only body need not have an exceptional edge.
            # Incomplete effects and possible noncompletion are still explicit
            # frame obligations, never a fabricated replacement exception.
            body_operations = {item for block in blocks for item in block.operations}
            completed = {operation.terminator.kind for operation in self.operations
                         if operation.id in body_operations
                         and operation.terminator is not None}
            exits = tuple(port for port in exits
                          if (TerminatorKind.RETURN if port.kind is ExitKind.NORMAL else TerminatorKind.RAISE)
                          in completed)
        region = Region(self.function_context, name, entry, blocks, exits, parent=root)
        self.regions.append(region)
        if self.profile is BodyLoweringProfile.BOUND_FRAME:
            self.frame = FrameModel(definition.id, region.id, self.source(node), tuple(self.frame_transitions))
        return region.id

    def region_id(self, definition):
        if self.profile is BodyLoweringProfile.BOUND_FRAME:
            return RegionID(_key("function-body", definition.id.wire, self.profile.value))
        return RegionID(_key("function-body", definition.id.wire))

    def run(self):
        if self.entry not in self.functions:
            raise ValueError("entry must name a selected function body")
        root_node = self.functions[self.entry]
        root_id = self.region_id(self.definition(root_node))
        try:
            self.function(self.entry, None)
            # Expand only referenced source candidates, not unrelated modules.
            expanded = {self.entry}
            index = 0
            failed_candidates = set()
            while self.expand_candidates and index < len(self.pending_targets):
                _, _, name, _ = self.pending_targets[index]
                index += 1
                if name is None or name in expanded or name in failed_candidates:
                    continue
                checkpoint = self.checkpoint()
                try:
                    self.function(name, root_id)
                except _Unsupported as error:
                    self.restore(checkpoint)
                    failed_candidates.add(name)
                    self.gap(error.kind, error.node, "candidate body: " + error.detail)
                else:
                    expanded.add(name)
            available = {region.id for region in self.regions}
            operations = {operation.id: operation for operation in self.operations}
            regions = {region.id: region for region in self.regions}
            for operation, callee, name, node in self.pending_targets:
                definition = self.definition(self.functions[name]) if name in self.functions else None
                candidate = self.region_id(definition) if definition else None
                candidate = candidate if candidate in available else None
                arguments, results = (), ()
                if candidate is not None:
                    arguments, results = self.candidate_bindings(operations[operation], regions[candidate],
                                                                  self.functions[name], node)
                binding_use = self.old_operation(node.func).binding_use
                self.targets.append(CallTarget(operation, callee, candidate if candidate in available else None,
                                               definition.id if definition else None,
                                               EvidenceKind.INFERRED, _ASSUMPTIONS,
                                               arguments, results, binding_use))
            graph = ProgramGraph(root_id, tuple(self.regions), tuple(self.operations), tuple(self.values),
                                 (StateLocation(self.world, "coarse Python/external world", stability=Stability.UNKNOWN),))
            require_valid(graph)
            if self.frame is not None:
                from scar.ir.program.frame_validation import require_valid_frame_model
                require_valid_frame_model(self.frame, graph, interface=self.interface, semantic=self.semantic)
        except _Unsupported as error:
            self.gap(error.kind, error.node, error.detail)
            graph = None
            # A rejected body has diagnostics, not dangling links into a graph
            # that was never emitted. Preserve the source layers and all gaps.
            self.operation_links.clear()
            self.clear_value_links()
            self.use_links.clear()
            self.targets.clear()
            self.interface = None
            self.frame = None
        metadata = LoweringMetadata(self.entry, self.snapshot, tuple(self.operation_links),
                                   tuple(self.value_links), tuple(self.targets), tuple(self.gaps),
                                   _ASSUMPTIONS, tuple(self.use_links))
        return LoweredSourceBody(graph, metadata, self.operations_emitted, self.interface, self.frame)

    def candidate_bindings(self, operation, region, function, node):
        """Conditional interface correspondence, never confirmation of a target."""
        if self.profile is not BodyLoweringProfile.LEGACY:
            return (), ()
        parameters = function.args.posonlyargs + function.args.args
        entry = next(block for block in region.blocks if block.id == region.entry)
        if (len(node.args) > len(parameters) or len(node.args) + len(node.keywords) != len(parameters)):
            return (), ()
        parameter_index = {parameter.arg: index for index, parameter in enumerate(parameters)}
        actuals = {index: operation.invoke_arguments[index + 1] for index in range(len(node.args))}
        for index, keyword in enumerate(node.keywords):
            formal = parameter_index.get(keyword.arg)
            if formal is None or formal < len(function.args.posonlyargs) or formal in actuals:
                return (), ()
            actuals[formal] = operation.invoke_arguments[1 + len(node.args) + index]
        if set(actuals) != set(range(len(parameters))):
            return (), ()
        arguments = tuple(CandidateArgument(actuals[index], entry.arguments[index])
                          for index in range(len(parameters)))
        arguments += (CandidateArgument(operation.invoke_arguments[-1], entry.arguments[-1]),)
        exit_types = {port.kind: port.types for port in region.exits}
        results = []
        for edge in operation.terminator.successors:
            signature = next(signature for signature in operation.completions if signature.kind is edge.kind)
            if exit_types.get(edge.kind) != signature.types:
                return (), ()
            for actual, formal in zip(edge.arguments, self.block_arguments[edge.block]):
                if isinstance(actual, CompletionResult):
                    results.append(CandidateResult(edge.kind, actual.index, formal))
        return arguments, tuple(results)

    def checkpoint(self):
        return tuple(len(items) for items in (self.regions, self.operations, self.values,
            self.operation_links, self.value_links, self.use_links, self.pending_targets, self.gaps))

    def restore(self, checkpoint):
        for items, length in zip((self.regions, self.operations, self.values,
                self.operation_links, self.value_links, self.use_links, self.pending_targets, self.gaps), checkpoint):
            del items[length:]
        self.values_by_id = {value.id: value for value in self.values}
        self.value_positions = {value.id: index for index, value in enumerate(self.values)}
        self.value_link_set = set(self.value_links)


def _span_atom(atom):
    r = atom.reference
    return atom.kind, r.start_line, r.end_line, r.start_column, r.end_column


def _check_arguments(entry, max_operations):
    if type(entry) is not str or not entry:
        raise ValueError("entry must be a nonempty function-body name")
    if type(max_operations) is not int or max_operations < 1 or max_operations > 100000:
        raise ValueError("max_operations must be an integer in [1, 100000]")


def prepare_source(path: str | Path, *, project_root=None) -> PreparedSource:
    """Prepare immutable source text and shared source layers once per file.

    Body graphs use the selected root's source namespace. Inventory persistence
    retains this context once; standalone lower_source keeps its historical
    per-file namespace and report format.
    """
    path = Path(path).resolve()
    root = Path(project_root).resolve() if project_root is not None else path.parent
    if path.stat().st_size > 4_000_000:
        raise ValueError("source exceeds the existing 4 MB control-model input budget")
    with tokenize.open(path) as stream:
        text = stream.read()
    sources = {str(path): text}
    semantic, semantics, control = _build_generated_source_layers((path,), root, sources=sources)
    tree = ast.parse(text, filename=str(path))
    return PreparedSource(path, root, text, semantic, semantics, control, tree, _symbol_tables(text, path))


def _symbol_tables(text, path):
    tables = {}
    def collect(table):
        tables[(table.get_name(), table.get_lineno())] = table
        for child in table.get_children():
            collect(child)
    collect(symtable.symtable(text, str(path), "exec"))
    return tables


def lower_source(path: str | Path, entry: str, *, max_operations: int = 10000,
                 profile: BodyLoweringProfile = BodyLoweringProfile.LEGACY, language_options=None,
                 project_root=None) -> SourceProgram:
    _check_arguments(entry, max_operations)
    if type(profile) is not BodyLoweringProfile or profile not in (BodyLoweringProfile.LEGACY,
            BodyLoweringProfile.BOUND_FRAME, BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
        raise ValueError("unsupported standalone source profile")
    context = prepare_source(path, project_root=project_root)
    body = context.lower(entry, max_operations=max_operations,
                         expand_candidates=profile is BodyLoweringProfile.LEGACY, profile=profile,
                         language_options=language_options)
    return SourceProgram(body.graph, body.metadata, context.semantic, context.semantics, context.control,
                         profile, body.interface, body.frame, body.structured, body.language)


def _check_structure_source_texts(verification, source_texts):
    if source_texts is not None:
        if verification != "STRUCTURE":
            raise ValueError("explicit retained source_texts are only supported for STRUCTURE verification")
        if type(source_texts) is not dict or any(type(path) is not str or type(text) is not str
                                                for path, text in source_texts.items()):
            raise TypeError("source_texts must be an explicit dict[path, str]")


def validate_source_program(result: SourceProgram, *, max_operations: int = 10000, language_options=None,
                            verification="SOURCE_REPLAY", source_texts: dict[str, str] | None = None,
                            module_code_evidence=None):
    """Rebuild from current source; reported provenance cannot raise this budget."""
    try:
        if type(result) is not SourceProgram:
            raise ValueError("expected SourceProgram")
        if verification not in ("SOURCE_REPLAY", "STRUCTURE"):
            raise ValueError("source verification mode differs")
        _check_structure_source_texts(verification, source_texts)
        if result.module is not None:
            if verification != "STRUCTURE" or language_options is not None:
                raise ValueError("v6 mapping verification requires explicit retained STRUCTURE inputs")
            from scar.analysis.source_module_validation import module_validation_report
            return module_validation_report(result, source_texts=source_texts,
                code_evidence=module_code_evidence, max_operations=max_operations)
        if module_code_evidence is not None:
            raise ValueError("module evidence cannot alter function validation")
        structural_only = verification == "STRUCTURE"
        if structural_only and result.language is None:
            raise ValueError("historical source replay policy is unchanged")
        if result.language is not None:
            if (type(result.language) is not SourceLanguageOverlay
                    or result.profile is not BodyLoweringProfile.STRUCTURED_ENV):
                raise ValueError("extended source-language overlay requires the environment entry ABI")
            if result.language.source != result.metadata.source:
                raise ValueError("source-language overlay snapshot differs from metadata")
        if type(result.profile) is not BodyLoweringProfile or result.profile not in (BodyLoweringProfile.LEGACY,
                BodyLoweringProfile.BOUND_FRAME, BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
            raise ValueError("unsupported standalone source lowering profile")
        if result.profile is BodyLoweringProfile.LEGACY:
            if result.interface is not None or result.frame is not None or result.structured is not None:
                raise ValueError("historical source-program v1 has no bound-frame overlay")
        elif result.graph is None:
            if result.interface is not None or result.frame is not None or result.structured is not None:
                raise ValueError("unsupported source body has no frame/interface links")
        elif result.profile in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
            from scar.analysis.structured_lowering import require_valid_structured_body
            if result.frame is not None or result.interface is None:
                raise ValueError("structured bodies require a structured interface, not a legacy frame overlay")
            source_tree = None
            from scar.ir.program.source_language import SourceLanguageCapability
            try_source = result.language is not None and SourceLanguageCapability.FUNCTION_TRY_314_V1 in result.language.capabilities
            call_source = result.language is not None and SourceLanguageCapability.CALL_EXPANSION_314_V1 in result.language.capabilities
            function_source = result.language is not None and SourceLanguageCapability.NESTED_FUNCTION_314_V1 in result.language.capabilities
            if result.language is not None and (not structural_only or try_source or call_source or function_source):
                if not structural_only and language_options is None:
                    raise ValueError("v5 source replay requires explicit independently supplied language inputs")
                if structural_only:
                    if source_texts is None or result.metadata.source.path not in source_texts:
                        raise ValueError("function Try STRUCTURE requires its exact retained source text" if try_source
                                         else "function definition STRUCTURE requires its exact retained source text" if function_source
                                         else "expanded call STRUCTURE requires its exact retained source text")
                    source_text = source_texts[result.metadata.source.path]
                else:
                    with tokenize.open(result.metadata.source.path) as stream:
                        source_text = stream.read()
                if "sha256:" + hashlib.sha256(source_text.encode()).hexdigest() != result.metadata.source.fingerprint:
                    raise ValueError("v5 source text changed")
                source_tree = ast.parse(source_text, filename=result.metadata.source.path)
            require_valid_structured_body(result.structured, result.graph, result.interface, result.metadata,
                semantic=result.semantic, control=result.control, language=result.language,
                source_tree=source_tree, language_options=language_options, structural_only=structural_only)
        else:
            if result.structured is not None:
                raise ValueError("historical frame bodies cannot contain structured protocols")
            from scar.ir.program.frame_validation import require_valid_frame_model
            if result.interface is None or result.interface.profile is not result.profile:
                raise ValueError("frame source program needs its matching body interface")
            require_valid_frame_model(result.frame, result.graph, interface=result.interface,
                                      semantic=result.semantic)
        errors = record_errors(result.metadata, LoweringMetadata, "metadata")
        if errors:
            return {"valid": False, "errors": errors}
        result.semantic.assert_valid()
        source_check = validate_source_semantics(result.semantics, result.semantic, sources=source_texts)
        if not source_check["valid"]:
            return source_check
        control_check = validate_source_control_flow(result.control, result.semantic, result.semantics,
                                                      sources=source_texts)
        if not control_check["valid"]:
            return control_check
        if result.graph is not None:
            require_valid(result.graph)
            ops = {op.id: op for op in result.graph.operations}
            values = {value.id for value in result.graph.values}
            if {link.operation for link in result.metadata.operation_links} != set(ops):
                raise ValueError("source operation correspondence is incomplete")
            if {link.value for link in result.metadata.value_links} != values:
                raise ValueError("source value correspondence is incomplete")
            if {(link.operation, link.use) for link in result.metadata.use_links} != {
                    (op.id, use.id) for op in ops.values() for use in op.uses}:
                raise ValueError("source use correspondence is incomplete")
        if not structural_only:
            rebuilt = lower_source(result.metadata.source.path, result.metadata.entry,
                max_operations=max_operations, profile=result.profile, language_options=language_options,
                project_root=result.language.namespace_root if result.language is not None else None)
            if _canonical(result.to_dict()) != _canonical(rebuilt.to_dict()):
                raise ValueError("program graph or typed source correspondence differs from source replay")
    except (ValueError, TypeError, KeyError, AttributeError, OSError, SyntaxError, RecursionError) as error:
        return {"valid": False, "errors": [str(error)]}
    if result.language is None:
        return {"valid": True, "errors": []}
    return {"valid": True, "errors": [], "verification": verification,
            "source_shape_verified": verification == "SOURCE_REPLAY",
            "code_constant_provenance_verified": bool(result.language and result.language.constants)
                and verification == "SOURCE_REPLAY",
            "runtime_code_instance_established": False}


__all__ = ["SourceProgram", "PreparedSource", "LoweredSourceBody", "prepare_source",
           "lower_source", "validate_source_program"]
