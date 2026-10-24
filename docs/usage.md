# litegm 使用说明

litegm 把 ComfyUI 包装成 OpenAI 兼容的多媒体生成 API，并提供任务历史/状态管理台。

## 1. 环境准备

```powershell
# 安装依赖环境（Python 3.15、服务端依赖；dev 环境含测试工具，web 环境含 Node.js）
pixi install -e dev
pixi install -e web
```

密钥通过环境变量提供（配置里写的是 `env:LITEGM_MASTER_KEY`）：

```powershell
$env:LITEGM_MASTER_KEY = "<你的 master key>"
```

## 2. 配置

**仓库里的 `config/` 只是示例，会提交到 git；真实部署与本地测试都从 `.config/` 读取配置**
（`.config/` 已被 `.gitignore` 忽略）。首次使用先复制示例：

```powershell
New-Item -ItemType Directory -Force .config | Out-Null
Copy-Item config/litegm.yaml .config/litegm.yaml
```

然后编辑 `.config/litegm.yaml`：

* `backends[]`：ComfyUI 服务器地址、并发、超时（不写死任何服务器）。
* `tasks.image.generate` / `tasks.image.edit`：模型别名、workflow 模板、参数注入点、图片槽位、回退链。
* `auth`：`username` + `master_key`（API 与后台共用同一把 key）。
* `server.sync_timeout_s`：同步请求最长等待时间。

模板路径有两种写法：

* `config/workflows/...`：解析到仓库自带的示例模板（`.config/` 下没有时回退到仓库根目录）。
* `.config/workflows/...`：解析到 `.config/` 下你自己的模板。仓库未收录的模型（例如
  Z-Image 系）需要这样引用；模板缺失时 `check`/启动会直接报错，所以要么补上模板，要么删掉
  对应别名。

改完先校验（会连到后端，用真实节点 schema 校验每个 workflow）：

```powershell
pixi run check
```

## 3. 启动

```powershell
pixi run serve            # 读取 .config/litegm.yaml，监听配置中的 host/port（默认 127.0.0.1:8080）
```

也可直接指定路径：`litegm serve --config <path> --base-dir .`。

管理台：<http://127.0.0.1:8080/admin/>（用配置中的用户名 + master key 登录）。

## 4. 调用 API

API key 就是 `master_key`，可直接用官方 OpenAI SDK：

```python
from openai import OpenAI

client = OpenAI(api_key="<你的 master key>", base_url="http://127.0.0.1:8080/v1")

r = client.images.generate(
    model="qwen-image-2.1-turbo",
    prompt="一只红色的狐狸坐在金色秋天的草地上，柔和晨光，浅景深",
    size="1024x1024",
    extra_body={"seed": 20261023},
)
```

图片编辑（multipart，`image` 可多张）：

```python
with open("person.png", "rb") as fh:
    r = client.images.edit(
        model="qwen-image-2.1-turbo-edit",
        image=fh,
        prompt="给 <image1> 里的人换上一件红色羽绒服，保持脸部、发型、姿势和背景不变",
    )
```

可用别名见 `GET /v1/models`；健康检查见 `GET /v1/health`。

### 内置别名（示例配置）

| 别名 | 用途 | 说明 |
|------|------|------|
| `qwen-image-2.1-turbo` / `-pe` | 文生图 + 图像编辑 | 默认模型，8 步蒸馏；`-pe` 启用提示词增强（较慢）。同时也是示例配置里的通用图像模型 |
| `qwen-image-2.1` | 文生图 | base 权重，25 步，可用 `steps` 字段调整 |
| `moss-image` | 文生图 | MOSS Image，尺寸需 16 的倍数，支持负面词 |
| `qwen-image-2.1-turbo-edit` / `-pe` | 图片编辑 | 默认编辑；`-pe` 启用编辑提示词增强 |
| `qwen-image-2.1-edit` | 图片编辑 | base 权重编辑，单图/多图均可 |

别名完全由配置决定，增删模型只需改 `.config/litegm.yaml`，无需改代码。

### 通用图像模型（一个别名同时做文生图与图生图）

在配置 `routing.unified_image_models` 中声明后，同一别名可同时用于两种场景，网关按是否带图自动路由。示例配置把 `qwen-image-2.1-turbo` 声明为通用模型：

```bash
# 文生图（JSON）
curl -s http://127.0.0.1:8080/v1/images \
  -H "Authorization: Bearer $LITEGM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"model":"qwen-image-2.1-turbo","prompt":"一只红色狐狸坐在秋日草地上","size":"1024x1024"}'

# 图生图/编辑（multipart，带图即路由到编辑）
curl -s http://127.0.0.1:8080/v1/images \
  -H "Authorization: Bearer $LITEGM_MASTER_KEY" \
  -F "model=qwen-image-2.1-turbo" -F "prompt=把 <image1> 的背景换成夕阳天空，主体保持不变" \
  -F "image=@person.png"
```

