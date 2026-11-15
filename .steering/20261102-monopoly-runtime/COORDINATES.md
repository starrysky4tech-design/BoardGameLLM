# 操作の座標(フェーズ3、2026-11-02)

端末 SHG11、2432x1080、横向き。座標は取得画像の座標(`input tap` にそのまま渡す)。
「実機」は、この作業で端末に送って画面の変化を確かめたもの。「参照」は、評価用の参照画像から読んだもので、実機の確認は未了。
確定の操作(Buy の Yes、Make Changes、Accept Trade、Offer Trade など)は、この作業では押していない。

| 画面 | 操作 | 座標 | 状態 | 画面の変化 |
|---|---|---|---|---|
| 自分の手番(Roll 待ち) | Roll | 押下 (1257,763) → 上へ (1257,300) | 実機 | Roll → End Turn。HoldDrag を 12 回。3 秒待ってから押すと 12/12 |
| 自分の手番(End Turn 待ち) | End Turn | (330,320) | 実機 | AI の手番へ |
| 自分の手番 | Log を開く / 閉じる | (330,655) / (1567,205) | 実機 | log ↔ 盤 |
| 自分の手番 | Manage | (330,525) | 実機 | 拡大盤(zoomed_board)が開く |
| 拡大盤 | Return | (330,425)(2 回目で効いた) | 実機 | 盤へ戻る |
| 自分の手番 | Trade を開く | (330,450) | 実機 | trade 画面 |
| trade 画面 | Cancel | (1050,875) | 実機 | 「取引をキャンセルしますか」 |
| 取引キャンセルの確認 | Yes | (1462,800) | 実機 | 盤へ戻る。取引は成立していない |
| 取引キャンセルの確認 | No | (1040,800) | 参照 | 未確認 |
| 収監中(Post Bail) | Post Bail | (330,350) | 実機 | 収監の確認(jail_dialog) |
| 収監の確認 | Yes(₼50 を払う) | (1462,800) | 実機 | 出所(2 回)。戦績に影響する。「数手進める」指示のもとで実施(以後、保釈は自動化しない) |
| 収監の確認 | No | (1040,800) | 参照 | 未確認 |
| 購入の確認(BUY PROPERTY) | Yes | (1462,800) | 参照 | 未確認(購入は押していない) |
| 購入の確認 | No | (1040,800) | 参照 | 未確認 |
| 取引の提案(AI から) | Accept Trade | (1455,870) | 参照 | 未確認 |
| 取引の提案 | Decline Trade | (1045,870) | 参照 | 未確認(Cancel と同じ位置の並び。実機で Cancel は確認済み) |
| IMPROVEMENTS | Clear Changes | (1062,392) | 参照 | 未確認。押すと変更が取り消される |
| IMPROVEMENTS | Make Changes | (1455,392) | 参照 | 未確認。押すと建設が確定する(押していない) |
| 一時停止(Pause) | Pause | (335,750) | 実機(以前の対局で確認) | pause |
| 一時停止 | Resume | (1250,875) | 実機(以前の対局で確認) | 盤へ戻る |

注意
- Abandon Game、Save & Exit は、どの手順にも入れない(戦績・保存に影響する)
- 参照の座標は、ボタンの中心を画面の縮小図から読んだもの。使う前に、実機の画面で位置を確かめる

## 建設画面(2026-11-03、実機で確認)
- 赤い土地を 1 回タップして、IMPROVEMENTS を開いた(ユーザーのタップ。盤の左の列の赤いマス)
- Clear Changes: (1067,390) を押したが、画面は IMPROVEMENTS のまま(変更がない状態では、閉じないことがある。要確認)
- Make Changes: 画面上の位置は約 (1462,390)。確定の操作のため、押していない
- 「+」「-」は下の段に複数あり、どれが赤い土地かは、この画面からは確定できていない。建設は行っていない
- 未了: 赤い土地の「+」の特定、1 軒の建設と Make Changes の確認、Clear Changes の動作の確認

## 盤のタップ位置（2026-11-03、実機）
- 通常の盤（board_my_turn_end）で、下段の Reading Railroad を (1249,809) でタップ → 拡大盤（zoomed_board）が開く
- 拡大盤で Reading Railroad を選択した状態を、ユーザーが確認（選択表示あり）
- 拡大盤の中での、土地ごとの位置は未記録。残り 11 か所（色グループ 8 + 鉄道 3）は未確認

