"""Original native record -> canonical interface occurrence, without completion claims."""
from dataclasses import dataclass
from scar.ir.program.ids import NativeBoundaryID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from .common import Unresolved
from .content import NativeInputRef
from .coordinates import ProgramSnapshot
from .fragment_relations import EvidenceInstanceRef, FragmentLocator
from .ids import OperationOccurrenceID


@dataclass(frozen=True, slots=True)
class NativeDeclarationOccurrence:
    native: EvidenceInstanceRef
    definition: FragmentLocator
    ports: FragmentLocator
    execution: ProviderArtifact
    snapshot: ProgramSnapshot
    invocation: OperationOccurrenceID
    boundary: NativeBoundaryID
    inputs: tuple[NativeInputRef, ...]
    output_sources: tuple[ProviderFactReference, ...]
    completion: Unresolved

    def __post_init__(self):
        for name, cls in (('native',EvidenceInstanceRef),('definition',FragmentLocator),
            ('ports',FragmentLocator),('execution',ProviderArtifact),('snapshot',ProgramSnapshot),
            ('invocation',OperationOccurrenceID),('boundary',NativeBoundaryID),('completion',Unresolved)):
            value=getattr(self,name)
            if type(value)is not cls:raise TypeError('native declaration requires exact '+name)
            value.__post_init__()
        for name,cls in (('inputs',NativeInputRef),('output_sources',ProviderFactReference)):
            value=getattr(self,name)
            if type(value)is not tuple or any(type(v)is not cls for v in value):
                raise TypeError('native declaration requires typed '+name)
            for v in value:v.__post_init__()
