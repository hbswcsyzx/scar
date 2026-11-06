"""Mutable dictionary views of original root namespace input references.

The proxy reuses the globals formal point. It is neither a fresh allocation
nor a module object. Content remains open and flow-insensitive; root bindings
and declared external input fields retain their separate provenance.
"""
from hashlib import sha256

from scar.analysis.source_template_links import _json
from scar.ir.program import normal_links as F, source_productions as P
from scar.ir.program import source_frame_bindings as B
from scar.ir.record_codec import encode


_NAMESPACE_TAGS = frozenset(('source_root_namespace',))
_METHODS = frozenset(('get','update','keys','values','items'))


class RootNamespaceViews:
    def __init__(self, solver, frames):
        self.s,self.frames = solver,frames
        self.roots,self.proxies,self.proxy_units = {},{},{}
        self.input_bindings = {}
        self._mirrored,self._forwarded = set(),set()

    @staticmethod
    def _channel(unit, key):
        return unit,F.NamespaceKind.MODULE.value,0,key

    def admit(self, root_binding, contract=None):
        unit = root_binding.root.owner.unit
        previous = self.roots.get(unit)
        if previous is not None and (previous.root != root_binding.root
                or previous.globals != root_binding.globals or previous.locals != root_binding.locals):
            raise ValueError('root namespace view changed its original input interface')
        self.roots[unit] = root_binding
        proxy = ('container',self.frames.point(root_binding.globals),'MAPPING')
        self.proxies[unit] = proxy;self.proxy_units[proxy] = unit
        # A root input is not a closed source display, including an empty view.
        self.s.containers.open_containers.add(proxy)
        sources = tuple(self.s.containers.namespace_sources.items())
        for channel,points in sources:
            if channel[:3] == (unit,F.NamespaceKind.MODULE.value,0) and type(channel[3]) is str:
                for source in tuple(points):
                    self.name_write(unit,channel[3],source)
        for channel,targets in tuple(self.s.reads.items()):
            if channel[:3] == (unit,F.NamespaceKind.MODULE.value,0) and type(channel[3]) is str:
                for target in tuple(targets):
                    self.name_read(unit,channel[3],target)
        if contract is not None:
            digest = sha256(_json(encode(contract,record_tags=P.PRODUCTION_RECORD_TAGS))).hexdigest()
            if (contract.root != root_binding.root or contract.source.unit != unit
                    or root_binding.entry_contract_sha256 != digest):
                raise ValueError('root namespace external inputs differ from the declared entry contract')
            for index,binding in enumerate(contract.globals):
                if binding.namespace.kind is not F.NamespaceKind.MODULE or binding.namespace.owner != 0:
                    raise ValueError('entry global field has no root namespace key')
                port = B.StaticInputPort(root_binding.root,digest,('globals',index,'literal'))
                record = B.StaticInputBinding(port,binding.literal)
                if port in self.input_bindings:
                    if self.input_bindings[port] != record:
                        raise ValueError('declared entry field changed its literal')
                    continue
                self.input_bindings[port] = record
                point = self.s.interface_point(('static-entry-field',port),port)
                value = binding.literal.to_python()
                self.s.add(point,('constant',type(value).__name__,value))
                self.name_write(unit,binding.namespace.name,point)
        return proxy

    def proxy(self, token):
        if token[0] not in _NAMESPACE_TAGS:
            raise ValueError('root namespace reference token required')
        unit = token[1]
        if unit not in self.proxies:
            binding = self.frames.roots.get(unit)
            if binding is None:
                raise ValueError('root namespace input binding must be admitted before its view')
            self.admit(binding,self.frames.entry_contracts.get(unit))
        return self.proxies[unit]

    def name_write(self, unit, key, source):
        proxy = self.proxies.get(unit)
        if proxy is None or type(key) is not str:
            return
        item = proxy,('str',key),source
        if item in self._mirrored:
            return
        self._mirrored.add(item)
        self.s.containers.write(*item)

    def name_read(self, unit, key, target):
        proxy = self.proxies.get(unit)
        if proxy is not None and type(key) is str:
            self.s.containers.read(proxy,('str',key),target)

    def content_write(self, container, key, source):
        unit = self.proxy_units.get(container)
        if unit is None or key is None or key[0] != 'str':
            # Unknown writes already reach all registered proxy readers, and
            # future name_read subscriptions replay their wildcard contents.
            return
        item = container,key,source
        if item in self._forwarded:
            return
        self._forwarded.add(item)
        channel = self._channel(unit,key[1])
        self.s.containers.namespace_sources[channel].add(source)
        self.s.writes[source].add(channel)
        for value in tuple(self.s.values.get(source,())):
            self.s.namespace_value(channel,value)
        # The ordinary namespace subscriptions are retained too. Register all
        # existing readers so later wildcard writes reach them through the view.
        for target in tuple(self.s.reads.get(channel,())):
            self.name_read(unit,key[1],target)
        self.frames.name_write(unit,key[1],source)

    def access(self, token, key, target, write):
        self.s.containers.access(self.proxy(token),key,target,write)

    def attribute(self, token, name, target):
        proxy = self.proxy(token)
        if name == 'copy':
            self.s.add(target,('container_method',proxy,'copy'))
            return True
        if name in _METHODS:
            self.s.containers.attribute(proxy,name,target)
            return True
        return False