## 土地の詳細画面（2026-11-03、実機）
- 拡大盤（zoomed_board）で Mediterranean Avenue（茶色、M60）をタップ → 「MANAGE PROPERTY」（抵当用の画面）
- この画面の判別は未対応（classify が unknown）。IMPROVEMENTS（建設）とは別の画面
- Mortgage ボタン: 約 (1443,943) / Return ボタン: 約 (1006,929)。未押下（座標は画面の縮小図からの推定。押す前に確認）
- 画面内容: Owned by（自分）、Current rent M2、Mortgage Value M30
- 拡大盤で Baltic Avenue（茶色、M60）をタップ → 「MANAGE PROPERTY」（同じ画面）。所有者は AI のため、Mortgage ボタンは出ない（Return のみ）
- Return ボタン（Baltic・AI 所有）: 約 (1243,929)。Mediterranean（自分所有）は Mortgage ボタンが出て、Return は約 (1006,929) に左寄りになる。Return の位置は、所有者と Mortgage の有無で変わる
- Baltic の画面を、Return で戻った（拡大盤に戻ることを確認）は未実施

## ライトブルーの拡大表示（2026-11-03、実機）
- ユーザーが盤をタップ → 拡大盤（zoomed_board）が開いた。タップしたマスは未確認（座標は受け取っていない）
- 拡大盤の下段に水色の土地が写る: Connecticut（M120）、Vermont（M100）、Oriental（M100）。拡大盤での座標は未記録
- 未了: タップした盤上の位置（どの水色マスか）の記録。次回は、タップ座標をユーザーから教えてもらう
- 拡大盤で Oriental Avenue（水色、M100 [07]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）のため、Mortgage ボタンは出ない（Return のみ）
- Return ボタン: 約 (1243,929)（Baltic と同じ位置。Mortgage ボタンが無いとき）
- 水色の [06] Oriental の詳細画面の座標を確認（ユーザーのタップ。盤上の位置は未受領）
- 拡大盤で Vermont Avenue（水色、M100 [08]）をタップ → 「MANAGE PROPERTY」。Mortgage ボタンあり。Return: 約 (1006,929)（Mortgage ありの位置）、Mortgage: 約 (1443,943)

## 抵当ボタンの位置（MANAGE PROPERTY 共通）
- Mortgage ボタン: 約 (1443,943)。Mediterranean（自分所有）と Vermont（自分所有）の画面で、縮小画像から推定
- 全土地・鉄道・会社で同じ位置と見込む（ユーザー指示）。ただし、押して確かめてはいない
- Mortgage ボタンは、所有者が自分の土地でだけ出る（AI 所有・無所有では出ない）
- 押下の確認（Mortgage → Yes など）の座標は未記録。抵当は押していない
- 拡大盤で Connecticut Avenue（水色、M120 [09]）をタップ → 「MANAGE PROPERTY」。Mortgage ボタンあり。Return: 約 (1006,929)、Mortgage: 約 (1443,943)

## パープル・Electric Company の拡大表示（2026-11-03、実機）
- 通常の盤（board_my_turn_end）で、ユーザーがパープル／Electric Company 付近をタップ → 拡大盤（zoomed_board）が開いた（判別 1.0）
- タップした正確な盤上の位置は未受領（座標は記録できない）。次回は、タップ座標を教えてもらう
- 拡大盤で St. Charles Place（パープル、M140 [11]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)
- 拡大盤で Electric Company（会社 [12]）をタップ → 「MANAGE PROPERTY」（会社の説明つき）。Mortgage ボタンあり（自分所有）。Return: 約 (1006,929)、Mortgage: 約 (1443,943)
- 拡大盤で States Avenue（パープル、M140 [13]）をタップ → 「MANAGE PROPERTY」。所有者あり（AI）、Mortgage ボタンなし。Return: 約 (1243,929)
- 拡大盤で Virginia Avenue（パープル、M160 [14]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)
- 通常の盤で、ユーザーが Pennsylvania Railroad [15] 付近をタップ → 拡大盤（zoomed_board、判別 0.97）。タップの盤上座標は未受領
- 拡大盤で Pennsylvania Railroad [15] をタップ → 「MANAGE PROPERTY」（鉄道の説明つき）。所有者あり（AI）、Mortgage なし。Return: 約 (1243,929)

