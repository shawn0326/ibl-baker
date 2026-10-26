# Runtime integration contract

This document describes consumption of the current baker's outputs. IBLA v1,
BC6H UFLOAT + zstd KTX2, parser APIs and the default complete specular chain stay
unchanged. File layout remains defined by the [IBLA specification](format-spec.md)
and [CLI KTX2 profile](../crates/ibl_cli/README.md#ktx2-output).

## Choose a bake

For a BC6H-capable runtime, start with an explicit power-of-two size and the
default medium quality:

```sh
ibl-baker bake environment.hdr --out-dir out --output-format ktx2 --size 256
```

Use `--quality low` for faster iteration. Increase `--size` for more directional
detail or `--quality` for a larger integration budget when a visible defect
justifies the cost. Size affects GPU storage; quality and samples affect offline
work, without adding runtime texture queries. Keep `--samples` at its default
1024 unless controlling a specific budget: it is an upper request, not a promise
that every texel uses that many samples. Use `both` when both delivery formats
are required; the two encodings share the cubemap bake.

Leave `--specular-min-size auto` for the complete chain. A different minimum
changes the baked roughness nodes; it is not a general shader-speed control.
Use explicit sizes for repeatable batch storage budgets: `--size auto` follows
the input dimensions and can select a large texture. NPOT files remain valid,
but container validity does not guarantee compressed GPU upload on every backend.
For example, [WebGL BPTC](https://registry.khronos.org/webgl/extensions/EXT_texture_compression_bptc/)
imposes block-dimension restrictions. Power-of-two sizes such as 128, 256 or 512
avoid that portability issue.

The BRDF LUT is independent of environment contents and rotation. Reuse one LUT
for the same baker/model and quality/sample settings. To bake subsequent
environments without regenerating it:

```sh
ibl-baker bake next.hdr --out-dir next --output-format ktx2 --size 256 --target specular --target irradiance
```

`--rotation` is in **degrees** and is already applied during baking.

## Asset meanings

| Output | Stored meaning | Runtime use |
| --- | --- | --- |
| Specular cubemap | GGX prefilter, perceptual roughness `r = mip / (mipCount - 1)`, with `alpha = r*r` | Reflection direction and explicit roughness LOD |
| Irradiance cubemap | Normalized Lambert convolution, `E / pi` | Normal direction at LOD 0; multiply by diffuse albedo without another division by pi |
| BRDF LUT PNG | Linear RG coefficients `A, B` for Schlick Fresnel and correlated Smith GGX visibility | `prefiltered * (F0 * A + B)` |

The application assigns these roles. Neither the general IBLA cubemap topology
nor the narrow KTX2 profile carries an asset-role tag; a one-level cubemap alone
cannot identify irradiance. The CLI's filenames provide the normal packaging
convention. Material energy sharing, metallic response, occlusion and exposure
belong to the renderer.

LUT columns increase with `NdotV`, and rows increase with perceptual roughness.
Texel centers are `(index + 0.5) / 256`. Upload it as **linear data**, sample RG
with bilinear filtering and clamped addressing, and preserve row 0 as low
roughness. Do not apply sRGB conversion. Its resolution is fixed at 256x256;
the PNG stores quantized coefficients, not an environment image.

## Directions and levels

Face order is `px, nx, py, ny, pz, nz`. With face coordinates `u, v` in `[-1, 1]`,
where image columns and rows increase with `u, v`, the unnormalized directions are:

| Face | Direction |
| --- | --- |
| px | `(1, -v, -u)` |
| nx | `(-1, -v, u)` |
| py | `(u, 1, v)` |
| ny | `(u, -1, -v)` |
| pz | `(u, -v, 1)` |
| nz | `(-u, -v, -1)` |

Transform normals, reflections and both cubemaps consistently into this basis.
Any engine-specific axis or image-row conversion belongs in its adapter; do not
apply a second bake rotation or assume that all engines need the same flip.

Upload every supplied face and level. Cache the actual level count at load time:

```text
maxLod = actualLevelCount - 1
lod = clamp(perceptualRoughness, 0, 1) * maxLod
```

Use the **linear perceptual roughness**, not `r*r`, in this LOD expression.
Configure linear filtering within and between levels and the accessible mip
range to match the uploaded levels. Disable automatic mip generation. Truncated
chains are freshly baked over the full roughness range; cropping an existing
chain or deriving its count from base width changes the mapping. One level uses
LOD 0 and provides no specular roughness variation.

For resident linear textures, the material shader can use a fixed query pattern:

```glsl
float r = clamp(perceptualRoughness, 0.0, 1.0);
float nv = clamp(dot(N, V), 0.0, 1.0);
vec3 R = reflect(-V, N);
vec3 prefiltered = textureLod(specularCube, R, r * specularMaxLod).rgb;
vec2 ab = texture(brdfLut, vec2(nv, r)).rg;
vec3 specular = prefiltered * (F0 * ab.x + ab.y);
vec3 diffuseInput = textureLod(irradianceCube, N, 0.0).rgb;
```

This assumes normalized directions in the asset basis, V pointing from surface
to viewer, and LUT row 0 uploaded at texture coordinate zero. The specular path
has one cubemap query and one LUT
query; the optional diffuse path adds one cubemap query. Hardware filtering can
access several texels/levels internally. No file parsing, decompression, CPU
roughness search or per-roughness rebaking belongs in the frame loop.

## Load once, query on the GPU

Both parsers accept an `ArrayBuffer` or a `Uint8Array` view, including a nonzero
input offset. With ArrayBuffer or same-realm Uint8Array/Node Buffer inputs, encoded
payloads are views into the input backing buffer without copying the large
payload. Metadata and view objects are still allocated. Treat
the source bytes as immutable; retaining one view retains its backing buffer.
Transfer/detach ownership only when the receiving worker owns the subsequent
parse/decode work. Release file and decode buffers after upload completion when
the integration no longer needs them.

For KTX2, parse once and zstd-decompress each level **once**, verifying the result
against `uncompressedByteLength`. Each face offset is relative to that decompressed
level. Use `subarray` views for its six BC6H faces, upload compressed blocks, and
let the GPU decode them. zstd is a loading/transport step, not the GPU format.
Check BC6H capability before selecting this route; WebGPU uses the optional
[`texture-compression-bc` feature](https://gpuweb.github.io/gpuweb/#texture-compression-bc).
An unsupported backend needs a decode/upload fallback in its adapter.

For IBLA, PNG-decode each chunk once with its stored encoding and unassociated
alpha preserved. `srgb` RGB must be linearized once; `linear` RGB must not be
linearized. For `rgbd-srgb`, linearize RGB and divide by the linear alpha `D`.
Hardware sRGB conversion can perform the RGB step, but must not be applied twice.
Decoding a hardware-filtered RGBD sample is a fast approximation: interpolating
RGB and D before division is not filtering reconstructed HDR texels. If that
causes visible bleed or banding, decode to a filterable linear texture at load
time. The packed RGBD route remains available to integrations accepting that
approximation; its PNG alpha is data, not transparency.

Budget GPU storage separately from download size. For one BC6H cubemap, the raw
block payload is `6 * sum(ceil(width_mip / 4)^2 * 16)` bytes. A complete 256 chain
uses 524448 block bytes, compared with 4194288 texel bytes in RGBA16F. These exclude
driver alignment and allocation overhead. zstd file size is not resident GPU size.
Process one decompressed level at a time when the upload API permits it.

## Acceptance priorities

Current engineering priorities are stable output and sampling contracts, simple
parameters, visible correctness and efficient bake/load/query paths. Keep small
deterministic checks for finite values, constant-environment normalization,
directions, topology, encoding and LUT semantics. Check representative indoor,
outdoor and strong-sun material views with fixed exposure, camera and material
for obvious seams, incorrect orientation, energy shifts and roughness transitions.

Converged integration errors remain useful diagnostics. The earlier research
15%/10% improvement targets and individual tiny subgroup differences are not
universal release gates. Algorithm changes still need visual evidence and
performance measurements; a visible gain or correctness fix must justify extra
work. Retain the 2x bake-time ceiling for new algorithm candidates, preferring
lower cost when the visual result is equivalent. Do not add public knobs or
runtime queries merely to optimize a numerical score. Existing precision studies
remain historical evidence; broader precision research is deferred.