OpenAI SDK 也可直接使用 `client.images.generate` / `client.images.edit`，并把 `model` 设为通用别名。
通用别名由你自行决定：在 `tasks.image.generate` 与 `tasks.image.edit` 下各声明一个同名变体，
再在 `routing.unified_image_models` 中引用即可。

## 5. 行为说明

* 图像接口与 OpenAI 一样是**同步**的；超过 `sync_timeout_s` 返回 504，并带
  `X-Litegm-Task-Id` 响应头，任务会继续执行，可用 `GET /v1/tasks/{id}` 取回。
* `mask` 在 v1 不支持（返回 `unsupported_parameter`）。
* 编辑模型的输出画布跟随输入图，`size` 仅作建议。
* 每个任务都会记录实际提交的 workflow 快照与事件，管理台可查看。

### 5.1 把服务接入 agent 环境

网关自带面向 agent/开发者的发现文档，**拿到链接即可自助接入**：

| 端点 | 用途 |
|---|---|
| `GET /llms.txt` | Markdown 接入说明，内容按当前生效配置生成（真实别名、尺寸/时长约束、鉴权、curl 与 SDK 示例、异步轮询、错误码） |
| `GET /swagger-ui`（`/docs` 同义） | Swagger UI；点 Authorize 填入 master key 后可直接在浏览器试调用 |
| `GET /openapi.json` | OpenAPI 3 文档，可据此生成客户端或工具定义 |

三者均无需 Bearer，响应中也不含 master key。接入方式：

1. 把 `http://<网关地址>:8080/llms.txt` 作为上下文交给 agent（例如在 Claude Code、
   Cursor 等工具中直接粘贴该链接，或写入项目说明），agent 会先读它，再调用
   `GET /v1/models` 确认别名。
2. 把 `base_url=http://<网关地址>:8080/v1` 与 master key 配置为该 agent 的 OpenAI 兼容
   客户端（很多 agent 框架支持自定义 OpenAI base_url）；需要工具定义时用
   `/openapi.json` 导入。
3. 管理台顶栏的「API 文档」与「llms.txt」按钮可打开文档或一键复制接入链接。

安全提示：`/llms.txt`、`/swagger-ui` 只暴露结构与别名，不暴露密钥；**master key 仍需
单独提供给 agent**（等同于全部生成权限）。公网部署时建议仅在反向代理层放行
`/llms.txt`、`/swagger-ui`、`/openapi.json`，其余 `/v1/*` 继续要求 Bearer。

## 6. 测试

```powershell
pixi run -e dev test-unit          # 单元测试（不需要 ComfyUI）
pixi run -e dev test-integration   # 集成测试（真实生成，较慢）
```

## 7. 前端开发

```powershell
pixi run -e web web-install
pixi run -e web web-build          # 产物在 web/dist，由网关在 /admin 托管
```

开发期可单独跑 `npm --prefix web run dev`（Vite 反代到 127.0.0.1:8080）。

管理台包含：任务历史（搜索/状态与类型过滤/导出 CSV、JSON/删除）、任务详情（输入图、
图片内联预览、视频 `<video>` 播放、音频 `<audio>` 播放、workflow 快照与事件）、
Playground（按任务类型动态生成表单，可直接提交图像/视频/音频任务并预览产物）、
系统页（后端健康、队列、存储用量与清理、配置热载）。

## 8. v3 运维功能

### 8.1 存储治理

`.config/litegm.yaml` 的 `storage` 段：

```yaml
storage:
  root: ./data
  artifact_ttl_days: 30          # 成功任务产物保留天数
  failed_retention_days: 60      # 失败/取消任务保留更久，便于排查（缺省为 TTL 的 2 倍）
  max_bytes: 53687091200         # 可选：磁盘上限，超出后按 LRU 清理
  sweep_interval_s: 900          # 后台清理周期
```

后台按周期执行；也可在管理台"系统"页点"立即清理存储"，或调用
`POST /admin/api/storage/sweep`。删除任务（`DELETE /admin/api/tasks/{id}`）会硬删产物与
输入文件并软删记录（保留审计）。

### 8.2 可观测性

* 结构化访问日志：每条请求一行 JSON（`request_id`、`method`、`path`、`status`、
  `duration_ms`、`task_id`）。
* `GET /metrics`：Prometheus 文本格式（请求/任务计数与耗时、队列深度、后端在线状态、
  磁盘用量），无额外依赖。
* `GET /health/live`（存活）与 `GET /health/ready`（就绪，检查后端）分离。

### 8.3 配置热载

改完 `tasks`/`routing`/`backends` 后，在管理台"系统"页点"热载配置"，或：

```powershell
curl -X POST http://127.0.0.1:8080/admin/api/config/reload -b cookies.txt
```

校验失败会回滚（保留旧配置）；`server`/`auth`/`storage` 的变更需要重启，响应里的
`restart_required` 会列出。进行中的任务保持提交时的配置快照。

### 8.4 免认证模式（仅限本地）