## オレンジ・鉄道・Penn の詳細（2026-11-03、実機）
- 通常の盤で、ユーザーがオレンジ [16]〜[19] 付近をタップ → 拡大盤（zoomed_board、判別 0.97）。タップの盤上座標は未受領
- 拡大盤で St. James Place（オレンジ、M180 [16]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)
- 拡大盤で Tennessee Avenue（オレンジ、M180 [18]）をタップ → 「MANAGE PROPERTY」。Mortgage ボタンあり（自分所有）。Return: 約 (1006,929)、Mortgage: 約 (1443,943)
- 拡大盤で New York Avenue（オレンジ、M200 [19]）をタップ → 「MANAGE PROPERTY」。所有者あり（AI）、Mortgage なし。Return: 約 (1243,929)
- 通常の盤で、ユーザーが赤 [21]〜[24] 付近をタップ → 拡大盤（zoomed_board、判別 1.0）。タップの盤上座標は未受領
- 拡大盤で Kentucky Avenue（赤、M220 [21]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)
- 拡大盤で Indiana Avenue（赤、M220 [22]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)
- 拡大盤で Illinois Avenue（赤、M240 [24]）をタップ → 「MANAGE PROPERTY」。所有者あり（AI）、Mortgage なし。Return: 約 (1243,929)
- 通常の盤で、ユーザーが B. & O. Railroad [25] 付近をタップ → 拡大盤（zoomed_board、判別 0.97）。タップの盤上座標は未受領
- 拡大盤で B. & O. Railroad [25] をタップ → 「MANAGE PROPERTY」（鉄道の説明つき）。所有者あり（自分）、Mortgage あり。Return: 約 (1006,929)、Mortgage: 約 (1443,943)
- 通常の盤で、ユーザーが黄色 [26]〜[29] と Water Works 付近をタップ → 拡大盤（zoomed_board、判別 0.97）。タップの盤上座標は未受領
- 拡大盤で Atlantic Avenue（黄色、M260 [26]）をタップ → 「MANAGE PROPERTY」。所有者あり（AI）、Mortgage なし。Return: 約 (1243,929)
- 拡大盤で Ventnor Avenue（黄色、M260 [27]）をタップ → 「MANAGE PROPERTY」。Mortgage ボタンあり（自分所有）。Return: 約 (1006,929)、Mortgage: 約 (1443,943)
- 拡大盤で Water Works（会社 [28]）をタップ → 「MANAGE PROPERTY」（会社の説明つき）。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)
- 拡大盤で Marvin Gardens（黄色、M280 [29]）をタップ → 「MANAGE PROPERTY」。Mortgage ボタンあり（自分所有）。Return: 約 (1006,929)、Mortgage: 約 (1443,943)
- 通常の盤で、ユーザーが緑 [31]〜[34] 付近をタップ → 拡大盤（zoomed_board、判別 0.99）。タップの盤上座標は未受領
- 拡大盤で Pacific Avenue（緑、M300 [31]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)
- 拡大盤で North Carolina Avenue（緑、M300 [32]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)
- 拡大盤で Pennsylvania Avenue（緑、M320 [34]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)
- 通常の盤で、ユーザーが Short Line [35] 付近をタップ → 拡大盤（zoomed_board、判別 0.97）。タップの盤上座標は未受領
- 拡大盤で Short Line R.R.（鉄道 [35]）をタップ → 「MANAGE PROPERTY」（鉄道の説明つき）。所有者あり（AI）、Mortgage なし。Return: 約 (1243,929)
- 通常の盤で、ユーザーがブルー [37]〜[39] 付近をタップ → 拡大盤（zoomed_board、判別 0.96）。タップの盤上座標は未受領
- 拡大盤で Park Place（ブルー、M350 [37]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)
- 拡大盤で Boardwalk（ブルー、M400 [39]）をタップ → 「MANAGE PROPERTY」。所有者なし（Unowned）、Mortgage なし。Return: 約 (1243,929)

