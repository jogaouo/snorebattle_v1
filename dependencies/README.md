# 離線 Pygame

`pygame-ce-2.5.6-windows-py312.zip` 封存目前測試使用的 Windows x64／CPython 3.12 pygame-ce 2.5.6 套件內容，包含套件原附文件與 LGPL 授權文字（pygame/docs/generated/LGPL.txt）。

`bootstrap.py` 驗證 SHA-256 後展開到 `.vendor`。此 ZIP 必須與程式一起提交到 GitHub；不需要 Git LFS。初次啟動不會下載或執行遠端安裝程式。

日後升級 Pygame 時，應同時更新 `requirements.txt`、離線包以及 `bootstrap.py` 中的版本、檔名和雜湊，並重新驗證乾淨下載版啟動。
