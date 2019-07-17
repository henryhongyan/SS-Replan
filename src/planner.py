import cProfile
import pstats

from pddlstream.algorithms.constraints import PlanConstraints
from pddlstream.algorithms.focused import solve_focused
from pddlstream.algorithms.incremental import solve_incremental
from pddlstream.language.constants import print_solution
from pddlstream.language.stream import StreamInfo
from pddlstream.language.function import FunctionInfo
from pddlstream.utils import INF
from pybullet_tools.utils import LockRenderer, WorldSaver, wait_for_user, VideoSaver
from src.command import Wait, State, execute_plan
from src.stream import BASE_CONSTANT

VIDEO_FILENAME = 'video.mp4'
REPLAN_ACTIONS = {'calibrate'}


def solve_pddlstream(problem, args, success_cost=INF, debug=False):
    _, _, _, stream_map, init, goal = problem
    print('Init:', init)
    print('Goal:', goal)
    print('Streams:', stream_map.keys())

    stream_info = {
        'test-gripper': StreamInfo(p_success=0, eager=True),
        'test-door': StreamInfo(p_success=0, eager=True),
        'test-near-pose': StreamInfo(p_success=0, eager=True),
        'test-near-joint': StreamInfo(p_success=0, eager=True),

        'compute-pose-kin': StreamInfo(p_success=0.5, eager=True),
        'compute-angle-kin': StreamInfo(p_success=0.5, eager=True),

        'plan-pick': StreamInfo(overhead=1e1),
        'plan-pull': StreamInfo(overhead=1e1),

        'plan-base-motion': StreamInfo(overhead=1e3, defer=True),
        'plan-arm-motion': StreamInfo(overhead=1e2, defer=True),

        'test-cfree-pose-pose': StreamInfo(p_success=1e-3, negate=True),
        'test-cfree-approach-pose': StreamInfo(p_success=1e-2, negate=True),
        'test-cfree-traj-pose': StreamInfo(p_success=1e-1, negate=True),
        'Distance': FunctionInfo(p_success=0.99, opt_fn=lambda bq1, bq2: BASE_CONSTANT),
        # 'MoveCost': FunctionInfo(lambda t: BASE_CONSTANT),
    }
    replan_actions = REPLAN_ACTIONS if args.defer else set()

    #constraints = PlanConstraints(skeletons=[skeleton], exact=True)
    constraints = PlanConstraints()

    success_cost = 0 if args.optimal else success_cost
    planner = 'max-astar' if args.optimal else 'ff-wastar1'
    search_sample_ratio = 1 # TODO: could try decreasing
    max_planner_time = 10

    pr = cProfile.Profile()
    pr.enable()
    with LockRenderer(lock=not args.visualize):
        saver = WorldSaver()
        if args.algorithm == 'focused':
            # TODO: option to only consider costs during local optimization
            # effort_weight = 0 if args.optimal else 1
            #effort_weight = 1e-3 if args.optimal else 1
            effort_weight = 0
            solution = solve_focused(problem, constraints=constraints, stream_info=stream_info,
                                     replan_actions=replan_actions,
                                     # TODO: start complexity
                                     planner=planner, max_planner_time=max_planner_time,
                                     unit_costs=args.unit, success_cost=success_cost,
                                     max_time=args.max_time, verbose=True, debug=debug,
                                     unit_efforts=True, effort_weight=effort_weight,
                                     # bind=True, max_skeletons=None,
                                     search_sample_ratio=search_sample_ratio)
        elif args.algorithm == 'incremental':
            solution = solve_incremental(problem, constraints=constraints,
                                         planner=planner, max_planner_time=max_planner_time,
                                         unit_costs=args.unit, success_cost=success_cost,
                                         max_time=args.max_time, verbose=True, debug=debug)
        else:
            raise ValueError(args.algorithm)
        saver.restore()

    # print([(s.cost, s.time) for s in SOLUTIONS])
    # print(SOLUTIONS)
    print_solution(solution)
    pr.disable()
    pstats.Stats(pr).sort_stats('tottime').print_stats(25)  # cumtime | tottime
    return solution

################################################################################

def commands_from_plan(world, plan, defer=False):
    if plan is None:
        return None
    # TODO: propagate the state
    commands = []
    for action, params in plan:
        if action in ['move_base', 'move_arm', 'move_gripper', 'pick', 'pull', 'calibrate']:
            commands.extend(params[-1].commands)
        elif action == 'place':
            commands.extend(params[-1].reverse().commands)
        elif action in ['cook']:
            commands.append(Wait(world, steps=100))
        else:
            raise NotImplementedError(action)
        if defer and (action in REPLAN_ACTIONS):
            break
    return commands

################################################################################

def simulate_plan(state, commands, args, time_step=0.02):
    wait_for_user()
    if commands is None:
        return
    time_step = None if args.teleport else time_step
    if args.record:
        with VideoSaver(VIDEO_FILENAME):
            execute_plan(state, commands, time_step=time_step)
    else:
        execute_plan(state, commands, time_step=time_step)