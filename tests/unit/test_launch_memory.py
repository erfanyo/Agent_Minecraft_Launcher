"""Window readiness and memory policy require neither a GUI nor a live game."""
from launcher_app.runtime.launch_memory import heap_limit, WindowReadinessTracker, WindowReadiness, assess_launch_memory


def test_window_must_remain_visible_and_exit_is_not_readiness():
    tracker=WindowReadinessTracker(0)
    assert tracker.observe(now=1,running=True,visible=True) is WindowReadiness.WAIT
    assert tracker.observe(now=9,running=True,visible=False) is WindowReadiness.WAIT
    assert tracker.observe(now=10,running=True,visible=True) is WindowReadiness.WAIT
    assert tracker.observe(now=19,running=True,visible=True) is WindowReadiness.WAIT
    assert tracker.observe(now=20,running=True,visible=True) is WindowReadiness.READY
    assert tracker.observe(now=21,running=False,visible=True) is WindowReadiness.EXITED


def test_timeout_keeps_launcher_available():
    tracker=WindowReadinessTracker(0)
    assert tracker.observe(now=181,running=True,visible=False) is WindowReadiness.TIMED_OUT


def test_memory_inputs_and_default_heap():
    assert heap_limit(['java','-Xmx8G','Main'])==8
    assert heap_limit(['java','Main'])==2
    seen=[]
    result=assess_launch_memory(['-Xmx6G'],'history','game',sampler=lambda:(16,3),
        budgeter=lambda **kwargs:{'gb':4,'desired_gb':5},
        history_reader=lambda path:seen.append(path) or 0,
        mod_counter=lambda path:seen.append(path) or 10,
        pressure_reader=lambda available,heap,desired:2)
    assert seen==['history','game']
    assert (result.heap,result.level,result.state)==(6,2,(16,3))
