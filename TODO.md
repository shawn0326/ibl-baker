# TODO

## 当前状态

- [x] Rust workspace、`ibl_core`、`ibl_cli` 基础骨架已建立
- [x] v1 对外契约已冻结到以下文档：
  - `docs/cli.md`
  - `docs/format-spec.md`
  - `docs/loader-api.md`
- [x] 阶段路线已并入本文件，不再单独维护独立 roadmap 文档

## 实现前提

- [ ] 所有实现以 `docs/cli.md`、`docs/format-spec.md`、`docs/loader-api.md` 为准
- [ ] 任何会改变公开行为或文件契约的改动，必须同步更新对应 docs
- [ ] `README.md` 与 `AGENTS.md` 仅保留摘要和链接，不重复展开规格细节

## Phase 1：完成真实 bake 主链路

- [ ] 替换当前 placeholder PNG payload，接入真实输出链路
- [ ] 实现 HDR 输入读取
- [ ] 实现 EXR 输入读取
- [ ] 实现 HDR/EXR 转换链路，避免默认强制降级到 8-bit
- [ ] 实现 latlong -> cubemap 转换
- [ ] 实现 mip chain 生成
- [ ] 实现 specular prefilter
- [ ] 实现 irradiance 生成
- [ ] 实现 BRDF LUT 生成
- [ ] 将真实 bake 结果接入 `.ibla` writer，并保持 `docs/format-spec.md` 约定不变

## Phase 1：收紧 CLI 与验证链路

- [ ] 确认 CLI 行为、帮助文本、错误输出与 `docs/cli.md` 一致
- [ ] 保持 `--size auto` 与 `--encoding auto` 的既定语义
- [ ] 为真实 bake 输出补齐 `bake -> validate` 端到端测试
- [ ] 补强 `.ibla` 读写、拓扑、chunk range、face ordering 的验证测试
- [ ] 为 specular、irradiance、lut 三类输出分别补最小可验证样例

## Phase 2：实现 TypeScript loader（parser-only）

- [ ] 在 Rust 输出稳定后创建 `packages/loader`
- [ ] 实现 `parseIBLA(buffer)`，遵守 `docs/loader-api.md`
- [ ] 落实 `IBLAParseError` 与稳定错误码
- [ ] 输出 parser-only 数据结构，不提前加入 PNG decode / RGBD decode / WebGL / WebGPU 上传封装
- [ ] 基于 Rust 产物补齐 parser fixtures 与解析测试

## 后置事项

- [ ] 在 CLI 稳定、分发方案明确后再创建 `packages/baker`
- [ ] 按实际需要补充 `examples/` 与 `scripts/`
- [ ] 评估极小 mip 是否需要更轻量 payload 方案；如需支持，再单独设计 codec 元数据

## 明确暂不做

- [ ] 不做 UI
- [ ] 不做浏览器端 baking
- [ ] 不做 Rust loader
- [ ] 不做 wasm loader / wasm core
- [ ] 不做 napi / node addon
- [ ] 不做引擎适配层，不直接返回 three / Babylon / t3d 等运行时对象
- [ ] 不引入额外 container，如 `ktx` / `ktx2`
- [ ] 不在 v1 提前扩展多种 encoding / container 组合
- [ ] 不过早引入插件化或渲染器绑定抽象
