# AgentFlow Frontend

Vue 3 + Vite + Pinia + Vue Flow。样式使用 CSS 与静态基础重置样式，消息和执行状态通过 REST 轮询同步，保留原生 WebSocket 服务代码用于后续事件接入。

```bash
npm ci
npm run dev
npm run lint
npm test
npm run build
npm run preview
```

Node.js 22.13+（22.x）或 24+。实际使用还需要运行后端；完整启动方式见 [根目录 README](../README.md)。

将 `.env.example` 复制为 `.env` 可覆盖 `VITE_API_BASE_URL`。不要在前端环境变量中保存 API Key。

`src/` 为应用源码，`tests/` 为 Node 测试；已删除未安装 Vitest 依赖的旧测试脚手架与未启用的路由页面。
