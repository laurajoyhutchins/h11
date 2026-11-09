"""Execute independent chunked-codec contracts at pinned Git commits.

No installed h11 import fallback, pytest dependency, Git mutation, or source rewrite.
The original h11/__init__.py is absent at codec introduction; a scratch-only
package shim allows importing the exact original module blobs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MUTATIONS = {
    "reader": {
        "chunk-length-plus-one": ('self._bytes_in_chunk = int(matches["chunk_size"], base=16)',
                                  'self._bytes_in_chunk = int(matches["chunk_size"], base=16) + 1'),
        "discard-only-lf": ('self._bytes_to_discard = b"\\r\\n"',
                            'self._bytes_to_discard = b"\\n"'),
        "drop-trailers": ('return EndOfMessage(headers=list(_decode_header_lines(lines)))',
                          'return EndOfMessage()'),
    },
    "writer": {
        "chunk-length-plus-one": ('write(b"%x\\r\\n" % len(data))',
                                  'write(b"%x\\r\\n" % (len(data) + 1))'),
        "omit-data-footer-cr": ('write(data)\n        write(b"\\r\\n")',
                                'write(data)\n        write(b"\\n")'),
        "wrong-terminal-chunk": ('write(b"0\\r\\n")', 'write(b"1\\r\\n")'),
    },
}
# Independent wire-format oracles, not production reader/writer calls acting as oracles.
ORACLES = {
    "reader": r'''
import random
from h11._readers import ChunkedReader
from h11._receivebuffer import ReceiveBuffer
from h11._events import Data, EndOfMessage
from h11._util import LocalProtocolError, RemoteProtocolError
def check(wire, payload, trailers=None, fragmented=False):
    r=ChunkedReader(); b=ReceiveBuffer(); parts=[]; end=[]
    if fragmented: chunks=[bytes([c]) for c in wire]
    else: chunks=[wire]
    for chunk in chunks:
        b+=chunk
        for budget in range(5000):
            event=r(b)
            if event is None: break
            if isinstance(event, Data): parts.append(bytes(event.data))
            elif isinstance(event, EndOfMessage): end.append(event); break
            else: raise AssertionError(repr(event))
        else: raise AssertionError("nonterminating reader")
    assert b"".join(parts)==payload, (parts, payload)
    assert len(end)==1, end
    assert list(end[0].headers)==(trailers or [])
for size in (1,3,15,16,255):
    data=bytes((i*37+11)%256 for i in range(size))
    wire=format(size,"x").encode()+b"\r\n"+data+b"\r\n0\r\n\r\n"
    check(wire,data)
    check(wire,data,fragmented=True)
check(b"0\r\nX-Check: yes\r\n\r\n",b"",[(b"x-check",b"yes")])
for bad in (b"z\r\nhello\r\n",b"3\r\nabcXX0\r\n\r\n"):
    b=ReceiveBuffer(); b+=bad; r=ChunkedReader()
    try:
        for _ in range(10):
            if r(b) is None: break
    except LocalProtocolError: pass
    else: raise AssertionError("invalid chunk accepted")
try: ChunkedReader().read_eof()
except RemoteProtocolError: pass
else: raise AssertionError("premature EOF accepted")
''',
    "writer": r'''
from h11._writers import ChunkedWriter
from h11._events import Data, EndOfMessage
def expected(data):
    return (format(len(data),"x").encode()+b"\r\n"+data+b"\r\n") if data else b""
for size in (0,1,2,3,15,16,255,256):
    body=bytes((i*31+7)%256 for i in range(size))
    out=[]; w=ChunkedWriter()
    w(Data(data=body),out.append)
    w(EndOfMessage(),out.append)
    assert b"".join(out)==expected(body)+b"0\r\n\r\n",out
out=[];w=ChunkedWriter()
for part in (b"abc",b"",b"defg"): w(Data(data=part),out.append)
w(EndOfMessage(headers=[(b"X-Check",b"yes")]),out.append)
assert b"".join(out)==b"3\r\nabc\r\n4\r\ndefg\r\n0\r\nX-Check: yes\r\n\r\n",out
''',
    "composition": r'''
from h11._writers import ChunkedWriter
from h11._readers import ChunkedReader
from h11._events import Data, EndOfMessage
from h11._receivebuffer import ReceiveBuffer
for size in (0,1,2,3,16,63,255):
    body=bytes((i*41+17)%256 for i in range(size))
    writer=ChunkedWriter(); encoded=[]
    for part in (body[:size//2],b"",body[size//2:]):writer(Data(data=part),encoded.append)
    writer(EndOfMessage(),encoded.append)
    reader=ChunkedReader();buf=ReceiveBuffer();buf+=b"".join(encoded)
    pieces=[];finished=[]
    for _ in range(1000):
        e=reader(buf)
        if isinstance(e,Data):pieces.append(bytes(e.data))
        elif isinstance(e,EndOfMessage):finished.append(e);break
        elif e is None: raise AssertionError("early incomplete read")
    assert b"".join(pieces)==body
    assert len(finished)==1
''',
}
STAGES = {"reader": "chunked-reader", "writer": "chunked-writer", "composition": "codec-composition"}

def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])

def blob_sha(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def execute(repo, ref, contract, mutation=None):
    with tempfile.TemporaryDirectory(prefix="h11-contract-") as td:
        root=Path(td);pkg=root/"h11";pkg.mkdir()
        (pkg/"__init__.py").write_text("# scratch-only package import shim\n")
        for path in contract["import_closure"]:
            original=git(repo,"show",f"{ref}:{path}")
            if path==contract["implementation"] and contract["blob_sha"]:
                assert blob_sha(original)==contract["blob_sha"],path
            text=original.decode("utf-8")
            if mutation and path==contract["implementation"]:
                before,after=MUTATIONS[contract["id"].split(".")[-1]][mutation]
                assert text.count(before)==1,(path,mutation)
                text=text.replace(before,after)
            (root/path).write_text(text)
        kind=contract["id"].split(".")[-1]
        script="import sys,pathlib\nsys.path.insert(0,"+repr(td)+")\n"+ORACLES[kind]
        script+="\nimport h11\nassert pathlib.Path(h11.__file__).resolve()==pathlib.Path("+repr(str(pkg/"__init__.py"))+").resolve()\n"
        result=subprocess.run([sys.executable,"-I","-S","-c",script],capture_output=True,text=True,timeout=20)
        if mutation is None and result.returncode!=0:
            raise AssertionError(f"Contract {kind} failed unexpectedly:\n{result.stderr[-2000:]}")
        if mutation is not None and (result.returncode==0 or
                "ImportError:" in result.stderr or "ModuleNotFoundError:" in result.stderr or
                "SyntaxError:" in result.stderr or
                not any(marker in result.stderr for marker in ("AssertionError", "h11._util.LocalProtocolError", "h11._util.RemoteProtocolError"))):
            raise AssertionError(f"Mutant {kind}/{mutation} survived or broke the harness:\n{result.stderr[-2000:]}")
        return {"contract":contract["id"],"checkpoint":ref,"mutant":mutation,
                "result":"PASS" if mutation is None else "KILLED"}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo",type=Path,default=Path.cwd())
    parser.add_argument("--commits",required=True,type=Path,
                        help="JSON mapping node id to pinned commit SHA")
    parser.add_argument("--mutations",action="store_true")
    args=parser.parse_args()
    manifest=json.loads((ROOT/"contracts.json").read_text())
    commits=json.loads(args.commits.read_text())
    results=[]
    for contract in manifest["contracts"]:
        ref=commits["nodes"][STAGES[contract["id"].split(".")[-1]]]["sha"]
        results.append(execute(args.repo,ref,contract))
        if args.mutations:
            for mutant in contract["mutants"]:
                results.append(execute(args.repo,ref,contract,mutant))
    print(json.dumps({"checks":results,"all_passed":True},indent=2))
if __name__=="__main__":
    main()
