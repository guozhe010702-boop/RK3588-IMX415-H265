import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("tune_capture_irqs", Path(__file__).resolve().parents[1] / "tune_capture_irqs.py")
tuning = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tuning)


def test_only_active_camera_irqs_move_to_distinct_big_cpus():
    text = """ CPU0 CPU1 CPU2 CPU3 CPU4 CPU5 CPU6 CPU7
62: 100 0 0 0 0 0 0 0 GICv3 163 Level rkisp_hw
64: 0 0 0 0 0 0 0 0 GICv3 166 Level rkisp_hw
70: 200 0 0 0 0 0 0 0 GICv3 187 Level rkcifhw
137: 500 0 0 0 0 0 0 0 GICv3 259 Level eth1
"""
    plan = tuning.plan_interrupts(text, {c: 1024 if c >= 4 else 446 for c in range(8)}, set(range(8)))
    assert [(r["irq"], r["cpu"]) for r in plan] == [(62, 5), (70, 4)]
    assert tuning.parse_list("0-3,5,7") == {0,1,2,3,5,7}


def test_shared_or_missing_camera_interrupt_is_rejected():
    with pytest.raises(ValueError):
        tuning.plan_interrupts("70: 10 0 GICv3 Level unrelated, rkcifhw", {4:1024,5:1024}, {4,5})
    with pytest.raises(ValueError):
        tuning.plan_interrupts("", {0:100}, {0})
