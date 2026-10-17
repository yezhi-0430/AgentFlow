# 本次整理说明

## 保留

- 当前极简黑白前端、工作流执行与删除、模型连接校验、可调高度消息时间线。
- 当前启用的前端 Node 回归测试。
- FastAPI 服务、工作流引擎、模型适配器与代码审查示例。
- 原有 MIT License 与作者声明。

## 清理

- 根目录多份重复的启动、模型、优化和完成情况文档，合并为 README 与 docs 中的专题说明。
- 24 个未接入或过时的脚手架文件：旧 router / views、未启用的 Vitest 测试和配置、未使用的 TypeScript 声明与配置、DebugConsole / SkeletonLoader 及旧通知组合函数、后端空占位包。
- 仅用于基础重置的 Tailwind 构建依赖改为带 MIT 授权的静态样式；升级 Vite 与 ESLint 工具链，清除旧依赖审计记录。
- 未使用的 vue-router、Vue Flow controls / minimap、socket.io-client 等前端依赖。
- 未被代码使用的 python-socketio、anthropic、python-multipart 等后端依赖声明；实际适配器使用的 OpenAI SDK保留。
- 依赖目录、dist、Python 缓存、环境文件和本地临时产物不进入上传目录或源码 ZIP。

原始运行目录完整保留，作为清理前的恢复来源。独立整理目录用于后续 Git 管理与上传。

## 修正

- Python 包发现规则会包含 API / core / adapters 等子包，补齐包内 README。
- 后端详情接口改为读取真实状态字段；客户端配置错误保留原有 400 状态。
- 后端启动日志使用兼容 Windows 终端编码的文本。
- 补齐前端 Dockerfile 与各构建上下文的 dockerignore，修正 Compose 的前端环境变量名。
- 启动器检查依赖、避免端口冲突，只结束自己启动的子进程；不再提供杀死所有 Python / Node 的停止脚本。
- 示例从环境变量读取密钥与模型，补齐 favicon。
- 增加可复现的 ESLint 配置、GitHub Actions、后端 API 冒烟测试与上传前扫描。

## 未扩大范围

执行模式、持久化、鉴权和模型服务的现有限制见 [当前限制](limitations.md)。本次不向原运行目录注入后端改动，也没有替用户调用真实模型或发布远程仓库。
