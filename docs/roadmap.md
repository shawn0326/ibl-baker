# Roadmap

## Phase 1

- stabilize the `.ibla` container
- stabilize the single-file texture topology model
- complete deterministic read/write/validate flows
- replace placeholder PNG payloads with real bake outputs

## Phase 2

- implement HDR input loading
- implement HDR/EXR conversion without forcing 8-bit downgrade
- implement latlong to cubemap conversion
- implement specular prefilter and irradiance generation
- implement BRDF LUT generation
- add TypeScript loader parsing and decode support

## Future

- support additional image containers such as `ktx` or `ktx2`
- support higher precision asset outputs such as `rgba16f` and `rgba32f`
- preserve the same logical chunk model across containers
- keep the format renderer-agnostic
