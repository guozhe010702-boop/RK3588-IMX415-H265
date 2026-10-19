"""Acceptance must never pass short/minimized runs or hide added frame gaps."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("live_stability", Path(__file__).with_name("live_stability.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def samples():
    rows, boards = [], []
    for at in (11, 1811):
        row = dict(elapsedSeconds=at, windowMinimized=False, windowVisible=True,
            pc_decode_errors=0, reconnects=0, gui_rss_mib=150, pc_decoder_rss_mib=190,
            decodedCount=60*at, paintedCount=60*at, board_stale=False,
            pc_decode_size="3840x2160", preview_size="1280x720")
        rows.append(row)
        boards.append(dict(elapsedSeconds=at, monotonic=at, pid=123,
            encoded=at*60, decoded=at*60, duplicates=0, drops=0, hardwareAndModeValid=True,
            capture=dict(frames=at*60, monotonicUs=at*1000000, sequenceGaps=100, errors=0)))
    return rows, boards


def test_startup_gap_is_preserved_but_added_gap_fails():
    rows, boards = samples()
    result = module.summarize(rows, boards, 1815, 1815, True)
    assert result["passed"] and result["initialGapCount"] == 100
    boards[-1]["capture"]["sequenceGaps"] += 1
    assert not module.summarize(rows, boards, 1815, 1815, True)["passed"]


def test_minimized_or_wrong_resolution_or_short_run_never_passes():
    rows, boards = samples()
    assert not module.summarize(rows, boards, 75, 75, True)["passed"]
    assert not module.summarize(rows, boards, 1815, 1815, False)["passed"]
    rows[-1]["windowMinimized"] = True
    assert not module.summarize(rows, boards, 1815, 1815, True)["passed"]
    rows[-1]["windowMinimized"] = False
    rows[-1]["pc_decode_size"] = "1920x1080"
    assert not module.summarize(rows, boards, 1815, 1815, True)["passed"]