## ライトブルーの手順（2026-11-03、実機で確認。盤の位置を画像から求めて検証）
- 全体盤で Connecticut [09] の位置: 約 (965,800) → 拡大盤（zoomed_board）が開く（確認済み）
- 拡大盤に出る黄色の案内「Drag left or right...」は、1回タップで消える: 約 (1200,540)（確認済み）
- 案内が消えた後の拡大盤で Connecticut の土地: 約 (963,640) → 「MANAGE PROPERTY」（確認済み。所有者あり、Mortgage あり、Return: 約 (1006,929)）
- 拡大盤での土地の位置は、案内の表示有無や盤の寄りで変わる。タップ前に画面を確認すること
- 残り: Vermont [08]、Oriental [06] の同じ手順は未実施
- Vermont [08]: 拡大盤（案内消去後）で約 (1152,640) → 「MANAGE PROPERTY」（所有者あり、Mortgage あり、Return: 約 (1006,929)）。確認済み
- 残り: Oriental [06]
- Oriental [06]: 拡大盤（案内消去後）で約 (1534,640) → 「MANAGE PROPERTY」（所有者なし、Mortgage なし、Return: 約 (1243,929)）。確認済み
- ライトブルー [06]・[08]・[09] の詳細まで確認完了

## 茶色 [01]・[03] の拡大表示（2026-11-03）
- 全体盤で茶色の位置をタップ → 拡大盤が開く。案内「Drag left or right...」は、拡大盤の (1200,540) をタップで消える（確認済み）
- 案内消去後の拡大盤での位置（確認済み）: Baltic [03] 約 (1057,614)、Mediterranean [01] 約 (1437,614)
- 詳細画面の座標（Mediterranean、Baltic）は未記録。次に詳細をタップして記録する
- Mediterranean [01]: 拡大盤（案内消去後）で約 (1437,614) → 「MANAGE PROPERTY」（所有者あり、Mortgage あり）。Return: 約 (1006,929)、Mortgage: 約 (1443,943)。確認済み
- 残り: Baltic [03] の詳細
- Baltic [03]: 拡大盤（案内消去後）で約 (1057,614) → 「MANAGE PROPERTY」（所有者 AI、Mortgage なし）。Return: 約 (1243,929)。確認済み
- 茶色 [01]・[03] の詳細まで完了

## Reading Railroad [05] の拡大表示（2026-11-03）
- 全体盤から拡大盤を開く（前の記録の (1249,809)）→ 案内は (1200,540) で消える（確認済み）
- 案内消去後の拡大盤での位置: 約 (1257,629)。詳細の座標は未記録
- Reading Railroad [05]: 拡大盤（案内消去後）で約 (1257,629) → 「MANAGE PROPERTY」（鉄道の説明つき、所有者あり、Mortgage あり）。Return: 約 (1006,929)、Mortgage: 約 (1443,943)。確認済み
- 鉄道 [05] を含め、街区・鉄道・会社の詳細記録は全件完了（[01]〜[39] の所有地）

## 抵当ボタンの確認（[01] Mediterranean、2026-11-03、実機）
- 全体盤で Mediterranean を (1540,800) → 拡大盤（案内は (1200,540) で消す）→ (1437,614) → MANAGE PROPERTY（所有者あり、Mortgage あり）
- Mortgage ボタン (1443,943) を押す → 確認「MORTGAGE PROPERTY: Are you sure you want to mortgage Mediterranean Avenue for M30?」が出る（確認済み）
- 確認ダイアログのボタン: No 約 (1037,814)、Yes 約 (1463,814)
- No を押して閉じた。所持金は変わらず（自分 M277）。抵当は実行していない
- Yes の効果（抵当で M30 受取）は未実行。実機で確認するなら、ユーザー指示が必要

## パープルの拡大盤の位置（2026-11-03、画像から求めて確認）
- 全体盤で St. Charles 付近 (890,717) → 拡大盤が開く（確認済み）。案内は (1200,540) で消す（確認済み）
- 案内消去後の拡大盤での位置（下段）: Virginia [14] 約 (957,614)、States [13] 約 (1151,614)、Electric Company [12] 約 (1337,614)、St. Charles [11] 約 (1529,614)
- 詳細の座標は未記録（次に、各土地の詳細をタップして確認する）

## オレンジの拡大盤の位置（2026-11-03、途中）
- 拡大盤（案内消去後）の下段で St. James Place [16] 約 (597,620)。画像からの推定（未タップ）
- Tennessee [18]: 左端がメニューに隠れる。New York [19]: 画面外。盤のドラッグが必要（未実施）

