# 国内外研究综述 · Zeabur 部署指南

本文档教你如何将本项目部署到 [Zeabur](https://zeabur.com) 云端，让更多人访问。

---

## 一、前置准备

### 1. 代码已就绪

项目已完成云端适配：

- `app.py`：支持 `PORT` 环境变量，云端自动绑定 `0.0.0.0`
- `requirements.txt`：已添加 `gunicorn`，Zeabur 会用它作为生产服务器

### 2. 准备 Git 仓库

Zeabur 通过 Git 部署，请先将项目推送到 GitHub / GitLab / Gitee：

```bash
cd "c:\Users\10196\Desktop\国内外研究和综述"
git init
git add .
git commit -m "初版：国内外研究综述生成器"
git branch -M main
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

> ⚠️ `.env` 已在 `.gitignore` 中，不会上传。**切勿**把 API 密钥提交到 Git。

---

## 二、在 Zeabur 上部署

### 步骤 1：注册并登录

1. 打开 [https://zeabur.com](https://zeabur.com)
2. 使用 GitHub / GitLab 账号登录（推荐 GitHub，方便授权仓库）

### 步骤 2：创建项目并导入代码

1. 点击 **「Add new project」** 或 **「新建项目」**
2. 选择 **「Deploy your source code」**（从源代码部署）
3. 选择 **GitHub**（或你使用的平台），找到你的仓库
4. 点击 **「Import」** 导入

### 步骤 3：配置服务

Zeabur 会自动识别 Python Flask 项目，一般无需额外配置。若需要自定义：

- **启动命令**：默认会运行 `python app.py` 或使用 Gunicorn
- **端口**：Zeabur 自动设置 `PORT`，应用已支持

### 步骤 4：配置环境变量（重要）

在项目或服务页面找到 **「Variables」/「环境变量」**，添加以下变量：

| 变量名 | 说明 | 是否必填 |
|--------|------|----------|
| `QWEN_API_KEY` | 通义千问 API 密钥（阿里云 DashScope） | ✅ 必填 |
| `QWEN_BASE_URL` | API 地址，默认：`https://dashscope.aliyuncs.com/compatible-mode/v1` | 可选 |
| `QWEN_INTENT_MODEL` | 意图解析模型，如 `qwen-max` | 可选 |
| `QWEN_WRITING_MODEL` | 撰写模型，如 `qwen-max` | 可选 |
| `OPENALEX_EMAIL` | OpenAlex 邮箱（进入 Polite Pool，可选） | 可选 |
| `FETCH_POOL_SIZE` | 候选池条数，默认 `50` | 可选 |
| `TOP_K_EN` | 英文 TOP 数量，默认 `15` | 可选 |
| `TOP_K_ZH` | 中文 TOP 数量，默认 `5` | 可选 |
| `USE_AI_SELECTION` | 是否用 AI 筛选文献，`true` / `false` | 可选 |

**至少需要设置 `QWEN_API_KEY`**，否则应用会报错。

### 步骤 5：部署与访问

1. 点击 **「Deploy」** 开始部署
2. 等待构建与启动完成（约 1–3 分钟）
3. Zeabur 会分配一个域名，如 `你的项目.zeabur.app`
4. 点击域名即可在浏览器中访问

---

## 三、本地验证（可选）

部署前可在本地模拟生产环境：

```bash
cd "c:\Users\10196\Desktop\国内外研究和综述"
set PORT=5000
python app.py
```

或在 PowerShell：

```powershell
$env:PORT=5000
python app.py
```

然后访问 `http://localhost:5000` 确认功能正常。

---

## 四、常见问题

### 1. 部署后访问 500 或白屏

- 检查环境变量是否配置正确，尤其是 `QWEN_API_KEY`
- 在 Zeabur 控制台查看 **「Logs」** 是否有报错

### 2. API 请求失败

- 前端使用相对路径 `/api`，部署在同一域名下无需修改
- 若使用自定义域名，确认已正确绑定

### 3. 构建失败

- 确认 `requirements.txt` 中依赖完整
- 查看 Zeabur 构建日志中的具体错误信息

### 4. 密钥安全

- 不要将 `QWEN_API_KEY` 等写入代码或提交到 Git
- 只在 Zeabur 的环境变量中配置

---

## 五、获取通义千问 API 密钥

1. 打开 [阿里云 DashScope](https://dashscope.aliyun.com/)
2. 登录阿里云账号
3. 在控制台创建 API Key
4. 将密钥填入 Zeabur 的 `QWEN_API_KEY` 环境变量

---

部署完成后，你的应用会有一个公网地址，任何人通过浏览器即可访问使用。
