# 模块 4: 确定性工具层 + 云 API + Provider 适配

## media_tools.py - FFmpeg 操作（全部 async）

### probe_media

```python
async def probe_media(file_path: Path) -> dict:
    """FFprobe 提取媒体元数据，返回 JSON (format + streams)"""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(file_path)]
    # ... asyncio.create_subprocess_exec ... stdout JSON
```
### generate_proxy
```python
async def generate_proxy(input_path: Path, output_path: Path, width: int = 1280) -> Path:
    """GPU 转码生成低分辨率代理视频"""
    # ffmpeg -hwaccel cuda -i input -vf scale=1280:-2 -c:v h264_nvenc -preset p4 -c:a aac -b:a 128k ...
```
### generate_thumbnails
```python
async def generate_thumbnails(input_path: Path, output_dir: Path, interval_sec: float = 5.0) -> list[Path]:
    """按固定间隔提取缩略图 (320px wide, quality 5)"""
    # ffmpeg -vf fps=1/{interval},scale=320:-2 -q:v 5 thumb_%04d.jpg
```
### extract_audio
```python
async def extract_audio(input_path: Path, output_path: Path) -> Path:
    """提取音频 - PCM 16kHz 单声道 WAV (供 ASR 使用)"""
    # ffmpeg -y -i input -ar 16000 -ac 1 ...
```
### detect_silence
```python
async def detect_silence(audio_path: Path, threshold_db: float = -40, min_duration_ms: int = 500) -> list[dict]:
    """FFmpeg silencedetect 检测静音片段"""
    # ffmpeg -i audio -af silencedetect=noise={threshold_db}dB:d={min_duration/1000} -f null -
    # 解析 stderr 输出 silence_start / silence_end
    # 返回 [{"start_ms": int, "end_ms": int, "duration_ms": int}, ...]
```
## render_tools.py - GPU 渲染
### render_preview
```python
async def render_preview(timeline, input_files, output_path, start_ms=None, end_ms=None) -> Path:
    """低分辨率预览渲染：scale=1280:-2, h264_nvenc p4 cq28, aac 128k"""
    # 如果指定 start/end 使用 -ss/-t 裁剪
```
### render_export
```python
async def render_export(timeline, input_files, output_path) -> Path:
    """高质量最终导出：h264_nvenc p2 cq20, aac 192k, +faststart"""
```
## subtitle_tools.py

### transcribe
- 调用 dashscope Transcription.async_call -> 返回 task_id

### check_transcription_status
- 调用 Transcription.fetch(task=task_id) -> {status, results}

### parse_srt
- 纯本地解析 SRT 格式 -> [{id, start_ms, end_ms, text}]

### cues_to_srt
- 反向：cue 列表 -> SRT 文本

时间戳互换：`HH:MM:SS,ms` <-> 毫秒

## timeline_tools.py - 纯逻辑（无 AI、无 IO）

### validate_edit_plan(plan, timeline) -> list[str]
校验规则：
- 每个 operation 必须有 type
- DELETE_RANGE：需要 start_ms < end_ms
- INSERT_BROLL_OVERLAY：需要 asset_id + duration_ms > 0
- UPDATE_SUBTITLE：需要 cue_id
- SET_VOLUME：0 <= volume <= 2.0
- DELETE_RANGE 之间不能时间重叠

### apply_edit_plan(plan, timeline) -> dict
逐个应用操作：
- DELETE_RANGE：删除范围内 clip，后续 clip 前移
- INSERT_BROLL_OVERLAY：插入到 broll_clips 列表
- SET_VOLUME：记录到 volume_changes 列表

## cloud_api/dashscope_client.py - 百炼 API 统一封装

### API 域名说明
- 配置 `DASHSCOPE_WORKSPACE_ID` 后自动使用专属域名：`https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1`
- 未配置时使用公共域名：`https://dashscope.aliyuncs.com/api/v1`（你可用但官方推荐付费）
- 业务访问需在百炼控制台为主账号授权