## オレンジの拡大盤の位置（2026-11-03、確認済み）
- 全体盤で St. James 付近 (946,439) → 拡大盤が開く（確認済み）。案内は (1200,540) で消す（確認済み）
- 全体盤の画像からの位置: New York (944,313)、Tennessee (944,356)、St. James (946,439)
- 案内消去後の拡大盤での位置（下段）: New York [19] 約 (971,614)、Tennessee [18] 約 (1151,614)、St. James [16] 約 (1534,614)
- 詳細の座標は、オレンジの詳細記録（[16][18][19]）を参照

## 赤の拡大盤の位置（2026-11-03、確認済み）
- 全体盤で Kentucky 付近 (1027,293) → 拡大盤が開く（確認済み）。案内は (1200,540) で消す（確認済み）
- 案内消去後の拡大盤での位置（下段）: Illinois [24] 約 (957,614)、Indiana [22] 約 (1151,614)、Kentucky [21] 約 (1529,614)
- 詳細の座標は、赤の詳細記録（[21][22][24]）を参照

## 黄色の拡大盤の位置（2026-11-03、確認済み）
- 全体盤で Atlantic 付近 (1308,293) → 拡大盤が開く（確認済み）。案内は (1200,540) で消す（確認済み）
- 案内消去後の拡大盤での位置（下段）: Marvin [29] 約 (957,614)、Water Works [28] 約 (1151,614)、Ventnor [27] 約 (1343,614)、Atlantic [26] 約 (1534,614)

## 緑の拡大盤の位置（2026-11-03、確認済み）
- 全体盤で Pacific 付近 (1560,312) → 拡大盤が開く（確認済み）。案内は (1200,540) で消す（確認済み）
- 案内消去後の拡大盤での位置（下段）: Pennsylvania [34] 約 (957,614)、North Carolina [32] 約 (1337,614)、Pacific [31] 約 (1534,614)

## ブルーの拡大盤の位置（2026-11-03、確認済み）
- 全体盤で Park Place 付近 (1575,601) → 拡大盤が開く（確認済み）。案内は (1200,540) で消す（確認済み）
- 案内消去後の拡大盤での位置（下段）: Boardwalk [39] 約 (1057,614)、Park Place [37] 約 (1437,614)

## 鉄道 [15] の拡大盤の位置（2026-11-03、確認済み）
- 全体盤で Pennsylvania Railroad 付近 (930,494) → 拡大盤が開く（確認済み）。案内は (1200,540) で消す（確認済み）
- 案内消去後の拡大盤での位置: Pennsylvania Railroad [15] 約 (1257,620)
- 残り: [25] B&O、[35] Short Line
- 鉄道 [25] B. & O.: 全体盤で (1251,300) → 拡大盤が開く（確認済み）。案内消去後の拡大盤での位置: 約 (1257,620)
- 残り: [35] Short Line
- 鉄道 [35] Short Line: 全体盤で (1560,495) → 拡大盤が開く（確認済み）。案内消去後の拡大盤での位置: 約 (1257,620)
- 鉄道 4 か所（[05][15][25][35]）の拡大盤位置は、すべて確認済み

## 最終整理（2026-11-03）
- 土地・鉄道・会社の詳細画面（MANAGE PROPERTY）: 28 か所すべて座標を記録済み（ただし Oriental の旧記録の [07] は [06] に修正）
- 色グループ 8 色と鉄道 4 か所の拡大盤の位置: 記録済み（全体盤の位置 → 案内消去 → 拡大盤の位置）
- Return: (1006,929)（抵当あり）、(1243,929)（抵当なし）。Mediterranean の画面で Mortgage ボタンの位置を確認（確認済み）。他の Return は、画面の縮小図からの推定を含む
- Mortgage (1443,943): 自分所有の画面で確認済み。Mortgage の確定（Yes、(1463,814)）は未実行
- 未確認: 抵当の Yes（実行）、解除（Unmortgage）、建設の Make Changes（確定）と Clear Changes（取消）、赤の「+」の位置、取引の Accept Trade、カードの種類別の閉じ方

