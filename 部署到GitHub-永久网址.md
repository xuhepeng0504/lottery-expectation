# 部署到 GitHub Pages：永久固定网址 + 电脑关机也能看

目标：得到一个**永远不变**的网址（`https://<用户名>.github.io/<仓库名>/`），并且数据由 GitHub 云端每 15 分钟自动抓取更新，**你的电脑关机、断网都不影响访问**。

> 费用：公开仓库 + GitHub Pages + Actions 全部免费。
> 数据更新：云端每 15 分钟运行一次 `抓取官方开奖 → 重新计算 → 发布页面`。

---

## 方式一：网页手动部署（推荐，约 5 分钟）

### 1. 注册/登录 GitHub

打开 <https://github.com>，没有账号就注册（免费）。记住你的**用户名**。

### 2. 新建仓库

右上角 `+` → **New repository**：

- Repository name：`lottery-expectation`（可自定义，后面网址会用到）
- 选择 **Public**（免费账号的 Pages 必须公开仓库）
- 勾选 **Add a README file**
- 点 **Create repository**

### 3. 上传项目文件

在仓库页面点 **Add file → Upload files**，把本项目里的这些**文件/文件夹**拖进去：

```
scripts/            （整个文件夹：fetch_data.py、analyze.py、build_site.py、template.html 等）
data/ssq.json
data/dlt.json
README.md
```

> `.github/workflows/deploy.yml` 和 `.gitignore` 建议用下面第 4 步的网页编辑器创建（拖拽隐藏文件夹有时会被浏览器忽略）。
> `tools/`、`logs/`、`index.html`、`preview.png` **不需要上传**。

上传后点 **Commit changes**。

### 4. 创建自动更新工作流

仓库页面 **Add file → Create new file**，文件名填：

```
.github/workflows/deploy.yml
```

把本项目 `.github/workflows/deploy.yml` 的内容完整粘贴进去，点 **Commit changes**。

（`.gitignore` 同理：Add file → Create new file，文件名 `.gitignore`，粘贴本项目同名文件内容。）

### 5. 开启 Pages

仓库 **Settings → Pages**：

- **Build and deployment → Source** 选择 **GitHub Actions**

### 6. 首次运行

仓库 **Actions** 标签页 → 左侧 **「更新数据并部署」** → 右侧 **Run workflow** → 绿色按钮运行。

等待 1~2 分钟，图标变绿即部署成功。

### 7. 固定网址

```
https://<你的GitHub用户名>.github.io/lottery-expectation/
```

把这个网址发给任何人，手机/电脑、任何网络都能打开；电脑关机也能看。

---

## 方式二：一键脚本（需要 GitHub Token）

适合不想手动点网页的情况：

1. 打开 Token 创建页（已预选权限）：
   <https://github.com/settings/tokens/new?scopes=repo,workflow&description=lottery-deploy>
   拉到最下面点 **Generate token**，复制生成的 Token（只显示一次）
2. 在本项目文件夹里，**双击 `一键发布到GitHub.bat`**（或右键 `发布到GitHub.ps1` → 使用 PowerShell 运行）
3. 粘贴 Token（输入不回显，注意不要发到聊天/截图里）
4. 等待脚本自动完成：验证 Token → 创建公开仓库 → 上传代码/数据 → 开启 Pages → 触发部署 → 等待部署成功
5. 脚本会打印固定网址

> 如果提示权限不足，请确认 Token 勾选了 `repo` + `workflow`；如果 Pages 自动开启失败，按「方式一」第 5 步手动选一下即可。
> 如果执行脚本被系统拦截（PowerShell 执行策略），用 `一键发布到GitHub.bat` 启动即可，它已带 `-ExecutionPolicy Bypass`。

---

## 更新机制

- GitHub Actions 工作流 `.github/workflows/deploy.yml` 每 **15 分钟**运行一次：
  1. `python scripts/fetch_data.py` 抓取官方双色球/大乐透数据
  2. `python scripts/analyze.py` 重新计算统计、期望指数、五组号码
  3. `python scripts/build_site.py --deploy` 生成静态页面 `dist/`
  4. 发布到 GitHub Pages
- 页面加载后还会每 5 分钟请求一次 `data/site_data.json`，有更新就自动重渲染。
- 电脑关机、断网都不影响上述云端更新和访问。

## 常见问题

**Actions 运行失败？**
点进失败的运行记录看日志。常见原因：
- 抓取步骤超时/被拦截：重新运行一次（Run workflow）即可，抓取脚本自带 4 次重试；
- Pages 未开启：Settings → Pages → Source 选 GitHub Actions；
- 仓库是 Private：免费账号 Pages 需要 Public 仓库。

**网址 404？**
首次部署需要等 Actions 跑完（1~2 分钟）；确认 Settings → Pages 显示 "Your site is live at ..."。

**国内访问 github.io 慢？**
GitHub Pages 在国内多数网络可访问但可能偏慢。若长期打不开，可以改用 Cloudflare Pages（同样免费，需要 Cloudflare 账号）或国内静态托管；页面本身是纯静态的，换托管只需上传 `dist/` 目录。

**想改更新频率？**
编辑 `.github/workflows/deploy.yml` 里的 `cron`，例如 `*/30 * * * *` 表示每 30 分钟。

**仓库名/用户名会体现在网址里**，建议用英文小写、无空格。