### llm_chat_stream (async generator)
```python
async def llm_chat_stream(model, messages, tools=None) -> AsyncGenerator[str]:
    """SSE 流式 LLM 响应。每个 chunk 包含 content/tool_calls/usage"""
    # Generation.call(stream=True, incremental_output=True)
```
### llm_chat_sync
```python
def llm_chat_sync(model, messages, tools=None) -> dict:
    """同步 LLM 调用 (Agent tools 中使用)"""
    # 返回 {"content": str, "tool_calls": list|None, "usage": {...}}
```
### llm_chat_async
```python
async def llm_chat_async(model, messages, tools=None) -> dict:
    """异步版本 - 在 ThreadPoolExecutor 中运行同步调用"""
```
### transcribe_audio
```python
def transcribe_audio(file_url, language_hints=["zh","en"]) -> str:
    """阿里 Paraformer ASR 异步提交，返回 task_id"""
    # Transcription.async_call(model="paraformer-v2", file_urls=[...])
```
### poll_transcription
```python
def poll_transcription(task_id) -> dict:
    """轮询 ASR 结果: {"status": "RUNNING/SUCCEEDED/FAILED", "results": "..."}"""
```
### generate_embeddings
```python
def generate_embeddings(texts: list[str], dimension=1024) -> list[list[float]]:
    """阿里 text-embedding-v3 向量生成"""
    # TextEmbedding.call(model="text-embedding-v3", input=texts, dimension=dimension)
```
## cloud_api/cost_tracker.py - 费用追踪
### 定价表
```python
PRICING = {  # 元/1M tokens
    "qwen-max": {"input": 0.02, "output": 0.06},
    "qwen-plus": {"input": 0.004, "output": 0.012},
    "qwen-turbo": {"input": 0.0005, "output": 0.002},
    "text-embedding-v3": {"input": 0.0007, "output": 0},
    "paraformer-v2": {"per_hour_yuan": 3.6},  # 元/小时音频
}
```
### 核心函数
- `calculate_cost(service, input_tokens, output_tokens, audio_duration_ms)` -> 计算单次调用费用
- `record_usage(project_id, service, ...)` - 写入 CloudAPIUsage 表
- `check_budget(db)` - 检查月/日预算余额
- `ensure_budget(db)` - 超预算则抛出 BudgetExceededError

## embedding_store.py - Chroma 向量检索
基于 chromadb.PersistentClient 的项目级素材向量存储，供 B-roll 搜索使用。

### 配置
- 存储路径：{AICUT_DATA_ROOT}/chroma
- Collection 命名：`project_{project_id}_assets`
- 距离度量：cosine

### 核心函数
```python
def get_collection(project_id: str) -> Collection
def index_asset(project_id, asset_id, description, embedding: list[float]) -> None
def remove_asset(project_id, asset_id) -> None
def search_similar(project_id, query_embedding, top_k=5) -> dict
```
素材入库时机：asset 上传处理完成后，调用 DashScope text-embedding-v3 生成描述向量，upsert 到 Chroma。

search_similar 返回 `{ids, distances, metadatas}` 格式，距离最小相似度 (cosine)。
---
## providers/ - 视频生成 Provider 适配层
### Protocol 定义
```python
class VideoGenProvider(Protocol):
    async def generate(self, prompt: str, **kwargs: dict) -> str: ...  # 返回 task_id
    async def poll_status(self, task_id: str) -> dict: ...  # PENDING/PROCESSING/COMPLETED/FAILED
    async def download_result(self, task_id: str, dest: Path) -> Path: ...
    @property
    def cost_per_generation(self) -> float: ...  # 元/次
```
### Factory
```python
def get_provider(name=None) -> VideoGenProvider:
    # "dashscope" (默认) -> DashScopeVideoProvider
    # "runway" -> RunwayProvider, "pika" -> PikaProvider, "keling" -> KelingProvider
```
配置项：`VIDEO_GEN_PROVIDER` 环境变量，默认`dashscope`
### DashScopeVideoProvider (默认)
- 通义万相视频生成，复用已有的 DASHSCOPE_API_KEY
- 域名：配置 DASHSCOPE_WORKSPACE_ID 后使用专属域名，否则用 dashscope.aliyuncs.com
- submit: POST 异步任务 (X-DashScope-Async: enable) - model=wanx-video-generation-v1
- poll: GET {base}/tasks/{id} -> output.task_status
- download: output.video_url
- cost: ¥0.5/次
- 默认参数：duration=4s, size=1280*720

### RunwayProvider
- BASE_URL: https://api.dev.runwayml.com/v1
- submit: POST /image_to_video - model=gen3a_turbo, duration=5, ratio=16:9
- poll: GET /tasks/{id} - status mapping
- download: 从 output[0] URL 下载
- cost: ¥2.5/次
### PikaProvider
- BASE_URL: https://api.pika.art/v1
- submit: POST /generate - *tyle=realistic, duration=4
- poll: GET /tasks/{id}
- cost: ¥1.5/次

### KelingProvider (可配)
- BASE_URL: https://api.klingai.com/v1
- submit: POST /videos/text2video - model=kling-v1
- poll: GET /videos/text2video/{id} - data.task_status
- download: data.works[0].resource.resource
- cost: ¥2.0/次