## 抵当の確定と解除（2026-11-03、実機）
- Mediterranean [01] の Mortgage (1443,943) → 確認ダイアログ → Yes (1463,814) で抵当が実行された（確認済み）。現金 ₼277 → ₼307（+30）
- 抵当後の詳細画面: ボタンが「Unmortgage」に変わり、位置は (1443,943)（確認済み）。Return は (1006,929)
- 解除（Unmortgage）の確定ダイアログと、その Yes/No の位置は未確認
- 解除（Unmortgage）: 同じボタン (1443,943) → 確認「Are you sure you want to unmortgage Mediterranean Avenue for M33?」（確認済み）
- 確認ダイアログの No: 約 (1037,814) を押して、詳細画面（Unmortgage 表示）に戻った。現金 ₼307 のまま（確認済み）
- 解除の Yes（約 (1463,814)）は未実行
- 解除（Unmortgage）の Yes (1463,814) で解除が実行された（確認済み）。現金 ₼307 → ₼274（−33）。抵当の確定（+30）と解除（−33）で、抵当と解除の両方の位置が確認できた
- 抵当・解除の操作は、Mediterranean [01] の 1 件のみで確認。他の土地での動作は未確認

## 取引（Accept Trade）の確認（2026-11-03）
- 全体盤の左メニュー Trade (330,450) → 取引画面（trade）が開く（確認済み）
- 取引画面の下段ボタン: Cancel (1050,875)（確認済み）、Revert、Offer Trade（押さない）
- 取引画面の位置情報: Cancel は確認済み。AI からの提案（trade_offer）の Accept/Decline は、AI が提案したときに確認する

## 取引画面の盤の印（2026-11-03、実機）
- 取引画面（trade）で、Pennsylvania Railroad [15] の左の黄色の印をタップ → チェックが付いた（確認済み）。実機の座標: 約 (643,518)
- 案内「Touch a property marker...」は、案内の部分（約 (900,520)）をタップで消える（確認済み）
- 取引画面の印（確認済み、実機）: Pennsylvania [15] の左の黄色の印 (643,518)、Mediterranean [01] の下の青い印 (1109,814)、Short Line [35] の右の黄色の印 (1225,524)。3 つとも選択（チェック）された
- Offer Trade（約 (1036,800) 付近）は未押下。Cancel (1050,875) で取り消せる
- Offer Trade (1463,870) → 確認「Are you sure you want to make this offer?」が出る（確認済み）。Yes は約 (1463,814)、No は約 (1037,814)
- 提案を送る Yes は未押下（ユーザー判断待ち）
- Yes で提案を送った（確認済み）。AI（Dog）は断った: 「Dog has declined your offer.」→ OK ボタン 約 (1249,829)
- AI が断ったため、Accept Trade の画面は出なかった（未確認のまま）。Accept Trade を確認するには、AI が受ける提案が必要

## 取引の再提案（2026-11-03、実機）
- 取引画面の盤の印: Short Line [35] の右の印 (1223,523) をタップでチェックを外せる（確認済み）
- Offer Trade (1463,870) → 確認 Yes (1463,814) → AI（Dog）が断った（確認済み、2 回目）
- 断りダイアログの OK: (1249,760) で閉じた（確認済み）。(1249,829) では反応しなかった
- 取引画面の下段: Cancel (1050,875)、Revert（約 (880,870)）、Offer Trade (1463,870)
- Accept Trade（AI が受ける場合の画面）は、AI が受けないため未確認

---

# 作業の記録（2026-11-03、リミット前の整理）

## 実施結果（実機で確認したもの）
- 全体盤の土地・鉄道・会社の詳細（MANAGE PROPERTY）: 28 か所、座標を記録済み
- 色グループ 8 色と鉄道 4 か所の拡大盤位置: 記録済み（全体盤位置 → 案内消去 → 拡大盤の位置）
- 案内「Touch a property...」「Drag left or right...」: 案内の部分（(1200,540) または (900,520)）をタップで消える
- 抵当: Mortgage (1443,943) → 確認 Yes (1463,814)。Mediterranean [01] で +30（確認済み）
- 解除: Unmortgage (1443,943) → 確認 Yes (1463,814)。Mediterranean [01] で −33（確認済み）。確認 No (1037,814) も確認済み
- 取引: Trade (330,450) で取引画面を開く。盤の印の選択・付け外し、Offer Trade (1463,870)、確認 Yes (1463,814)、AI の断り OK (1249,760)、Cancel (1050,875) → 確認 Yes (1462,800)。いずれも確認済み
- Return: (1006,929)（抵当あり）、(1243,929)（抵当なし）、拡大盤の Return (330,425)
- ダイス・ロール: HoldDrag の成功（条件つき。表示後 3 秒待ち）

