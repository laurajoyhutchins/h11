"""Deterministically compile contract DAG into exact Git trees and verify commit ancestry.

No writes. The only inputs are pinned source commit, JSON contracts and existing
Git objects. Git is authoritative for blobs, file modes and parent relationships.
"""
from __future__ import annotations
import ast
import hashlib
import json
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
LEDGER=json.loads((HERE/"contracts.json").read_text())
COMMITS=json.loads((HERE/"generated_commits.json").read_text())

def git(*args):
    return subprocess.check_output(("git",*args)).decode().strip()

def original_blobs(ref):
    data=subprocess.check_output(["git","ls-tree","-r","-z",ref])
    blobs={}
    for line in data.split(b"\0"):
        if not line: continue
        meta,path=line.split(b"\t",1)
        mode,kind,sha=meta.decode().split()
        assert kind=="blob"
        name=path.decode()
        blobs[name]={"path":name,"mode":mode,"sha":sha,"type":"blob"}
    return blobs

def tree_sha(files):
    root={}
    for path,meta in files.items():
        bits=path.split("/")
        d=root
        for part in bits[:-1]:d=d.setdefault(part,{})
        assert bits[-1] not in d,path
        d[bits[-1]]=meta
    def digest(d):
        items=[]
        for name,item in d.items():
            is_dir="sha" not in item
            mode="40000" if is_dir else item["mode"]
            sha=digest(item) if is_dir else item["sha"]
            sort_key=name.encode()+(b"/" if is_dir else b"")
            obj=mode.encode()+b" "+name.encode()+b"\0"+bytes.fromhex(sha)
            items.append((sort_key,obj))
        raw=b"".join(content for _,content in sorted(items))
        return hashlib.sha1(b"tree "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    return digest(root)

def dependencies(module,source):
    result=set()
    def walk(node,type_only=False):
        if isinstance(node,ast.If) and isinstance(node.test,ast.Name) and node.test.id=="TYPE_CHECKING":
            for child in node.body: walk(child,True)
            for child in node.orelse:walk(child,type_only)
            return
        if not type_only and isinstance(node,ast.ImportFrom):
            if node.level and node.module and node.module.startswith("_"):
                result.add(node.module.split(".")[0])
            elif node.module and node.module.startswith("h11._"):
                result.add(node.module.split(".")[1])
        if not type_only and isinstance(node,ast.Import):
            for alias in node.names:
                if alias.name.startswith("h11._"):result.add(alias.name.split(".")[1])
        for child in ast.iter_child_nodes(node):walk(child,type_only)
    walk(ast.parse(source))
    return result

source=LEDGER["source"];expected_tree=source["tree"]
assert COMMITS["source_commit"]==source["commit"]
assert COMMITS["source_tree"]==expected_tree
assert git("rev-parse",source["commit"]+"^{tree}")==expected_tree
blobs=original_blobs(source["commit"])
assert len(blobs)==69
assert tree_sha(blobs)==expected_tree

# Verify declared module closures from the actual pinned Python sources, not
# merely from the manifest written by the experimenter.
modules={p[4:-3] for p in blobs if p.startswith("h11/_") and p.endswith(".py")}
dep={}
for module in sorted(modules):
    src=git("show",f"{source['commit']}:h11/{module}.py")
    dep[module]={d for d in dependencies(module,src) if d in modules}
def closure(m):
    found=set()
    def visit(n):
        if n in found:return
        found.add(n)
        for child in dep[n]:visit(child)
    visit(m)
    return {"h11/"+n+".py" for n in found}
for c in LEDGER["contracts"]:
    expected=set(c["import_closure"])
    actual=(closure(c["implementation"][4:-3]) if c["implementation"]
            else closure("_readers")|closure("_writers"))
    assert actual==expected,(c["id"],sorted(actual^expected))
    if c["implementation"]:
        assert blobs[c["implementation"]]["sha"]==c["blob_sha"],c["id"]

nodes={}
commits=COMMITS["nodes"]
for node in LEDGER["nodes"]:
    files={}
    for parent in node["parents"]:
        for path,record in nodes[parent]["files"].items():
            assert path not in files or files[path]==record
            files[path]=record
    for path in node["add_paths"]:
        assert path in blobs,path
        files[path]=blobs[path]
    if node.get("all_original_blobs"):files=dict(blobs)
    if node["contract"]:
        spec=next(c for c in LEDGER["contracts"] if c["id"]==node["contract"])
        assert set(spec["import_closure"])<=files.keys(),node["id"]
    tree=tree_sha(files)
    info=commits[node["id"]]
    assert info["tree"]==tree,(node["id"],tree,info["tree"])
    assert git("rev-parse",info["sha"]+"^{tree}")==tree
    parents=git("rev-list","--parents","-n","1",info["sha"]).split()[1:]
    assert parents==info["parents"],(node["id"],parents)
    expected_parents=([nodes[p]["commit"] for p in node["parents"]]
                      if node["parents"] else [source["commit"]])
    assert parents==expected_parents,(node["id"],expected_parents,parents)
    nodes[node["id"]]={"files":files,"commit":info["sha"]}
    print(f"{node['id']:<20} {tree} {len(files)} original blobs; parent(s) verified")

assert tree_sha(nodes["complete"]["files"])==expected_tree
assert git("rev-parse","research/contract-generated-history")==commits["complete"]["sha"]
assert not git("diff","--name-only",source["commit"],commits["complete"]["sha"])
print("VERIFIED: exact tree, dependency closures, contract stages, ancestry and unchanged source")
