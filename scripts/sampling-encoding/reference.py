"""Independent full-source cube-UV quadrature with explicit convergence diagnostics."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode=True
import experiment as e


def probes(cube):
    base=e.previous.directions();n=cube.size
    centers=(np.arange(n)+.5)/n*2-1;u,v=np.meshgrid(centers,centers)
    rays=np.stack([e.previous.quality.face_direction(f,u,v) for f in range(6)]).reshape(-1,3)
    luma=(cube.faces@np.array([.2126,.7152,.0722])).ravel()
    axes=[]
    for index in np.argsort(luma)[::-1]:
        ray=rays[index]
        if all(ray@a<np.cos(np.deg2rad(5)) for a in axes):axes.append(ray)
        if len(axes)==3:break
    local=[]
    for axis in axes:
        tangent=np.cross(axis,[0.,1.,0.])
        if np.linalg.norm(tangent)<.01:tangent=np.cross(axis,[1.,0.,0.])
        tangent/=np.linalg.norm(tangent);bitangent=np.cross(axis,tangent)
        for x,y in [(0,0),(.01,0),(-.01,0),(0,.01),(0,-.01),(.03,0),(-.03,0),(0,.03),(0,-.03)]:
            ray=axis+x*tangent+y*bitangent;local.append(ray/np.linalg.norm(ray))
    return np.concatenate([base,local])


def geometry(bounds,order,face,cube):
    nodes,weights=np.polynomial.legendre.leggauss(order)
    u0,u1,v0,v1=bounds.T
    u=u0[:,None]+(nodes[None,:]+1)*(u1-u0)[:,None]/2
    v=v0[:,None]+(nodes[None,:]+1)*(v1-v0)[:,None]/2
    uu=np.broadcast_to(u[:,:,None],(len(bounds),order,order)).ravel()
    vv=np.broadcast_to(v[:,None,:],(len(bounds),order,order)).ravel()
    w=((u1-u0)*(v1-v0))[:,None,None]/4*weights[None,:,None]*weights[None,None,:]
    w=w.ravel()/(1+uu*uu+vv*vv)**1.5
    rays=e.previous.quality.face_direction(face,uu,vv)
    rgb=cube.sample(rays)
    return rays,np.column_stack([rgb,np.ones(len(rgb))])*w[:,None]


def integrate(cube,directions,roughnesses,order):
    n=cube.size;knots=np.concatenate([[-1.],(np.arange(n)+.5)/n*2-1,[1.]])
    low_u,low_v=np.meshgrid(knots[:-1],knots[:-1]);hi_u,hi_v=np.meshgrid(knots[1:],knots[1:])
    bounds=np.stack([low_u.ravel(),hi_u.ravel(),low_v.ravel(),hi_v.ravel()],axis=-1)
    result=np.zeros((len(roughnesses),len(directions),4))
    for face in range(6):
        rays,weighted=geometry(bounds,order,face,cube)
        centers=e.previous.quality.face_direction(face,(bounds[:,0]+bounds[:,1])/2,(bounds[:,2]+bounds[:,3])/2)
        for start in range(0,len(directions),8):
            normals=directions[start:start+8];mu=rays@normals.T
            for ri,r in enumerate(roughnesses):
                density=independent.normalized_kernel(mu,r)
                result[ri,start:start+len(normals)]+=density.T@weighted
                if r>.100001:continue
                for ni,normal in enumerate(normals):
                    mask=centers@normal>np.cos(16*r*r+4/n)
                    if not np.any(mask):continue
                    # Replace identical source-UV cells with a higher-order rule
                    # near the kernel peak; bright source texels are always in
                    # the full global domain and cannot be missed as a support mask.
                    selected=np.repeat(mask,order*order)
                    old=independent.normalized_kernel(mu[selected,ni],r)@weighted[selected]
                    local_rays,local_weighted=geometry(bounds[mask],order*4,face,cube)
                    new=independent.normalized_kernel(local_rays@normal,r)@local_weighted
                    result[ri,start+ni]+=new-old
        print("quadrature",cube.size,"order",order,"face",face,flush=True)
    return result


def evaluate(case,size,roughnesses):
    raw=e.OUT/"raw"/str(size)/case/"quadratic"
    cube=e.previous.levels(raw)[0];directions=probes(cube)
    identity=dict(case=case,size=size,roughnesses=roughnesses,probes=directions.tolist(),
        source={f:e.digest(raw/f"m0_{f}.f32") for f in e.FACES},method=e.digest(__file__),
        kernel=e.digest(e.ROOT/"scripts/mip-weighting/reference.py"))
    destination=e.OUT/"reference"/str(size)/f"{case}.json"
    if destination.exists() and json.loads(destination.read_text())["identity"]==identity:return
    start=time.perf_counter();ladder=[]
    for order in (2,4,6):ladder.append(integrate(cube,directions,roughnesses,order))
    rows=[]
    for i,r in enumerate(roughnesses):
        values=ladder[-1][i,:,:3]
        spread=np.maximum(np.max(np.abs(ladder[2][i,:,:3]-ladder[1][i,:,:3]),axis=-1),np.max(np.abs(ladder[1][i,:,:3]-ladder[0][i,:,:3]),axis=-1))
        scale=np.maximum(np.sqrt(np.mean(values**2,axis=-1)),1e-6)
        norm_error=np.max(np.abs(np.asarray([v[i,:,3] for v in ladder])-1),axis=0)
        converged=(spread<=1e-4*scale)&(norm_error<=1e-4)
        rows.append(dict(roughness=r,rgb=values.tolist(),spread=spread.tolist(),converged=converged.tolist(),normalizer_error=norm_error.tolist()))
        print(case,r,"converged",int(converged.sum()),"/",len(directions),"max norm",float(norm_error.max()),flush=True)
    e.save(destination,dict(identity=identity,rows=rows,seconds=time.perf_counter()-start,
        target="shared projected mip-zero source, reconstructed in cube UV",orders=[2,4,6],
        limitation="Observed convergence and analytic normalizer checks, not rigorous error bounds; no source mips, FIS or production sample sequence"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-packages",type=Path,action="append",default=[])
    parser.add_argument("--size",type=int,default=128)
    parser.add_argument("--cases",default="pisa,footprint,qwantani")
    parser.add_argument("--roughnesses",default="0.05,0.1,0.2,0.35,0.5,0.7,1")
    args=parser.parse_args();e.initialize(args.python_packages)
    global np,independent
    import numpy as np
    independent=e.module("cube_reference_kernel",e.ROOT/"scripts/mip-weighting/reference.py")
    for case in args.cases.split(","):evaluate(case,args.size,list(map(float,args.roughnesses.split(","))))

if __name__=="__main__":main()
