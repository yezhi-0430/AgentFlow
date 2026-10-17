# 上传 GitHub

本地整理完成不代表代码已经发布到 GitHub。上传前需要确定仓库所有者、名称以及公开或私有设置。

## 1. 检查准备内容

```bash
git status --short
python scripts/check_repo.py
git diff --cached --stat
```

确保没有真实密钥、`.env`、`node_modules`、构建结果或缓存。测试中的模拟密钥仅为短占位文本。

## 2. 配置提交身份

如果机器尚未设置 Git 身份，在本仓库配置：

```bash
git config user.name "你的 GitHub 用户名"
git config user.email "你用于 Git 提交的邮箱"
```

可使用 GitHub 设置页提供的隐私邮箱。提交身份不是 GitHub 登录凭据，不要将 Token 填入这些设置。

## 3. 首次提交

整理目录已准备 `main` 分支；如果使用的是不含 Git 元数据的 ZIP，先执行 `git init -b main`。

```bash
git add .
python scripts/check_repo.py
git commit -m "Initial AgentFlow project"
```

## 4. 新建远程仓库并推送

在自己的 GitHub 账号或组织中创建空仓库，选择公开性。不要预先生成 README 或 License，避免与本地内容冲突。

将下面模板替换为你实际的新仓库地址：

```bash
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin main
```

使用 Git Credential Manager、SSH 或自己的常规登录方式认证。不要把 GitHub Token 写进远程 URL、源码或聊天消息。

如果远程仓库已经有内容，先查看其提交历史再决定如何合并，不要直接强制推送。

## 5. 上传后确认

- README 图片与文档链接能打开。
- Actions 中前后端检查通过。
- 仓库不包含本地环境文件、依赖目录、缓存和构建输出。
- 公开前已阅读 [当前限制](limitations.md)。

项目当前没有自动部署配置，推送不会启动公网服务。
