"""Isolate uniform 1x1 BC6H padding from spatially varying partial blocks."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode=True
import experiment as e


def generate():
    import zstandard
    for source in sorted((e.OUT/"raw").glob("*/*/*")):
        if not (source/"metadata.json").exists():continue
        size=int(source.parent.parent.name);case=source.parent.name;policy=source.name
        root=e.OUT/"encoded"/str(size)/case/policy
        inputs=[root/codec/"specular.ktx2" for codec in ("basic-black","basic-edge")]
        if not all(p.exists() for p in inputs):continue
        original,edge=[p.read_bytes() for p in inputs]
        widths=[row["size"] for row in json.loads((source/"metadata.json").read_text())["levels"]]
        payloads=[]
        for mip,width in enumerate(widths):
            data=edge if width==1 else original
            offset,length,uncompressed=struct.unpack_from("<QQQ",data,80+24*mip)
            payloads.append(zstandard.ZstdDecompressor().decompress(data[offset:offset+length],max_output_size=uncompressed))
        first=min(struct.unpack_from("<Q",original,80+24*mip)[0] for mip in range(len(widths)))
        header=bytearray(original[:first]);blobs=[zstandard.ZstdCompressor(level=3).compress(p) for p in payloads]
        offset=len(header)
        for mip in reversed(range(len(widths))):
            struct.pack_into("<QQQ",header,80+24*mip,offset,len(blobs[mip]),len(payloads[mip]));offset+=len(blobs[mip])
        directory=root/"single-texel-edge";directory.mkdir(parents=True,exist_ok=True)
        result=directory/"specular.ktx2";result.write_bytes(bytes(header)+b"".join(reversed(blobs)))
        e.save(directory/"generation.json",dict(inputs={str(p):e.digest(p) for p in inputs},method=e.digest(__file__),sha256=e.digest(result),
            policy="Replicate the sole valid texel at width 1; retain baseline blocks at every other width"))
        print("single texel",size,case,policy,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages",type=Path,action="append",default=[])
    args=parser.parse_args();e.initialize(args.python_packages);generate()

if __name__=="__main__":main()
