"""BC6H index refinement scored in decoded linear RGB, without changing endpoints."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
import sys
import time

sys.dont_write_bytecode=True
import experiment as e


def anchors():
    source=(e.OUT/"bcdec.h").read_text(encoding="utf-8-sig")
    table=source.split("partition_sets[32][4][4] = {",1)[1].split("};",1)[0]
    table=re.sub(r"/\*.*?\*/","",table,flags=re.S)
    numbers=list(map(int,re.findall(r"\d+",table)))
    if len(numbers)!=512:raise ValueError("Unexpected BC6H partition table")
    return [next(i for i,n in enumerate(numbers[p*16:(p+1)*16]) if n==129) for p in range(32)]


def layout(block,fixups):
    bits=int.from_bytes(block,"little")
    single=(bits&31) in (3,7,11,15)
    anchor=-1 if single else fixups[(bits>>77)&31]
    offset=65 if single else 82;result=[]
    for pixel in range(16):
        width=(4 if single else 3)-int(pixel==0 or pixel==anchor)
        result.append((offset,width));offset+=width
    if offset!=128:raise AssertionError("Invalid index layout")
    return bits,result,65 if single else 82


def refine_block(block,target,valid,fixups):
    bits,fields,start=layout(block,fixups);base=bits&((1<<start)-1)
    palettes=[]
    for index in range(16):
        value=base|sum((index&((1<<width)-1))<<offset for offset,width in fields)
        palettes.append(imagecodecs.bcn_decode(value.to_bytes(16,"little"),6,shape=(4,4,3)).reshape(16,3).astype(float))
    palettes=np.asarray(palettes)
    nearest=np.argmin(np.sum((palettes-target[None,:,:])**2,axis=-1),axis=0)
    for pixel,(offset,width) in enumerate(fields):
        index=int(nearest[pixel]) if valid[pixel] else (bits>>offset)&((1<<width)-1)
        base|=(index&((1<<width)-1))<<offset
    result=base.to_bytes(16,"little")
    decoded=imagecodecs.bcn_decode(result,6,shape=(4,4,3)).reshape(16,3).astype(float)
    original=imagecodecs.bcn_decode(block,6,shape=(4,4,3)).reshape(16,3).astype(float)
    old=float(np.sum((original[valid]-target[valid])**2));new=float(np.sum((decoded[valid]-target[valid])**2))
    if new>old+max(1e-15,old*1e-12):raise AssertionError("Linear reindex increased block SSE")
    return result,new


def refine(case,size,policy,limit=64):
    rawdir=e.OUT/"raw"/str(size)/case/policy
    raw=e.previous.levels(rawdir);sources=[e.encode(rawdir,size,c) for c in ("basic-black","basic-edge","slow-edge")]
    documents=[(p/"specular.ktx2").read_bytes() for p in sources]
    outputs={"linear-rgb-edge":[],"portfolio-edge":[]};fixups=anchors();start=time.perf_counter()
    for mip,cube in enumerate(raw):
        payloads=[]
        for data in documents:
            offset,length,uncompressed=struct.unpack_from("<QQQ",data,80+24*mip)
            payloads.append(zstandard.ZstdDecompressor().decompress(data[offset:offset+length],max_output_size=uncompressed))
        if cube.size>limit:
            for label in outputs:outputs[label].append(payloads[0])
            continue
        n=cube.size;blocks=(n+3)//4;results={label:bytearray() for label in outputs}
        for face in range(6):
            for by in range(blocks):
                for bx in range(blocks):
                    target=np.zeros((4,4,3));valid=np.zeros((4,4),dtype=bool)
                    height=min(4,n-by*4);width=min(4,n-bx*4)
                    target[:height,:width]=np.clip(cube.faces[face,by*4:by*4+height,bx*4:bx*4+width],0,65504)
                    valid[:height,:width]=True;target=target.reshape(16,3);valid=valid.ravel()
                    offset=((face*blocks+by)*blocks+bx)*16
                    candidates=[p[offset:offset+16] for p in payloads]
                    original=imagecodecs.bcn_decode(candidates[0],6,shape=(4,4,3)).reshape(16,3).astype(float)
                    original_error=float(np.sum((original[valid]-target[valid])**2))
                    refined=[refine_block(c,target,valid,fixups) for c in candidates]
                    results["linear-rgb-edge"].extend(refined[1][0])
                    results["portfolio-edge"].extend(min([(candidates[0],original_error),*refined],key=lambda x:x[1])[0])
        for label in outputs:outputs[label].append(bytes(results[label]))
    for label,payloads in outputs.items():
        original=documents[0];count=len(raw);first=min(struct.unpack_from("<Q",original,80+24*mip)[0] for mip in range(count))
        header=bytearray(original[:first]);blobs=[zstandard.ZstdCompressor(level=3).compress(p) for p in payloads]
        offset=len(header)
        for mip in reversed(range(count)):
            struct.pack_into("<QQQ",header,80+24*mip,offset,len(blobs[mip]),len(payloads[mip]));offset+=len(blobs[mip])
        directory=e.OUT/"encoded"/str(size)/case/policy/label;directory.mkdir(parents=True,exist_ok=True)
        file=directory/"specular.ktx2";file.write_bytes(bytes(header)+b"".join(reversed(blobs)))
        e.save(directory/"generation.json",dict(raw=e.digest(rawdir/"generation.json"),inputs={str(p):e.digest(p/"specular.ktx2") for p in sources},
            method=e.digest(__file__),reference=e.digest(e.OUT/"bcdec.h"),sha256=e.digest(file),seconds=time.perf_counter()-start,limit=limit))
    print("refined",size,case,policy,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages",type=Path,action="append",default=[])
    parser.add_argument("--size",type=int,default=128)
    parser.add_argument("--cases",default="constant,hemisphere-0,hemisphere-1,hemisphere-2")
    parser.add_argument("--policies",default="quadratic,linear")
    args=parser.parse_args();e.initialize(args.python_packages)
    global np,imagecodecs,zstandard
    import numpy as np
    import imagecodecs
    import zstandard
    for case in args.cases.split(","):
        for policy in args.policies.split(","):refine(case,args.size,policy)

if __name__=="__main__":main()
