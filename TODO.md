# TODO

## 当前状态

- [x] Rust workspace、`ibl_core`、`ibl_cli` 基础骨架已建立
- [x] v1 对外契约已冻结到以下文档：
  - `docs/format-spec.md`
  - `crates/ibl_cli/README.md`
  - `packages/loader/README.md`
- [x] 包级公开文档已迁移到对应 README，`docs/` 仅保留共享格式规范
- [x] 阶段路线已并入本文件，不再单独维护独立 roadmap 文档

## 实现前提

- [ ] 所有实现以 `docs/format-spec.md`、`crates/ibl_cli/README.md`、`packages/loader/README.md` 为准
- [ ] 任何会改变公开行为或文件契约的改动，必须同步更新对应 README 或 docs
- [ ] `README.md` 与 `AGENTS.md` 仅保留摘要和链接，不重复展开规格细节

## Phase 1：完成真实 bake 主链路

- [x] 替换当前 placeholder PNG payload，接入真实输出链路
- [x] 实现 HDR 输入读取
- [x] 实现 EXR 输入读取
- [x] 实现 HDR/EXR 转换链路，避免默认强制降级到 8-bit
- [x] 实现 latlong -> cubemap 转换
- [x] 实现 mip chain 生成
- [x] 实现 specular prefilter
- [x] 实现 irradiance 生成
- [x] 实现 BRDF LUT 生成
- [x] 将真实 bake 结果接入 `.ibla` writer，并保持 `docs/format-spec.md` 约定不变

## Phase 1：收紧 CLI 与验证链路

- [x] 确认 CLI 行为、帮助文本、错误输出与 `crates/ibl_cli/README.md` 一致
- [x] 保持 `--size auto` 与 `--encoding auto` 的既定语义
- [x] 为真实 bake 输出补齐 `bake -> validate` 端到端测试
- [x] 补强 `.ibla` 读写、拓扑、chunk range、face ordering 的验证测试
- [x] 为 specular、irradiance、lut 三类输出分别补最小可验证样例

## Phase 2：实现 TypeScript loader（parser-only）

- [x] 在 Rust 输出稳定后创建 `packages/loader`
- [x] 实现 `parseIBLA(buffer)`，遵守 `packages/loader/README.md`
- [x] 落实 `IBLAParseError` 与稳定错误码
- [x] 输出 parser-only 数据结构，不提前加入 PNG decode / RGBD decode / WebGL / WebGPU 上传封装
- [x] 基于 Rust 产物补齐 parser fixtures 与解析测试
- [x] 将 npm 侧切换到根目录 workspace 编排，并移除 `crates/ibl_e2e`
- [x] 将 loader fixture 测试切换为读取仓库内已提交 `.ibla` 产物，不再在 npm 测试里直接调用 `cargo`
- [x] 保持 `packages/loader` 为唯一公开 JS 包
- [x] 移除 three.js 专用 runtime 集成层，保持 JS 主线只剩 parser-only loader
- [x] 使用 `packages/e2e-loader` 承载中立浏览器侧 loader 验收

## 后置事项

- [ ] 在 CLI 稳定、分发方案明确后再创建 `packages/baker`
- [x] 按实际需要补充 `examples/` 与 `scripts/`
- [ ] 为 `packages/e2e-loader` 固化更多 fixture、资产类型与手动浏览器验收覆盖
- [ ] 评估极小 mip 是否需要更轻量 payload 方案；如需支持，再单独设计 codec 元数据
- [x] 与 glTF-IBL-Sampler 做算法对比
- [x] 预计算经纬→cubemap 映射表，同时将映射有效cache，包括旋转计算之类的，避免重复计算
- [x] 当前 diffuse（irradiance）是通过把经纬图转换为立方体面再对面图进行多次方框模糊来近似实现的，应参考 glTF-IBL-Sampler 使用 Lambertian 重要性采样
- [x] 把 computeLod 的 texel_area（omega_p）换成 shader 的经验式（6 * width^2 对于 cubemap），并删除任意 +1 偏移，或者把 +1 变为可配置 lodBias。
- [ ] 补充基于 glTF-IBL-Sampler 参考产物的图像差异回归 fixture 与 RMSE/PSNR 对比测试

## 明确暂不做

- [ ] 不做 UI
- [ ] 不做浏览器端 baking
- [ ] 不做 Rust loader
- [ ] 不做 wasm loader / wasm core
- [ ] 不做 napi / node addon
- [ ] 不做通用多引擎适配层，不抽象 three / Babylon / t3d 等统一运行时接口
- [ ] 不引入额外 container，如 `ktx` / `ktx2`
- [ ] 不在 v1 提前扩展多种 encoding / container 组合
- [ ] 不过早引入插件化或渲染器绑定抽象
