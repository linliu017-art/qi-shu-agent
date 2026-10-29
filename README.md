# qi-shu-agent

本机单人试用的 AI 工作助手：自然语言交办任务，读取资料，追问关键问题，生成、修改和确认草稿。项目处于开发和业务验收阶段。

## 已有能力

- 文本资料与任务持久化、关键问题追问、草稿确认与版本追溯。
- 后端支持 TXT、Markdown、DOCX、XLSX、PPTX 资料读取及基础 Word、Excel、PPT 成果生成。
- 当前预览页面只支持 TXT / Markdown 上传；Office 能力可通过后端接口调用，正式前端待开发。
- 使用 DeepSeek 兼容接口；调用模型会产生费用。

## 本地运行

需要 Python 3.12、Node.js 24。项目仅供本机单人试用，未实现正式多用户身份隔离，请勿直接暴露到公网。

1. 在 backend 目录创建虚拟环境并安装依赖：`python3.12 -m venv .venv`，执行 `.venv/bin/pip install -r requirements.txt`。
2. 参考 backend/.env.example 设置服务端环境变量 MODEL_API_KEY、MODEL_BASE_URL、MODEL_NAME，密钥不要提交。
3. 在 backend 目录加载环境变量后运行 `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18781`。
4. 在 frontend 目录执行 `npm ci` 和 `npm run dev -- --hostname 127.0.0.1 --port 13081`，打开 http://127.0.0.1:13081 。

接口文档：http://127.0.0.1:18781/docs 。上传和模型调用须遵守数据授权与隐私要求。

## 测试

项目根目录执行 `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests -q`；前端目录执行 `npm run lint` 和 `npx tsc --noEmit`。运行评测脚本前请创建 `data/evaluation` 目录。scripts/evaluation 中真实模型脚本会产生费用，必须显式设置 EVAL_APPROVED=yes 并配置服务端环境变量。

## 许可和来源

采用 MIT 许可证，保留工具包原有版权声明。backend/app/skill_references 保存业务指引所用 Skill 参考文件及来源、哈希，见 manifest.json。
