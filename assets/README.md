# 素材替換

不用素材也可執行，預設以 Pygame 繪製角色與介面。

- `images/snorer.png`：打呼者，透明背景建議。
- `images/slapper.png`：打巴掌者。
- `images/background.png`：整體背景。
- `audio/card_select.wav`：選取手牌的輕短聲，可替換同名WAV。
- `audio/card.wav`、`audio/slap.wav`、`audio/tool.wav`：事件音效。
- `audio/music.ogg`：循環背景音樂。
- `fonts/font.ttf`：非 Windows 環境的中文字型備援。

新增／替換後重開遊戲。資源載入與預設繪圖集中在 assets.py、app.py，不影響規則核心。

目前提供原創程序合成的短促出牌刷聲 `audio/card.wav`（0.22秒、44.1kHz、16-bit mono PCM），可直接替換同名WAV。設定→音效可調整音量及試聽；音量對所有事件音效統一生效，背景音樂獨立。

選牌聲只在手動點選手牌、切換到另一張手牌時播放；再次點同張取消、單純重畫、程式自動預選不播放。`card_select.wav` 為原創65毫秒輕短聲，跟隨音效音量與靜音設定；設定頁可獨立試聽。
