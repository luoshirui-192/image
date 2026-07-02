# 发布到 GitHub

## 1. 在 GitHub 创建空仓库

1. 打开 https://github.com/new  
2. 仓库名建议：`image-path-db` 或 `图像路径式数据库管理系统`（英文更省事）  
3. **不要**勾选 “Add a README”（本地已有）  
4. 创建后记下仓库地址，例如：  
   `https://github.com/你的用户名/image-path-db.git`

## 2. 本地首次推送（已完成 git init 后）

在项目根目录执行：

```powershell
# 查看将要提交的文件（不应出现 .env、node_modules、backend/.env）
git status

# 关联远程仓库（换成你的地址）
git remote add origin https://github.com/你的用户名/image-path-db.git

# 推送到 GitHub
git branch -M main
git push -u origin main
```

若 GitHub 要求登录，使用 **Personal Access Token** 作为密码，或安装 [GitHub CLI](https://cli.github.com/) 后执行 `gh auth login`。

## 3. 别人如何下载使用

```powershell
git clone https://github.com/你的用户名/image-path-db.git
cd image-path-db
.\start.ps1
```

详见 [quickstart-docker.md](quickstart-docker.md)。

## 4. 日常更新流程

```powershell
git add .
git status                    # 确认没有误加 .env、upload 图片等
git commit -m "说明本次改了什么"
git push
```

## 5. 切勿提交的内容

| 文件/目录 | 原因 |
|-----------|------|
| `backend/.env` | 数据库密码、SECRET_KEY |
| 根目录 `.env` | Docker 本地密钥 |
| `upload/*` 真实图片 | 体积大、隐私 |
| `frontend/node_modules/` | 依赖可 npm install |
| `frontend/dist/` | Docker 构建时会生成 |

以上已在 `.gitignore` 中配置。

## 6. 使用 GitHub CLI 一键创建远程（可选）

```powershell
gh auth login
gh repo create image-path-db --public --source=. --remote=origin --push
```
