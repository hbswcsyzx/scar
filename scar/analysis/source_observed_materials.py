"""Guard only the primitive fact leaves used by observed/source relations."""
from pathlib import Path
from hashlib import sha256

from scar.analysis.source_fact_materials import FactMaterialResolver


class ObservedFactMaterials:
    def __init__(self,catalog):
        self.resolver=FactMaterialResolver(catalog)
        if (self.resolver.catalog.path,self.resolver.catalog.report)!=(catalog.path,catalog.report):
            raise ValueError('observed primitive facts use a different source catalog')
        self.routes={};self._guard={};self._references=set()

    def admit(self,references):
        selected=tuple(r for r in references if r not in self._references)
        for route in self.resolver.verify(selected):
            for artifact in (route.physical,*route.catalogs):
                path=Path(artifact.uri);raw=path.read_bytes()
                if (len(raw),sha256(raw).hexdigest())!=(artifact.size_bytes,artifact.sha256):
                    raise ValueError('observed primitive fact receipt changed during admission')
                if path in self._guard and self._guard[path]!=raw:
                    raise ValueError('observed primitive facts changed during admission')
                self._guard[path]=raw
            self.routes[route.logical]=route
        self._references.update(selected);self.check()

    def check(self):
        self.resolver.validate_catalog()
        if any(path.read_bytes()!=raw for path,raw in self._guard.items()):
            raise ValueError('observed primitive fact leaf or catalog receipt changed')
