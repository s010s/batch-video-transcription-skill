# Batch Video Transcription

[English](README.md) | 简体中文

把一整个视频文件夹整理为带时间码、讲话人分段的文字稿、Word、字幕和可搜索的本地 HTML 页面。可以直接使用本机界面，也可以在 AI agent 中明确调用此 Skill。

- 原视频保持不变，先在本地提取完整时间线音轨。
- 上传前核对素材清单、时长、服务目的地及预计费用。
- 结果默认放在素材目录下的 `Transcription-Export`，运行状态放在独立工作目录。
- 根据已保存的任务 ID 和费用预留恢复，而不是整批重新开始。
- 支持逐视频文稿和合并 Word，不改写识别原文。

**目前仅实现阿里云北京 Fun-ASR。** 其他服务只有扩展接口约定，尚未接入。识别会上传音频并可能收费；备料和导出在本地完成。当前界面和文稿标签为中文，不承诺任意语言识别能力。

## 安装

必需：Python 3.10+、PATH 中的 FFmpeg 与 ffprobe。识别还需要网络和兼容的服务账户；开发测试需要 Node.js。

**不内置 Python 或 FFmpeg。** 先检查已有环境，缺失时再通过官方或可信来源安装。AI agent 必须说明安装范围并取得许可，不静默安装或提权。参见[依赖说明](references/dependencies.md)。

在工具目录中建立独立环境并安装锁定依赖：

macOS / Linux：
```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements-docx.lock
.venv/bin/python scripts/app.py
```

Windows PowerShell：
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements-docx.lock
.\.venv\Scripts\python.exe scripts/app.py
```

也可双击 macOS 的 `Start-Video-Transcription.command` 或 Windows 的 `Start-Video-Transcription.bat`。启动器在创建虚拟环境或安装 Python 依赖前询问；不会自动安装 Python 或 FFmpeg。

## 使用界面

1. **选择素材。** 点击文件夹按钮或输入路径。仅选择不会上传、识别、收费。工作目录应在素材目录外。
2. **准备并核对。** 检查实际数量、时长、预计费用和导出位置。默认导出目录固定为 `Transcription-Export`；已存在时，明确续用原批次，或选择新编号目录，不静默覆盖。
3. **批准本批。** 自行设置总费用上限，批准音频上传，并在本机隐藏输入框填写 API key，勿发到聊天里。预留费用包括未知尝试可能产生的费用，不是实际账单或账户余额。
4. **运行与恢复。** 同次操作可完成提交和收取。已有任务 ID 只查询、不重复提交；临时故障采用有界重试，无法确认的条目保留记录，不抹掉已完成进度。
5. **查看结果。** 打开文稿与搜索页，抽查时间码、专有名词、讲话人和音频。“服务未识别出文字”是正常完成结果，但不等于确认视频没有人声。

服务地址属于高级设置。批次绑定原服务地址，不能为了恢复而随意换地区或换地址重投。

## 密钥与费用

API key 只在运行进程内使用，不写入配置、命令参数、浏览器存储、日志、导出或 Git。操作结束会释放凭据；新操作或进程重启可能需要重输。目前未实现系统钥匙串持久保存。不要分享本机页面链接，也不要通过隧道公开页面。

预算由使用者决定。运行前核当前官方价格，不假设账户有免费额度或某种账单取整方式。未核清的历史费用仍占用预留；提高上限需要明确确认，不会清除历史费用。

如果提交后响应丢失，服务可能已经创建任务；没有服务端幂等支持就不能保证绝不重复。保留该尝试，能核对则核对；若选择重新尝试，需要明确接受可能重复收费，并把两次费用都计入上限。界面要求明确勾选重复费用风险，并设置 0–3 次额外未知提交尝试上限；次数跨重启保留。未勾选时未知条目保持隔离。不要反复点击或删状态文件来强制重试。查询失败与提交结果不明不是一回事。

## 在 AI agent 中使用

此 Skill **必须手动明确调用**。安装相应宿主的副本后，可说：

> 使用 batch-video-transcription 处理这个视频文件夹。先准备并告诉我素材范围和预计费用，暂时不要上传。

Agent 按 `SKILL.md` 检查输入与依赖，并打开本机页面供使用者私密输入 key。Agent 不应读取密钥输入框、包含密钥的截图、请求或进程内存。

从同一份源码生成不同宿主的安装副本：

```sh
python scripts/package_skill.py --host codex --output /path/to/new/codex/batch-video-transcription
python scripts/package_skill.py --host claude --output /path/to/new/claude/batch-video-transcription
```

目标必须是源码目录外的新目录。打包只复制白名单文件，不安装、不发布。

- Codex：`agents/openai.yaml` 设置 `policy.allow_implicit_invocation: false`；用 `$batch-video-transcription` 调用。
- Claude Code：生成副本的 `SKILL.md` 加 `disable-model-invocation: true`；用 `/batch-video-transcription` 调用。
- 其他宿主：配置并验证其手动调用机制；描述里写一句话不能保证所有工具都遵守。

安装位置和兼容边界见[宿主打包说明](references/host-packaging.md)。已测试元数据生成，未验证 Claude 实际加载。

## 导出与移动

HTML 使用原视频和逐片 Word 的相对链接。移动时应搬整个素材文件夹，保留导出子目录与内部结构；只搬 HTML、单独改视频名或移动部分文件会破坏链接。播放还依赖浏览器对视频编码的支持，不会悄悄转码原视频。

从已有本地结果生成合并 Word：

```sh
python scripts/merge_export.py --work /path/to/batch-work
```

按来源相对路径排序，保留文字、时间码及各视频自己的讲话人编号；正常纳入无文字结果，同时列明尚未导出的来源。不调用网络，新建带版本的 `Transcript-Summary.docx` 和来源校验回执，不覆盖已有汇总。不同视频的讲话人编号不代表同一个人。

素材目录只读时，需要明确指定新的可写导出位置；外部目录与 Windows 跨盘链接不保证整包可移动。移动后能浏览，不代表旧批次可以直接绑定到新磁盘继续处理。

## 开发与验证

```sh
python scripts/check_tests.py
```

测试使用合成素材与模拟服务，不产生真实 API 费用。macOS 已用于本地执行；Windows 目前限路径、平台分支与模拟测试，安装、原生选择器、取消及视频播放仍需实机验证。浏览器播放与 Word 分页也需在目标环境检查。测试通过不保证识别准确率或网络可用性。

服务扩展见[接口约定](references/providers.md)。修改恢复、预算、凭据或导出身份校验时应补针对性测试。贡献中不要包含素材、转写正文、密钥、签名 URL、运行批次、环境或本地日志。

## 许可证

[MIT](LICENSE)，适用于本仓库代码，不覆盖第三方运行时、模型服务或用户素材。Python、FFmpeg 构建、编解码器与服务调用另有各自条款。
