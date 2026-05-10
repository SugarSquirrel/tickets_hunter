# 本機已修改完成，Push 新版本到既有 GitHub Repo

## 1. 進入專案資料夾

```bash
cd 你的專案路徑
````

---

## 2. 確認目前所在分支

```bash
git branch
```

如果你要推到 `main`：

```bash
git checkout main
```

---

## 3. 確認遠端 GitHub Repo

```bash
git remote -v
```

正常會看到類似：

```bash
origin  https://github.com/你的帳號/你的repo名稱.git
```

---

## 4. 先拉 GitHub 最新版本

```bash
git pull origin main
```

如果你的分支不是 `main`，把 `main` 改成你的分支名稱，例如：

```bash
git pull origin master
```

---

## 5. 查看本機修改狀態

```bash
git status
```

---

## 6. 加入所有修改檔案

```bash
git add .
```

---

## 7. 建立新版本 Commit

```bash
git commit -m "更新版本說明"
```

例如：

```bash
git commit -m "Update model training pipeline"
```

---

## 8. Push 到 GitHub

```bash
git push origin main
```

如果你的分支不是 `main`，改成你的分支名稱：

```bash
git push origin master
```

---

# 之後每次更新版本都用這組

```bash
git pull origin main
git status
git add .
git commit -m "更新版本說明"
git push origin main
```

---

# 常見情況

## 沒有東西可以 commit

如果出現：

```bash
nothing to commit, working tree clean
```

代表目前沒有新的修改需要推上去。

---

## push 前忘記 pull

如果出現遠端版本比本機新的錯誤，先執行：

```bash
git pull origin main
```

再重新 push：

```bash
git push origin main
```

---

## 查看 commit 紀錄

```bash
git log --oneline
```

```
```
