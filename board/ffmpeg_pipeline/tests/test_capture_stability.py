import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('capture_stability',Path(__file__).with_name('capture_stability.py'))
stability = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stability)


def samples():
    rows=[]
    for second in (0,1,2):
        rows.append({'monotonic':100+second,'state':{
            'capturePid':42,'captureStartedAt':'first','config':{'fps':60},
            'state':'running','rtspReady':True,'lastFrameAgeSeconds':.1,
            'frame':60*second,'droppedFrames':'0','duplicateFrames':'0',
            'metrics':{'stale':False,'capture':{'available':True,'stale':False,
                'monotonicUs':(100+second)*1000000,'frames':60*second,
                'sequenceGaps':51,'errors':0}}}})
    return rows


def test_startup_gaps_preserved_but_only_window_increment_is_evaluated():
    r=stability.summarize(samples(),2)
    assert r['passed'] and r['captureFps']==60
    assert r['startSequenceGaps']==r['endSequenceGaps']==51
    assert not r['fullChain4k60Validated']


def test_one_gap_fails_even_if_average_fps_is_60():
    rows=samples();rows[-1]['state']['metrics']['capture']['sequenceGaps']=52
    r=stability.summarize(rows,2)
    assert not r['passed'] and r['newSequenceGaps']==1


def test_restart_or_mid_window_reset_cannot_be_hidden_by_final_counts():
    for change in ('capturePid','reset'):
        rows=samples()
        if change=='capturePid': rows[1]['state']['capturePid']=99
        else: rows[1]['state']['metrics']['capture']['sequenceGaps']=0
        assert not stability.summarize(rows,2)['passed']


def test_stale_sample_and_short_window_do_not_pass():
    rows=samples();rows[1]['state']['metrics']['capture']['stale']=True
    assert not stability.summarize(rows,2)['passed']
    assert not stability.summarize(samples(),1800)['passed']


def test_encoder_duplication_and_missing_statistics_are_not_success():
    rows=samples();rows[-1]['state']['duplicateFrames']='1'
    assert not stability.summarize(rows,2)['passed']
    rows=samples();rows[-1]['state'].pop('droppedFrames')
    assert not stability.summarize(rows,2)['passed']


def test_encoder_rate_uses_counter_observation_time_not_poll_time():
    rows=samples()
    rows[0]['state']['lastFrameAgeSeconds']=.8
    rows[-1]['state']['lastFrameAgeSeconds']=.2
    rows[-1]['state']['frame']=156
    r=stability.summarize(rows,2)
    assert abs(r['encodeFps']-60)<1e-9
    assert abs(r['encoderCounterIntervalSeconds']-2.6)<1e-9
