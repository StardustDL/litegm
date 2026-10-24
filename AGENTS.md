# AGENTS.md

给在本仓库工作的 AI agent 的速查说明。目标：**在不破坏既有约定的前提下快速定位代码、
做出改动并验证**。用户文档见 [README](README.md)，开发者指南见
[docs/development.md](docs/development.md)。

---

## 1. 一句话背景

litegm 是一个把 ComfyUI 包装成 OpenAI 兼容多媒体生成 API 的网关（FastAPI + SQLite +
React 管理台）。**所有与具体 ComfyUI 服务器相关的东西（地址、workflow 模板、模型别名、
参数注入点）都在配置文件中声明**；网关代码不应包含任何针对某一台服务器的硬编码。

**配置目录约定（重要）**：仓库里的 `config/` 是提交到 git 的**示例**；真实部署与本地测试
都读 git 忽略的 `.config/litegm.yaml`（`pixi run serve` / `pixi run check` 已指向它）。
改示例配置时同步考虑 `.config/`（本地真实配置，不要提交）。

---

## 2. 先读什么（按任务）

| 任务 | 先读 |
|---|---|
| 改配置/加模型 | `.config/litegm.yaml`（真实）与 `config/litegm.yaml`（示例）、`docs/api.md`、`src/litegm/config.py` |
| 改协议/接口 | `src/litegm/api.py`、`video.py`、`audio.py`、`requests.py`、`errors.py`、`docs/api.md` |
| 改执行流程 | `src/litegm/engine.py`、`workflow.py`、`comfy.py`、`docs/design.md` |
| 改存储/保留 | `src/litegm/storage.py`、`store.py`、`config.py`（`StorageConfig`） |
| 改管理台后端 | `src/litegm/admin.py`、`web/src/api.ts` |
| 改前端 | `web/src/`（先看 `index.css`、`tailwind.config.js`、`icons.tsx`、`ui.tsx`） |
| 改部署 | `Dockerfile`、`docker-compose.yml`、`docs/usage.md` |

---

## 3. 代码地图

```
src/litegm/
  app.py            应用组装（中间件顺序、GZip、静态资源缓存头、异常处理）
  cli.py            serve / check 入口
  config.py         配置模型与校验（唯一配置来源）
  api.py            OpenAI 图像接口 + 统一入口 + models/health/tasks/files
  video.py          OpenAI 异步视频协议（含任务族路由）
  audio.py          音频异步扩展
  requests.py       请求规范化与参数校验（先于任何 GPU 消耗）
  engine.py         任务队列/执行/回退链/取消/进度
  workflow.py       workflow 编译、图片槽位接线、对照 /object_info 的提交前校验
  comfy.py          ComfyUI HTTP 适配
  backends.py       后端注册表（支持热载替换）
  store.py          SQLite 任务/产物/事件/输入图（WAL）
  storage.py        产物落盘、保留清理、签名下载
  admin.py          管理台 API（会话鉴权、任务、缩略图、存储、热载、SSE）
  auth.py           Bearer/Basic 与签名会话
  errors.py         错误层级 → OpenAI 错误形状
  observability.py  结构化日志中间件、/metrics、/health/live|ready
web/src/            管理台（React 19 + TS strict + Tailwind；见 docs/development.md §4）
tests/              单元与集成测试（integration 标记默认跳过）
scripts/            截图、UTF-8 修复、文档链接校验、真实后端验证
docs/               用户/开发者文档与 changelog（每个里程碑必须记录）
```

`config/workflows/` 是实际提交给 ComfyUI 的 API 格式模板（示例随仓库提交；自定义模板放
`.config/workflows/` 并在配置里用 `.config/workflows/...` 引用）。模板里的模型文件名必须与
目标 ComfyUI 上安装的权重一致（各模型的节点接线与参数映射以配置文件为准）。

---

## 4. 必须遵守的规范

1. **配置优先**：新增模型、换 workflow、调约束，改配置即可；只有新协议/新任务类型才改代码。
2. **错误形状**：所有失败都经 `errors.py` 抛出，保持 OpenAI 错误结构与 HTTP 状态映射
   （见 `docs/api.md` 的错误码表）。不要直接返回裸 `HTTPException` 文本。
3. **校验前置**：请求先经 `requests.py`，再经 `workflow.py` 对照后端 `/object_info` 校验；
   校验失败不消耗 GPU。
4. **审计不可省**：任务状态变化、提交、产物、错误都要 `store.add_event` 记录。
5. **热载边界**：只允许 `tasks`/`routing`/`backends` 热载；`server`/`auth`/`storage` 变更
   必须重启并在响应 `restart_required` 中列出。
6. **前端设计系统**：只用 `tailwind.config.js` 的 token（`ink`/`amber`/`jade`/`coral`/
   `azure`/`violet`/`fg`），不要用 `slate`/`sky`；图标只用 `icons.tsx`，不用 emoji；
   UI 文案中文、代码注释英文。