```powershell
$env:LITEGM_AUTH_DISABLED = "1"     # 或配置 auth.enabled: false
pixi run serve
```

API 与 `/admin` 均不再校验。共享或公网部署**不要**关闭。

### 8.5 进度语义（v3 已知限制）

ComfyUI 的 `/queue` 无法给出步级进度。v3 中长任务的进度是**按阶段与耗时的估算值**
（生成阶段在 20–88% 之间随耗时推进，下载与完成阶段给出真实值），失败/取消的任务保留
到达过的进度。接入 ComfyUI `/ws` 的真实步级进度推迟到 **v4**。

## 9. Docker 部署

```powershell
# 1) 在仓库根目录准备两个目录（都在 .gitignore 中，不会提交到 git）：
#    .env                 → LITEGM_MASTER_KEY=<你的 master key>
#    .config/litegm.yaml  → 你的真实配置（可先复制示例：Copy-Item config/litegm.yaml .config/）

# 2) 启动
docker compose up -d --build
```

`docker-compose.yml` 挂载 `./.config`（真实配置）与 `./data`，容器以
`/app/.config/litegm.yaml` 启动；`LITEGM_MASTER_KEY` 从环境变量或 `.env` 读取。对外与
容器内端口均为 `8080`，通过 `--host/--port` 覆盖，无需改动本地 config。
镜像分两阶段：Node 阶段构建管理台，pixi 阶段按 `pixi.lock` 安装运行时环境（Python 3.15，
与本地一致），以非 root 用户运行，内置经 `pixi run` 执行的 `/health/live` 健康检查。
镜像内还带有示例 `config/`，供配置里 `config/workflows/...` 这类路径回退使用。
运行时环境包含 `ffmpeg`/`ffprobe`（conda-forge），因此视频产物在容器内即可截取首帧缩略图，
无需另行安装系统包。

容器入口 `docker-entrypoint.sh` 会先以 root 启动，把 `./data`、`./.config` 与 pixi 缓存目录
的属主修正为 UID 10001，再降权执行网关。宿主机上由 root 创建的 `data/` 目录（例如之前用
`docker run` 跑过一次留下的）否则会让 SQLite 以 UID 10001 打开时报
`unable to open database file`。若希望容器从一开始就以非 root 运行，可设置
`user: "10001:10001"`，并自行保证宿主机目录属主匹配：

```bash
sudo chown -R 10001:10001 ./data ./.config
```

### 首次部署：先修正 `./data` 属主

**这是首次部署最常见的一步失败**。容器以 UID 10001 运行，而 bind-mount 会把宿主机的
`./data` 原样覆盖到 `/app/data`，镜像构建阶段的 `chown` 对它无效。若宿主机目录属主不是
10001（由 root 创建、或 docker 自动创建），启动时就会在 `TaskStore` 初始化处失败：

```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) unable to open database file
  ... src/litegm/app.py, TaskStore(config.storage_root() / "litegm.db")
```

`docker-entrypoint.sh` 在以 root 启动时会尝试自动修正，但若容器以非 root 启动（compose
`user:` 覆盖、或 `setpriv` 在基础镜像中不可用），这一步不会生效，容器会反复
`exited with code 2 (restarting)`。此时在宿主机上手动修正即可（目录在 `.gitignore` 中，
不涉及仓库内容）：

```bash
cd ~/envs/litegm
mkdir -p data .config
sudo chown -R 10001:10001 data .config
docker compose up -d
```

排查时可确认容器内的实际属主：

```bash
docker run --rm --entrypoint sh -v "$PWD/data:/app/data" litegm:latest \
  -c 'id; ls -ld /app/data; touch /app/data/.probe && echo WRITABLE || echo NOT-WRITABLE'
```

若 Docker Hub 拉取受限，可用镜像加速器构建：

```powershell
$env:NODE_IMAGE = "docker.m.daocloud.io/library/node:22-alpine"
docker compose up -d --build
```

## 10. 管理台（v4 改版）

管理台为深色"暗房"风格，包含概览（运行脉搏、队列、存储、最近出片、失败摘要）、
任务库（画廊/表格双视图、筛选、批量重试/删除/导出）、任务详情（产物灯箱、输入输出对照、
执行时间线、workflow 快照）、创作台（按模型约束生成表单、参考图托盘、实时进度）与
系统面板（后端健康、队列、存储、路由、热载、清理）。

键盘操作：`Ctrl/Cmd+K` 命令面板、`g` 后接 `o`/`t`/`s`/`y` 跳转、`?` 查看快捷键、
灯箱内 `←`/`→` 切换。窄屏下导航栏变为底部栏。

缩略图接口（`/admin/api/artifacts/{id}/thumb`、`/admin/api/tasks/{id}/inputs/{idx}/thumb`）
对图片生成缓存缩略图；视频在 `ffmpeg` 可用时（容器镜像与本机 pixi 环境均已内置）自动截取
首帧，否则显示占位帧。


