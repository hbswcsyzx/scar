"""Root-authorized exact absent tracked input restoration; no index or graph decode."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = Path('/home/zyf/AAA/scar-worktrees/source858-runtime/artifacts/experiments/lewm_archived_compiler_gate_20261026/freeze.json')

def need(value, detail):
    if not value:
        raise ValueError(detail)

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])

def main():
    head = git('rev-parse', 'HEAD').decode().strip()
    rows = json.loads((HERE / 'original-input-availability.json').read_bytes())['original_inputs']
    restored = []
    def materialize(path, *, size, sha=None, declaration=None):
        path = Path(path)
        need(path.is_relative_to(ROOT / 'artifacts') and str(path.resolve()) == str(path), 'restore outside exact main artifacts')
        rel = path.relative_to(ROOT).as_posix()
        if path.exists():
            need(path.is_file() and not path.is_symlink(), 'existing input not ordinary')
            raw = path.read_bytes()
            action, oid = 'EXISTING_NOT_WRITTEN', None
        else:
            oid = git('rev-parse', '--verify', head + ':' + rel).decode().strip()
            raw = git('cat-file', 'blob', head + ':' + rel)
            actual_oid = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            need(actual_oid == oid, 'HEAD blob object identity differs')
            action = 'RESTORED_ABSENT_FROM_HEAD'
        actual = hashlib.sha256(raw).hexdigest()
        need(len(raw) == size and (sha is None or sha == actual), 'HEAD blob differs from original input receipt')
        if action == 'RESTORED_ABSENT_FROM_HEAD':
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
        restored.append({'path': str(path), 'sha256': actual, 'bytes': len(raw), 'action': action,
                         'head_blob_oid': oid, 'expected_original_stored_sha256': sha,
                         'graph_declaration': declaration,
                         'graph_canonical_payload_verified_here': False})
    for row in rows:
        materialize(row['path'], size=row['bytes'], sha=row['sha256'])
    config = json.loads((HERE / 'inputs.json').read_bytes())
    continuation_path = Path(config['continuation']['path'])
    continuation = json.loads(continuation_path.read_bytes())
    graph_seen = set()
    for row in continuation['source_files']:
        locator = row['source_graph_artifact']
        if locator is None:
            continue
        artifact = locator['artifact']
        if locator['origin'] == 'PARENT':
            base = Path(locator['parent_directory'])
            need(str(base) == continuation['parent']['directory'], 'parent graph path differs')
        else:
            need(locator['origin'] == 'CONTINUATION', 'unknown original graph origin')
            base = continuation_path.parent
        path = base / artifact['path']
        if str(path) in graph_seen:
            continue
        graph_seen.add(str(path))
        materialize(path, size=artifact['compressed_bytes'], declaration=artifact)
    result = {'schema': 'scar.original-absent-input-restoration/1', 'head': head,
        'root_authorization': 'restore only absent exact original input URIs from HEAD blobs; no index/sparse edits',
        'rows': restored, 'original_receipt_files': len(rows), 'declared_graph_files': len(graph_seen),
        'materialization_bytes': sum(r['bytes'] for r in restored if r['action'] == 'RESTORED_ABSENT_FROM_HEAD'),
        'scope': 'source/control restoration I/O, separate from later normal consumer actual I/O',
        'graph_decode_compile_target': False, 'canonical_graph_hash_verified': 'only later selected ordinary reader'}
    with (HERE / 'restore-receipt.json').open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2); stream.write('\n')
    print(json.dumps({k: result[k] for k in ('head', 'original_receipt_files', 'declared_graph_files', 'materialization_bytes')}))

if __name__ == '__main__':
    main()
