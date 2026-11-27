# 清單式互動教學

`lessons.json` 是劇本，`snorebattle/tutorial.py` 是共用執行器。所有得分、出牌、補牌、換人和效果仍走正式Game／Command；畫面沿用App.battle，不另做遊戲UI。

目前6關：snorer、slapper、cards_wave、cards_advantage、cards_time、cards_special。角色關完成返回教學首頁；卡牌關完成返回卡牌清單。每關完成後保存本機標記，可重玩，中途返回不算完成。開場故事動畫尚未加入。

## 每關資料

- id：穩定的完成紀錄ID，不要因改標題而更名。
- title／summary／group：標題、卡牌清單說明、分類。
- role：玩家視角0打呼、1巴掌；自動步驟會暫時顯示對手的實際操作。
- scenario.hands：雙方固定初始手牌ID，0與1各一份。
- scenario.draw_order：接下來共用牌堆的抽牌順序（第一個先抽）。要把手牌上限增加後的額外補牌也列進順序。
- scenario.config：本關覆蓋的固定示範設定；不修改玩家保存設定。
- steps：依順序執行的步驟，最後必須是finish。

## 步驟種類

- info：暫停並顯示圖卡，title、body、emphasis、image；按知道了才繼續。
- command：玩家按正式操作按鈕；action如to_cards、play、score、slap；play需card ID。
- select：玩家選指定card；quiz=true時不揭示答案、允許比較其他牌預覽，錯誤選擇不推進。
- auto：actions陣列，對手依序操作；每筆含action，出牌另含card。會先展示即將出的牌再實際出牌。
- observe：停下來觀察，玩家按繼續演示才前進。
- finish：完成確認，按鈕回到原清單並記錄本關完成。

## 插入圖卡

在任意兩步之間插入：

```json
{
  "kind": "info",
  "title": "這張牌影響未來",
  "body": "現在的落點不變，出牌後會改變後面的曲線。",
  "emphasis": "改變未來，不改過去",
  "image": "future_wave"
}
```

把圖片放在 `assets/tutorial/future_wave.png`，重開遊戲就會使用。圖片等比例縮放到圖卡區；沒有圖片時以emphasis顯示文字說明，不會出現空白。圖卡不會自行推進對局，對手也會暫停。

body與hint可使用{height}、{slap_points}、{hand_limit}、{preview}、{interval}、{duration}取得當前示範數值。插入info不需改控制器；改出牌或抽牌順序後需重新跑所有劇本測試。

卡牌的規則與素材讀自正式專案，僅副本張數與手牌被固定；更改cards.json效果可能改變解題結果，請一併檢查劇本。測試會實際完成六關，驗證測驗、進度、圖卡與正式存檔隔離。

## 聚焦與鏡頭特寫

observe步驟可加focus欄位，目前支援score_button、landing、thresholds。打呼者開頭先放大灰色得分按鈕，再放大落點與高度，最後使閾值外的上下區域脈動；按下一步才繼續，之後才出現規則圖卡。

特寫直接放大當前正式畫面的取樣，搭配暗幕、角色旁白、箭頭與動態標記，不複製規則、不推進Game的x，也不改正式視窗及滑鼠座標。只修改教學呈現，其他關卡與後續出牌流程不受影響。

## 開場節奏與階段橫幅

打呼者開頭新增角色／勝利目標介紹（observe、presentation=role_intro），按準備好了才進入階段橫幅。showcase是定時的純演示步驟，presentation=action_banner時播放中間的階段橫幅，presentation=locate_score時保持完整對戰畫面並框出原位置的得分按鈕。duration_ms控制停留時間，目前分別為2100與5500毫秒，之後接原本的特寫教學。

所有info圖卡僅保留一個知道了繼續按鈕。Escape仍能返回清單，中途離開不記完成。定時演示不執行Game操作，也不推進落點。

打呼者關卡每次返回行動階段、進入出牌階段都播放2400毫秒橫幅，播放期間暫停教學操作；等待鏡頭落定後播放。對手沿用固定劇本，但不顯示手牌、選牌預覽、出牌動畫及出牌按鈕。頂部旁白不加金框，文字以引導劇情口吻撰寫。

打呼者 scenario.config.wave_amplitude=30，僅調整起始波形；config.amplitude=50 仍為得分閾值。未指定 wave_amplitude 的正式對局沿用原設定。第二段以 focus=next_landing 聚焦未來落點；quiz 的 confirm_on_play=true 讓選牌只預覽，按出牌才驗證，錯誤答案不送入 Game、不消耗手牌。

打巴掌者關卡固定兩次機會：角色介紹 → 隱藏對手操作 → 行動橫幅 → 按鈕定位5500毫秒 → slap_button特寫 → landing落點 → positive_landing正值區域 → slap_chances次數 → 計分說明與保留機會 → 統整圖卡。旁白可用{slaps_left}、{slap_base}、{slap_points}帶入實際對局資料。說明步驟不允許提前打巴掌。

教學前進按鈕統一為「下一步」，finish為「完成教學」。打巴掌者示範倍率1.04；slap按鈕依真正資格亮起，但說明期間不註冊點擊操作。slap_chances特寫前以locate_chances在原戰鬥畫面框出次數2500毫秒，保留頂部實際介面位置。落點說明獨立完整，不假設玩家已看打呼者教學。

目前所有既有info步驟使用presentation=story，先以角色劇情文字說明呈現，不讀取圖檔、不使用重點圖卡框；待指定製作圖卡時再啟用圖片呈現。次數原位置定位改為5000毫秒。打巴掌後控制器等待3500毫秒才進入下一步，期間保留實際波形重置、換人與鏡頭移動。問號與驚嘆號使用暫時粗體與加厚繪製，無需圖檔。
