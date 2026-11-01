# qi-shu-agent

启枢是一个本机单人试用的 AI 工作助手：自然语言交办任务，读取参考资料，追问关键问题，并生成、修改和确认草稿。项目仍处于开发和业务验收阶段。

## 已有能力

- 上传和管理 TXT、Markdown、DOCX、XLSX、PPTX 资料；任务关联资料的具体版本并可查看提取内容。
- 任务状态与草稿持久化，支持补充要求、停止、章节恢复、草稿确认和版本对比与恢复。
- 成果库支持独立阅读、查看来源和版本、下载 Word 或 Markdown；结构化 Excel 和 PPT 成果可下载对应格式。
- Notion 风格工作台适配桌面和窄屏，外框占满屏幕，长内容在内部滚动。
- 创建任务支持持久化请求标识，防止相同请求在重试时重复执行。
- 文档可视化编辑、Excel 行列编辑、PPT 幻灯片编辑与预览，以及成果版本保存和恢复。
- 通过 DeepSeek 兼容接口调用模型；调用模型会产生费用。

复杂 Office 原文件的页面内编辑和 PPT 原文件预览正在开发：实验接入默认关闭，已完成部分虚构文件联调，动画、母版、跨软件保真、服务部署和完整无损验收尚未完成，不应视为已支持所有复杂格式。正式多用户权限仍未完成。模型生成完成不代表草稿已由用户确认。详见 [复杂 Office 编辑开发进度](docs/复杂Office编辑-开发进度.md)。

## 本地运行

需要 Python 3.12、Node.js 24。项目仅供本机单人试用，尚未实现正式多用户身份隔离，请勿直接暴露到公网。

1. 在 `backend` 目录执行 `python3.12 -m venv .venv` 和 `.venv/bin/pip install -r requirements.txt`。
2. 参考 `backend/.env.example` 配置服务端环境变量 `MODEL_API_KEY`、`MODEL_BASE_URL`、`MODEL_NAME`；不要提交密钥。
3. 加载环境变量后，在 `backend` 目录执行 `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18781`。
4. 在 `frontend` 目录执行 `npm ci` 和 `npm run dev -- --hostname 127.0.0.1 --port 13081`，打开 http://127.0.0.1:13081。

接口文档：http://127.0.0.1:18781/docs。上传资料及模型调用应先取得相应的数据使用授权。

## 测试

在项目根目录运行 `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests -q`。在 `frontend` 目录运行 `npm test`、`npm run lint`、`npx tsc --noEmit` 和 `npm run build`。不要让开发服务与生产构建同时使用同一 `.next` 目录。

`scripts/evaluation` 中的真实模型脚本会产生费用，运行前需明确费用与数据授权，创建 `data/evaluation`，并设置 `EVAL_APPROVED=yes` 和服务端环境变量。

## 许可和来源

采用 MIT 许可证。`backend/app/skill_references` 包含业务指引所用 Skill 参考文件及来源和哈希，详见 `manifest.json`。
