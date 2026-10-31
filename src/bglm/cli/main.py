"""コマンドの入口(`bglm`)。仕様の正本は docs/02 の「CLI設計」。"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from bglm.application.evaluation import EvalHarness
from bglm.application.registry import PluginRegistry
from bglm.application.replay import Replayer, ReplayError
from bglm.cli import wiring
from bglm.core.errors import BglmError
from bglm.core.models import Point, StopReason, Tap
from bglm.infrastructure.run_logger import FsRunReader, PngStore, load_frame, load_steps, write_png

TARGET_RATE = 0.95  # docs/01 の「要素単位の正答率」

app = typer.Typer(no_args_is_help=True, help="ターン制ボードゲームの自動プレイ")
eval_app = typer.Typer(help="認識の正答率の計測と、評価セットの追加", invoke_without_command=True)
app.add_typer(eval_app, name="eval")

Game = Annotated[str, typer.Option("--game", help="ゲーム名(例: kahuna)")]
ConfigPath = Annotated[Path | None, typer.Option("--config", help="設定ファイル")]
RunsDir = Annotated[Path, typer.Option("--runs-dir", help="実行ログの置き場")]


def _fail(message: str, code: int = 2) -> typer.Exit:
    typer.echo(f"エラー: {message}", err=True)
    return typer.Exit(code)


@app.command()
def run(
    game: Game,
    mode: Annotated[str, typer.Option(help="step=1手ずつ確認 / auto=連続実行")] = "step",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="入力を送らずにループを回す")] = False,
    config: ConfigPath = None,
    runs_dir: RunsDir = wiring.RUNS_DIR,
) -> None:
    """ゲームを自動プレイする。"""
    if mode not in ("step", "auto"):
        raise _fail(f"--mode は step か auto: {mode!r}")
    try:
        cfg = wiring.load_config(game, config)
        plugin = PluginRegistry().load(game)
        device = wiring.make_device(cfg)
    except BglmError as e:
        raise _fail(str(e)) from e

    def confirm(move: Any) -> bool:
        return typer.confirm(f"次の手を実行しますか: {move}", default=False)

    typer.echo(f"{game} を {mode} モードで開始{'(dry-run: 入力は送らない)' if dry_run else ''}")
    summary = wiring.execute_run(
        plugin=plugin,
        config=cfg,
        mode=mode,  # type: ignore[arg-type]
        dry_run=dry_run,
        source=device,
        driver=device,
        runs_root=runs_dir,
        confirm=confirm if mode == "step" else None,
        echo=typer.echo,
    )
    for line in wiring.describe_stop(summary, runs_dir):
        typer.echo(line)
    raise typer.Exit(0 if summary.stop_reason is StopReason.GAME_OVER else 1)


@app.command()
def capture(
    game: Game,
    tap: Annotated[
        tuple[int, int] | None, typer.Option("--tap", help="画面の座標を1回タップする(疎通確認)")
    ] = None,
    config: ConfigPath = None,
    runs_dir: RunsDir = wiring.RUNS_DIR,
) -> None:
    """画面取得と入力の疎通を確かめる。--tap を付けない限り、入力は送らない。"""
    try:
        device = wiring.make_device(wiring.load_config(game, config))
        started = time.monotonic()
        frame = device.capture()
        elapsed = time.monotonic() - started
        out = runs_dir / "capture" / f"{game}-{datetime.now():%Y%m%d-%H%M%S}.png"
        write_png(out, frame.image)
        typer.echo(f"取得 {frame.width}x{frame.height}、{elapsed:.2f}秒 → {out}")
        if tap is not None:
            device.perform(Tap(Point(*tap)))
            typer.echo(f"タップ {tap}")
    except BglmError as e:
        raise _fail(str(e)) from e


@app.command()
def calibrate(game: Game) -> None:
    """座標のキャリブレーション。"""
    if game == "kahuna":
        raise _fail("Kahuna は較正不要(点線と石の位置は board.json、領域はコード内の定数)", 2)
    raise _fail(f"{game} の較正は未実装")


@eval_app.callback()
def evaluate(
    ctx: typer.Context,
    game: Game = "kahuna",
    eval_dir: Annotated[Path, typer.Option(help="評価セットの置き場")] = wiring.EVAL_DIR,
) -> None:
    """評価セットで認識の正答率を、要素ごとに計測する。"""
    if ctx.invoked_subcommand is not None:
        return
    try:
        report = EvalHarness(PluginRegistry().load(game), eval_dir, PngStore()).evaluate()
    except BglmError as e:
        raise _fail(str(e)) from e
    typer.echo(f"{report.cases}件")
    for group in sorted(report.totals):
        typer.echo(
            f"{group:16s} {report.hits[group]:5d}/{report.totals[group]:<5d} {report.rate(group):6.1%}"
        )
    for miss in report.misses[:30]:
        typer.echo(f"  誤り: {miss}")
    typer.echo(f"最小 {report.worst_rate:.1%}(目標 {TARGET_RATE:.0%})")
    raise typer.Exit(0 if report.passes(TARGET_RATE) else 1)


@eval_app.command("add")
def eval_add(
    run_id: str,
    step: int,
    game: Game = "kahuna",
    label_file: Annotated[Path | None, typer.Option(help="正解ラベルの JSON")] = None,
    accept: Annotated[bool, typer.Option(help="今の認識結果を正解として登録する")] = False,
    case_id: Annotated[str | None, typer.Option(help="省略時は <run_id>_<step>")] = None,
    runs_dir: RunsDir = wiring.RUNS_DIR,
    eval_dir: Annotated[Path, typer.Option(help="評価セットの置き場")] = wiring.EVAL_DIR,
) -> None:
    """実行ログの1手の画面を、評価セットへ追加する。正解は --label-file か --accept で指定する。"""
    if (label_file is None) == (not accept):
        raise _fail("--label-file か --accept のどちらか一方を指定する")
    try:
        plugin = PluginRegistry().load(game)
        harness = EvalHarness(plugin, eval_dir, PngStore())
        run_dir = runs_dir / run_id
        record = next((r for r in load_steps(run_dir) if r.step == step), None)
        if record is None or not record.frame_paths:
            raise ReplayError(f"{run_id} に手 {step} の画像が無い")
        if label_file is not None:
            label = json.loads(label_file.read_text(encoding="utf-8"))
        else:
            result = Replayer(plugin, FsRunReader(runs_dir)).replay(run_id, step)[0]
            label = {"screen": result.recognition.ui.screen}
            describe = getattr(plugin, "describe_recognition", None)
            if describe is not None:
                label["elements"] = describe(result.recognition)
        frame = load_frame(run_dir, record.frame_paths[0])
        path = harness.add_case(frame.image, case_id or f"{run_id}_{step:06d}", label)
    except (BglmError, OSError, json.JSONDecodeError) as e:
        raise _fail(str(e)) from e
    typer.echo(f"追加: {path}")


@app.command()
def replay(
    run_id: str,
    step: Annotated[int | None, typer.Option(help="この手だけ再実行する")] = None,
    game: Game = "kahuna",
    runs_dir: RunsDir = wiring.RUNS_DIR,
) -> None:
    """保存した画像から認識と思考を再実行し、ログと比べる(入力は送らない)。"""
    try:
        results = Replayer(PluginRegistry().load(game), FsRunReader(runs_dir)).replay(run_id, step)
    except BglmError as e:
        raise _fail(str(e)) from e
    for r in results:
        mark = "一致" if r.consistent else "不一致"
        typer.echo(
            f"{r.step:>4}  {r.recognition.ui.screen:<14} 認識 {'同じ' if r.recognition_matches else '違う'}  "
            f"手 {_move_text(r.chosen_move)}  {mark}"
        )
    raise typer.Exit(0 if all(r.consistent for r in results) else 1)


def _move_text(move: Any) -> str:
    return "-" if move is None else str(move.get("type", move))


if __name__ == "__main__":
    app()