## 未確認・未実施
- **取引の Accept Trade**: AI が受ける提案が出ていない（2 回とも断られた）。位置は未確認
- **取引の Revert**: 押していない。位置は推定（約 (880,870)）
- **建設**: Make Changes（確定）、Clear Changes（取消の動作）、赤の「+」の位置。いずれも未実施
- **ダイス出目・Log の読み取り**: 未解決（計画2は保留）
- **収監中 Roll 表示**: 判別未対応
- **カードの種類別の閉じ方**: × (1695,312) で閉じた例のみ
- **強制終了からの復帰（Resume）**: 未実装・未確認
- **抵当・解除の他の土地での動作**: Mediterranean のみ確認。ボタン位置は同じと見込む（未確認）

## 現在の状態
- 対局: 自分の手番の全体盤（board_my_turn_end）
- 所持金: 自分 ₼274 / AI ₼425
- 取引: 成立なし。提案は断られ、取引は Cancel で終了済み
- 保有: Mediterranean は抵当を解除済み（抵当なし）

## 次に再開するとき
1. Accept Trade: AI が受ける条件（現金の付け方など）で提案し、受諾画面の位置を確認する
2. Revert の位置を、取引画面で 1 回押して確認する
3. 建設（Make Changes、Clear Changes、赤の「+」）の確認
4. 収監中 Roll とカードの閉じ方の確認


---

# 2026-11-07〜08 の実機確認(2 局目: Thimble、Easy)

座標は原寸(2432x1080)。表示座標は 1.22 倍する。**「確認済み」は、実機で押して結果を見たもの**。

## 対局の開始(確認済み)
Main Menu の PLAY NOW(337,183)→ 対局設定(自分 Top Hat、相手の駒、難易度はドロップダウン。矢印 1507,693 → Easy 1598,661)→ Play(1608,927)→ チュートリアル No(1046,818)→ 先攻の通知 OK(1254,818)。**新しい対局は、ユーザーの確認が要る(戦績が変わる)。**

## 購入・競り(確認済み)
- 購入画面は、土地のカードが付く形(見出しが高い位置)。「Purchase "<土地>" for ₼<価格>?」。OCR は ₼ を `A`、`M:` と誤読する。価格は、定価と一致するときだけ受け入れる。
- 見送り(Pass 995,854)→ 確認 Yes(1466,781)→ 競りへ。競りの間は、Log を開けない。土地は、画面のカード(題名と Original Value)から読む。
- 入札が無いとき、「Highest bid」の黄色い枠そのものが出ない(0 とみなす)。入札は、Bid(1662,268)→ キーパッド → ACCEPT。**Forfeit は (1662,634)**(確認 → Yes 1466,781)。
- 確認ダイアログの Yes は (1466,781〜790)、No は (1046,811)。通知ダイアログ(OK だけ)は OK (1254,811)。

## 刑務所(確認済み)
- 通常の Roll メニューに Post Bail(333,372)。釈放カードを持つと Use Card(333,317)と Post Bail(333,421)。Post Bail → JAIL ダイアログ(待ちが 2 秒以上かかる)→ Yes(1462,800)。
- 現金が保釈金に足りない、または Roll が無いメニュー: Post Bail が一番上(333,323)。保釈金を払うしかない。

## 建設(確認済み)
色グループを全部持つと、全体盤の色グループを押すと建設画面が開く(案内を消す: 1200,540)。Make Changes(1468,366)→ 確認「commit these changes?」Yes(1466,790)。Clear Changes(1068,340)→ 確認 Yes。現金不足、上限は通知(OK)で閉じる。
| 色 | + の位置(原寸) |
|---|---|
| ピンク | Virginia (1007,836)、States (1202,836)、St. Charles (1598,836) |
| ライトブルー | Connecticut (1035,830)、Vermont (1226,830)、Oriental (1623,830) |
| オレンジ | New York (1031,836)、Tennessee (1226,836)、St. James (1623,836) |
| ダークブルー | Boardwalk (1104,839)、Park Place (1495,839) |
| 緑 | Pennsylvania (1025,836)、North Carolina (1397,836)、Pacific (1617,836)(**+ の位置だけ。確定は未確認**) |
− は、+ の左 98 画素。赤は、組が揃うと建設画面が開く(**未確認**。揃っていないと、拡大盤が開く)。ホテル(家 4 軒の次)は、ピンクの地の上では、薄い赤の横長の塊(約 160×52)として写る。

