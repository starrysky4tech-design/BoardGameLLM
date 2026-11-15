"""プラグイン内で、認識と executor が共有する「追跡している状態」。

盤の読み取りは決定の途中の状態(決定の列、手札の中身、山札)を持たないので、executor が手を実行できたら、
その予測(`Rules.apply` の結果)をここに置き、認識は次の観測でこの状態を土台にして、画面から読めるものだけを
上書きする(自分の盤・餌・キューブ・餌箱・トレイ)。ランナーが渡す `previous` は、観測の状態なので使わない。
"""

from dataclasses import dataclass

from bglm.plugins.wingspan.logic.state import WingspanState


@dataclass
class Tracker:
    state: WingspanState | None = None
    # 手番開始のダイアログで読んだ、ラウンド(1〜4)。再開の初期状態を作るときだけ使う
    round_hint: int | None = None
