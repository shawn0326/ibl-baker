# 任务说明

---

## Codex 任务说明

实现一个名为 **`ibl-baker`** 的项目：它是一个**独立于渲染库的 IBL 资产编译器**，用于把 HDR 环境贴图烘焙成新的 `.ibla` 资产格式。

### 必须做什么

#### 1. 固定命名

* 仓库名使用 `ibl-baker`
* CLI binary 使用 `ibl-baker`
* 文件格式扩展名使用 `.ibla`
* 文件 magic 使用 `IBLA`
* npm scope 使用 `@ibltools`
* npm 包名使用：

  * `@ibltools/baker`
  * `@ibltools/loader`
  * `@ibltools/three-loader`

#### 2. 固定仓库结构

```text
ibl-baker/
├─ Cargo.toml
├─ Cargo.lock
├─ README.md
├─ LICENSE
├─ crates/
│  ├─ ibl_core/
│  └─ ibl_cli/
├─ package.json
├─ packages/
│  ├─ baker/
│  ├─ loader/
│  ├─ three-loader/
│  └─ e2e-three/
├─ docs/
├─ examples/
└─ scripts/
```

#### 3. Rust workspace

* 根 `Cargo.toml` 使用 workspace
* workspace 成员只有：

  * `crates/ibl_core`
  * `crates/ibl_cli`

#### 3.1 npm workspace

* 根 `package.json` 使用 npm workspaces
* JS 包统一放在 `packages/`
* 根包只负责脚本编排、lockfile 与工作区管理，不承载业务源码

#### 4. `ibl_core` 必须负责的内容

* HDR 输入读取
* latlong -> cubemap
* specular prefilter
* irradiance
* BRDF LUT
* mip chain
* RGBD encode/decode
* `.ibla` 读写
* inspect / validate / extract 的底层逻辑

#### 5. `ibl_core` 需要提供的顶层 API

* `bake_to_asset(input, options) -> IblAsset`
* `write_asset(path, &asset)`
* `read_asset(path) -> IblAsset`
* `inspect_asset(&asset) -> InspectInfo`
* `validate_asset(&asset) -> ValidationReport`
* `extract_asset(&asset, dir)`

#### 6. `ibl_cli` 必须负责的内容

* 参数解析
* 路径处理
* 调用 `ibl_core`
* 日志输出
* 正确退出码

#### 7. CLI 必须实现的子命令

```bash
ibl-baker bake input.hdr --asset specular --output out.ibla
ibl-baker bake input.hdr --asset irradiance --output out.ibla
ibl-baker bake input.hdr --asset brdf-lut --output out.ibla
ibl-baker inspect out.ibla
ibl-baker validate out.ibla
ibl-baker extract out.ibla --dir ./out
```

#### 8. `bake` 第一阶段只支持这些参数

* `--asset`
* `--size`
* `--irradiance-size`
* `--encoding rgbd`
* `--output`
* `--rotation`
* `--samples`
* `--quality`

#### 9. `.ibla` 文件格式必须固定为

```text
[Header]
[Manifest JSON]
[Chunk Table]
[Binary Chunks]
```

#### 10. `.ibla` Header 至少包含

* `magic = "IBLA"`
* `version`
* `flags`
* `manifest_byte_length`
* `chunk_table_byte_length`
* `reserved`

#### 11. `.ibla` Manifest 至少包含

* `generator`
* `generatorVersion`
* `assetType`
* `encoding`
* `container`
* `range`
* `layout`
* `width`
* `height`
* `mipCount`
* `build`

如果当前资产是 cubemap，还必须包含：

* `faceOrder`

#### 12. `.ibla` Chunk Table 每条记录至少包含

* `mipLevel`
* `face`
* `byteOffset`
* `byteLength`
* `width`
* `height`
* `mimeType`

#### 13. 第一阶段编码策略必须固定

* `encoding = rgbd-srgb | srgb | linear`
* `container = png`
* manifest 顶层不再包含 `pixelFormat` / `colorSpace`
* `build` 至少记录 `rotation`、`samples`、`quality`、`sourceFormat`

#### 14. 第一阶段资产粒度必须固定

* 一个 `.ibla` 文件只表达一种资产
* `specular cubemap + mip chain` 单独一个文件
* `irradiance cubemap` 单独一个文件
* `brdf lut` 单独一个文件

#### 15. 第一阶段必须固定的规则

* cubemap face 顺序固定
* roughness 与 mip 映射固定
* RGBD 还原公式固定
* range 策略固定
* 单图 payload 粒度固定

直接采用以下默认规则：

* `shared maxRange per asset`
* `roughness = mip / (mipCount - 1)`
* `one image payload per chunk record`
* HDR / EXR 转换链路未来不得默认降级到 `rgba8`

#### 16. `@ibltools/loader` 必须提供的能力

* `parseIBLA(buffer)`

并满足以下要求：

* 返回中立数据结构
* 保持 parser-only
* 不直接返回具体渲染引擎纹理对象
* 不在该包内引入运行时上传逻辑

#### 16.1 `@ibltools/three-loader` 必须提供的能力

* 接收 `.ibla` bytes
* 通过 `@ibltools/loader` 解析 cubemap 资产
* 在浏览器中解码 payload
* 返回 three.js 运行时纹理对象
* 作为 three.js 专用集成层独立维护，不反向污染 parser-only loader

#### 17. `@ibltools/baker` 必须提供的能力

* 检测平台
* 定位预编译 Rust binary
* 调用 `ibl-baker`
* 转发 stdout / stderr
* 返回正确退出码

#### 18. 文档必须至少包含

```text
docs/
├─ format-spec.md
├─ cli.md
├─ loader-api.md
├─ three-loader-api.md
```

#### 19. 示例与基础验证必须覆盖

* `.ibla` 读写
* `bake -> validate`
* TS loader 的 parse
* three.js 环境中的浏览器联调验证

---

### 不要做什么

* 不要做 UI
* 不要做浏览器端烘焙
* 不要做 Rust loader
* 不要做 wasm loader
* 不要做 KTX2
* 不要做通用多引擎适配层
* 不要把 three / Babylon / t3d 统一抽象成单一运行时接口
* 不要做 napi / node addon
* 不要做 wasm core
* 不要做进程内 JS binding
* 不要为第一阶段引入多种 encoding / container 组合
* 不要过早抽象成插件系统
* 不要绑定任何特定渲染库
* 不要偏离 `.ibla` 作为“单资产 IBL 文件格式”的定位

---

# 一句话项目描述

**更适合 GitHub 描述：**
A renderer-agnostic IBL asset compiler that bakes HDR environments into portable `.ibla` assets with Rust core, CLI, parser-only TypeScript loader, and dedicated three.js integration.

**更短一点的 README 介绍：**
A standalone, renderer-agnostic IBL compiler for baking HDR environment maps into portable `.ibla` assets.