## 抵当・解除・家の売却(確認済み)
全体盤の色グループ → 案内を消す → 土地を押す → 詳細(MANAGE PROPERTY)→ 右下のボタン(1482,976)は、Mortgage または **Unmortgage(同じ位置)**。押した後の確認の本文で、期待の操作かを確かめる。解除の費用は、抵当価値の 1.1 倍(₼30 → ₼33)。家の売却は、建設画面の − で、半額。詳細の Return は (1022,933)。

## 取引(確認済み)
- 取引の提案が来ると、取引画面(左に盤のマーカー、右に 2 列)。列の読み取り枠: 自分 (1364,525,1610,830)、相手 (1629,525,1879,830)。Decline Trade (1053,878)、**Accept Trade (1455,872)→ 確認「accept the offer?」Yes**(1466,790)。
- **自分から持ちかける:** 盤の Trade ボタン(333,425。拡大盤の Return と同じ位置なので、画面を確かめてから押す)→ 左の盤のマーカーを押して、土地を右の列に足す(青 = 自分、黄 = 相手)→ Offer Trade (1457,920)→ 抵当中の土地を含むと警告 → Yes → 通知「<駒> has proposed a counter offer」→ 取引画面が、相手の対案(Accept / Decline)になる。Easy の AI は、1 : 1 の提案に、土地と現金を足した対案を返した。
- **未確認:** 取引画面での現金の入力、対案を自分から出す操作。

## 負債・終了(確認済み)
- 所持金がマイナスだと、メニューが **Auto Sell(333,262)/ Trade / Resign(333,482)/ Manage** に変わり、Roll / End Turn が消える。**この画面では、Return の位置に Trade がある。**
- Auto Sell は、確認なしで、すぐ全土地を抵当に入れる(−₼619 → ₼26)。
- Resign →「Are you sure you want to resign?」Yes → 「<駒> WINS!!」→ Dice Rolling History(OK 1254,903)→ Game Statistics(Main Menu 1257,909)。

## 固まる画面の対処(確認済み)
- ダイスの演出で固まったら、盤の右の余白(1900,420)を 1 回タップする。ポーズ画面の Resume は、緑のチェックの絵 (1255,869)(ラベルの位置は効かない)。Log が開いたままなら × (1567,205)。
- adb は、まれに `error: closed` で切れる。1 回やり直す。出力の文字コード(cp932)で `₼` を出力するとエラーになる。`PYTHONIOENCODING=utf-8` で実行する。

## Log の文型(確認済み)
`bought <土地> for ₼<額>`(通常の購入)、`<P> built a hotel on`、`unmortgaged`、`Property is mortgaged. No rent collected.`、`<P> accepted trade with <Q>`、`<P> received ₼<額> from <Q>`、`<P> received <土地> from <Q>`、`<P> initiated a trade with <Q>.`、`Oh no <P> has been sent to Jail`(! が無い)、`<P> gets to go first.`。カードの「各プレイヤーに払う」は、払う側の行しか出ない。カードで動いた移動は、サイコロの行が無く、「landed on」だけが出る。OCR は、空白の欠落、`o`→`0`、`A`→`M`、`I`→`l` を起こす。

## 2026-11-10 追記(実機確認済み)
- **赤の建設画面**: 全体盤の赤 (1027,293) → 建設画面。+ の位置(原寸): Illinois (1003,836)、Indiana (1198,836)、Kentucky (1596,836)。Illinois と Kentucky を押して確定(Make Changes 1468,366 → Yes 1466,790)。現金 ₼301→₼1、「Shoe built 1 house on Illinois Avenue」。Indiana の + は未押下。
- 建設画面の土地の読み取り(`bars.improvements_red`): 実画像で Illinois 1、Indiana 0、Kentucky 1 を正しく読む。再同期(`--read-holdings`)も赤の組が揃った状態で成功。
- **取引(2026-11-09 の確認)**: 現金アイコンは列へ下にドラッグ(swipe 500ms、y 364→620)→ キーパッド → ACCEPT (1347,824)。AI の提案の現金を編集すると、ボタンが Counter Offer (1457,920) に変わる → Yes (1466,790) → 通知の OK (1254,811)。Revert (1268,903)。
- **Save & Exit → Resume**: Pause (333,770) → Save & Exit Game (1257,648) → Yes (1466,790) → Main Menu → PLAY NOW (337,183) → Resume (606,187) → Pause 画面 → 緑のチェック (1255,869)。