7. **不改无关文件**：不要重排格式、不要顺手改其它模块；新增依赖需有充分理由（当前
   Python 依赖由 pixi 管理，前端无额外依赖）。
8. **密钥不入库**：配置用 `env:LITEGM_MASTER_KEY`；本地 `.env` 已被忽略。

---

## 5. 验证流程（改动后必须执行）

```powershell
# 类型检查与前端构建（pixi 任务会自行准备 PATH）
pixi run -e web web-build
pixi run -e dev -- python -c "import subprocess,sys; sys.exit(subprocess.call([r'.pixi\envs\dev\node.exe', r'web\node_modules\typescript\bin\tsc', '-p', r'web\tsconfig.json', '--noEmit']))"

# 单元测试（不需要 ComfyUI）
pixi run -e dev test-unit

# 配置与 workflow 校验（会连接真实后端）
pixi run check

# 写文件后的编码自检（必须全部 OK）
pixi run -e dev -- python scripts/fix_utf8.py web/src/TaskList.tsx   # 按需列出文件

# 改动文档后校验相对链接
pixi run -e dev -- python scripts/check_doc_links.py README.md AGENTS.md docs
```

- 上面的命令以仓库根目录为工作目录；若要直接调用环境内的可执行文件，用相对路径
  `.pixi\envs\dev\python.exe`、`.pixi\envs\dev\node.exe`（不要写死绝对路径）。
- 集成测试（`-m integration`）会真实占用 GPU，默认只在需要时运行。
- 若启动网关验证：`$env:LITEGM_MASTER_KEY="..."` 后运行
  `pixi run serve`（等价于 `litegm.cli serve --config .config/litegm.yaml --base-dir .`）；
  本地调试可加 `$env:LITEGM_AUTH_DISABLED="1"`。`.config/litegm.yaml` 不存在时先从示例
  `config/litegm.yaml` 复制一份。
- **不要随意重启用户正在运行的服务**；Docker 部署用 `docker compose up -d` 更新，
  UI-only 改动无需重启（静态文件按请求读取）。

---

## 6. 环境陷阱（Windows 上尤其注意）

- `pytest`、`npm` 可能不在 PATH；优先用 `pixi run ...`，或把 `.pixi\envs\dev` 加入 PATH。
- **不要用 PowerShell 的 `-replace`/`Set-Content` 改含中文的文件**：控制台代码页可能截断
  中文字符，产生 `�`（U+FFFD）甚至非法 UTF-8，导致 `tsc` 报 "File appears to be binary"。
  优先用编辑工具的整文件写入；若必须用 PowerShell，使用
  `[System.IO.File]::WriteAllText($p, $t, [System.Text.UTF8Encoding]::new($false))`，
  并在之后跑 `scripts/fix_utf8.py`。
- 运行中的服务不自动重载：后端改动需要重启进程；前端改动重新构建即可。
- Docker Hub / ghcr 可能不可达（国内网络环境）：构建时用
  `$env:NODE_IMAGE = "docker.m.daocloud.io/library/node:22-alpine"`、
  `$env:PIXI_IMAGE = "docker.m.daocloud.io/prefix-dev/pixi:0.83.0"`；默认值是上游镜像，
  海外环境无需设置。
- 容器内没有 `python` 在 PATH（来自 pixi 环境），健康检查/命令需走 `pixi run`。

---

## 7. 常见改动示例

**新增一个图像模型别名**：把 workflow 放进 `config/workflows/`（或部署用的
`.config/workflows/`），在配置文件的 `tasks.image.generate.models` 下加 `alias`/`backend`/
`template`/`inject`/`static`/`constraints`，然后 `pixi run check`。示例配置改动要提交；
`.config/litegm.yaml` 的改动只留在本机。

**给任务详情增加字段**：在 `admin.py` 的 `_task_dict` 增加字段 → `web/src/api.ts` 类型 →
`web/src/TaskDetail.tsx` 展示 → 补 `tests/test_admin_ui_support.py`。

**改进度语义**：`engine.py` 的 `_advance_estimated_progress`；若要接入 `/ws`，
在 `_poll` 中并行监听并在断线后回退到轮询（见 `docs/development.md` §7.3）。

**加一个管理台视图**：`web/src/App.tsx` 增加哈希路由 → `web/src/Shell.tsx` 的 `NAV` →
新视图文件（复用 `ui.tsx`/`components.tsx`/`contract.tsx`）。

---

## 8. 交付要求

- 每个里程碑完成后在 `docs/changelog/` 写记录并在 `docs/changelog/README.md` 索引。
- 提交信息格式 `type(scope): summary`，正文包含动机、关键改动、验证方式。
- 最终回复中说明：改了什么、如何验证、哪些未覆盖/已知限制。
