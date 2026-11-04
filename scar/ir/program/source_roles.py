"""F3-B field-role facts, sharing F2 payloads instead of copying their values."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlotRef:
    occurrence: int
    group: str
    ordinal: int
    item_path: tuple[int, ...] = ()

    def __post_init__(self):
        if (type(self.occurrence) is not int or self.occurrence < 0
                or type(self.group) is not str or self.group not in ('FIELD', 'ATTRIBUTE')
                or type(self.ordinal) is not int or self.ordinal < 0
                or type(self.item_path) is not tuple
                or any(type(i) is not int or i < 0 for i in self.item_path)):
            raise ValueError('invalid original F2 slot reference')


@dataclass(frozen=True, slots=True)
class FieldRule:
    rule: int
    constructor: str
    group: str
    ordinal: int
    name: str
    shape: str
    family: str
    role: str
    selector: str
    sparse: bool


@dataclass(frozen=True, slots=True)
class RoleConstructor:
    name: str
    fields: tuple[int, ...]
    attributes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RoleCatalog:
    rule_version: str
    f2_schema_sha256: str
    content_sha256: str
    constructors: tuple[RoleConstructor, ...]
    rules: tuple[FieldRule, ...]
    schema: str = 'scar.source-role-catalog'
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class SlotResolution:
    site: SlotRef
    rule: int
    state: str
    role: str
    qualifiers: tuple[str, ...]
    projection: str
    context_owner: int | None


@dataclass(frozen=True, slots=True)
class RolePort:
    site: SlotRef
    rule: int
    role: str
    projection: str
    context_owner: int | None
    qualifiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuleCount:
    rule: int
    slots: int
    absent: int
    none: int
    empty_list: int
    values: int
    list_items: int
    ports: int

    def __post_init__(self):
        values = (self.rule, self.slots, self.absent, self.none, self.empty_list,
            self.values, self.list_items, self.ports)
        if (any(type(n) is not int or n < 0 for n in values)
                or self.absent + self.none + self.empty_list + self.values != self.slots):
            raise ValueError('field role count partition is not closed')


@dataclass(frozen=True, slots=True)
class RoleFrontier:
    code: str
    site: SlotRef
    processed_slots: int
    processed_ports: int
    detail: str


@dataclass(frozen=True, slots=True)
class RoleClassification:
    status: str
    ports: tuple[RolePort, ...]
    counts: tuple[RuleCount, ...]
    slots: int
    list_items: int
    frontiers: tuple[RoleFrontier, ...]


@dataclass(frozen=True, slots=True)
class SourceRolesProfile:
    rule_version: str
    f2_schema_sha256: str
    catalog_sha256: str
    implementation_sha256: str


@dataclass(frozen=True, slots=True)
class SourceRolesInput:
    f0_document_sha256: str
    f1_document_sha256: str
    f2_document_sha256: str
    path: str
    mode: str
    f2_status: str


@dataclass(frozen=True, slots=True)
class SourceRolesMaterial:
    input: SourceRolesInput
    profile: SourceRolesProfile
    max_ports: int
    max_slots: int
    status: str
    ports: tuple[RolePort, ...]
    counts: tuple[RuleCount, ...]
    slots: int
    list_items: int
    frontiers: tuple[RoleFrontier, ...]
    authority: str = 'SYNTAX_FIELD_ROLES'
    scope_binding: str = 'NOT_COMPUTED_IN_F3B'
    runtime_effects: str = 'NOT_CLAIMED'
    schema: str = 'scar.source-roles'
    schema_version: int = 1

    def __post_init__(self):
        if (self.schema != 'scar.source-roles' or type(self.schema_version) is not int or self.schema_version != 1
                or self.authority != 'SYNTAX_FIELD_ROLES' or self.scope_binding != 'NOT_COMPUTED_IN_F3B'
                or self.runtime_effects != 'NOT_CLAIMED'
                or self.status not in ('CLASSIFIED', 'UPSTREAM_NOT_PARSED', 'BUDGET_STOPPED')
                or any(type(n) is not int or n < 0 for n in (self.max_ports, self.max_slots, self.slots, self.list_items))
                or tuple(c.rule for c in self.counts) != tuple(range(484))
                or sum(c.slots for c in self.counts) != self.slots
                or sum(c.list_items for c in self.counts) != self.list_items
                or sum(c.ports for c in self.counts) != len(self.ports)
                or len(self.ports) > self.max_ports or self.slots > self.max_slots):
            raise ValueError('invalid F3-B role envelope or coverage counters')
        if self.status != 'CLASSIFIED' and (self.ports or self.slots or self.list_items):
            raise ValueError('incomplete role classification must not publish a partial table')
        if bool(self.frontiers) != (self.status == 'BUDGET_STOPPED'):
            raise ValueError('role status and budget frontiers disagree')
