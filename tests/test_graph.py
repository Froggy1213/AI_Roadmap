"""Tests for topological sort, graph validation, state derivation, and layout."""

import pytest

from app.graph import (
    CANVAS_BOTTOM_PAD,
    CENTER_Y,
    MARGIN_X,
    MIN_CANVAS_H,
    NODE_W,
    PITCH_X,
    PITCH_Y,
    GraphError,
    compute_layout,
    derive_states,
    edge_style,
    topo_sort,
    validate_graph,
)


class TestTopoSort:
    def test_linear_chain(self):
        ids = [1, 2, 3, 4]
        edges = [(1, 2), (2, 3), (3, 4)]
        assert topo_sort(ids, edges) == [1, 2, 3, 4]

    def test_diamond(self):
        ids = [1, 2, 3, 4]
        edges = [(1, 2), (1, 3), (2, 4), (3, 4)]
        order = topo_sort(ids, edges)
        assert order[0] == 1
        assert order[-1] == 4
        assert set(order[1:3]) == {2, 3}

    def test_single_node(self):
        assert topo_sort([1], []) == [1]

    def test_cycle_raises(self):
        ids = [1, 2, 3]
        edges = [(1, 2), (2, 3), (3, 1)]
        with pytest.raises(GraphError, match="cycle"):
            topo_sort(ids, edges)

    def test_bogus_edge_raises(self):
        with pytest.raises(GraphError, match="unknown module"):
            topo_sort([1, 2], [(1, 99)])


class TestValidateGraph:
    def test_valid_graph(self):
        ids = list(range(10))
        edges = [(i, i + 1) for i in range(9)]  # linear chain
        assert validate_graph(ids, edges) == []

    def test_too_few_modules(self):
        problems = validate_graph([1, 2], [(1, 2)], min_nodes=8)
        assert any("8" in p for p in problems)

    def test_too_many_modules(self):
        ids = list(range(30))
        edges = [(i, i + 1) for i in range(29)]
        problems = validate_graph(ids, edges, max_nodes=24)
        assert any("24" in p for p in problems)

    def test_missing_root(self):
        ids = [1, 2, 3]
        edges = [(1, 2), (2, 3), (3, 1)]  # cycle → no root
        problems = validate_graph(ids, edges, min_nodes=1)
        assert any("cycle" in p for p in problems)

    def test_self_loop(self):
        problems = validate_graph([1, 2, 3, 4, 5, 6, 7, 8], [(1, 1)])
        assert any("itself" in p for p in problems)

    def test_dangling_prereq(self):
        ids = [1, 2, 3, 4, 5, 6, 7, 8]
        problems = validate_graph(ids, [(99, 1)])
        assert any("99" in p for p in problems)

    def test_multiple_roots(self):
        ids = list(range(10))
        edges = [(2, 3), (3, 4)]  # 1 and 2 are both roots
        problems = validate_graph(ids, edges)
        assert any("starting module" in p for p in problems)

    def test_multiple_leaves(self):
        ids = list(range(10))
        edges = [(1, i) for i in range(2, 10)]  # many leaves
        problems = validate_graph(ids, edges)
        assert any("capstone" in p for p in problems)


class TestDeriveStates:
    def _info(self, **overrides):
        d = {
            "est_sessions": 5,
            "done_sessions": 0,
            "sticky_stuck": False,
            "manual_completed": False,
            "children_total": 0,
            "children_completed": 0,
        }
        d.update(overrides)
        return d

    def test_locked_by_default(self):
        # A module with prereqs that aren't done is locked
        states = derive_states(
            [1, 2], [(1, 2)],
            {1: self._info(), 2: self._info()}
        )
        assert states[2] == "locked"

    def test_available_when_no_prereqs(self):
        # A module with no prerequisites is available (even with 0 done sessions)
        states = derive_states([1], [], {1: self._info()})
        assert states[1] == "available"
        # Wait — lookup `derive_states`: rule 5 says "every prereq completed
        # or inprogress → available". With no prereqs, that's vacuously true.
        # But rule 6 (otherwise → locked) catches 0 sessions.
        # Actually let me re-read derive_states:
        # - children completed → completed
        # - sticky_stuck → stuck
        # - manual_completed or done_sessions >= est_sessions → completed
        # - done_sessions > 0 → inprogress
        # - every prereq completed/inprogress → available   <-- no prereqs = vacuously true
        # - otherwise → locked
        # So a module with 0 prereqs AND 0 done IS available.
        assert states[1] == "available"

    def test_inprogress_after_session(self):
        states = derive_states(
            [1], [], {1: self._info(done_sessions=1)}
        )
        assert states[1] == "inprogress"

    def test_completed_when_all_sessions_done(self):
        states = derive_states(
            [1], [], {1: self._info(done_sessions=5, est_sessions=5)}
        )
        assert states[1] == "completed"

    def test_stuck_overrides_progress(self):
        states = derive_states(
            [1], [], {1: self._info(done_sessions=3, sticky_stuck=True)}
        )
        assert states[1] == "stuck"

    def test_chain_progression(self):
        # 1 → 2 → 3, only module 1 has sessions done
        ids = [1, 2, 3]
        edges = [(1, 2), (2, 3)]
        info = {
            1: self._info(done_sessions=1),  # inprogress
            2: self._info(),                  # 0 done, prereq inprogress → available
            3: self._info(),                  # 0 done, prereq not started → locked
        }
        states = derive_states(ids, edges, info)
        assert states[1] == "inprogress"
        assert states[2] == "available"
        assert states[3] == "locked"

    def test_split_parent_completed_after_children(self):
        # Parent has 2 children, both completed
        info = {
            1: self._info(children_total=2, children_completed=2),
        }
        states = derive_states([1], [], info)
        assert states[1] == "completed"


class TestComputeLayout:
    def test_single_node(self):
        pos, canvas = compute_layout([1], [])
        assert 1 in pos
        x, y = pos[1]
        assert x == MARGIN_X
        assert canvas["height"] >= MIN_CANVAS_H
        assert canvas["width"] == MARGIN_X * 2 + NODE_W

    def test_two_layer_graph(self):
        ids = [1, 2, 3, 4]
        edges = [(1, 3), (1, 4), (2, 3)]  # layer 0: 1,2 → layer 1: 3,4
        pos, canvas = compute_layout(ids, edges)
        x_positions = [pos[n][0] for n in ids]
        # 1 and 2 should be in layer 0 (same x)
        assert pos[1][0] == pos[2][0] == MARGIN_X
        # 3 and 4 should be in layer 1
        assert pos[3][0] == pos[4][0] == MARGIN_X + PITCH_X

    def test_vertical_spread(self):
        ids = [1, 2, 3]
        edges = [(1, 2), (2, 3)]
        pos, _ = compute_layout(ids, edges)
        # 3 nodes in 3 different layers, each centered around CENTER_Y
        assert pos[1][1] == CENTER_Y
        assert pos[2][1] == CENTER_Y
        assert pos[3][1] == CENTER_Y

    def test_empty_graph(self):
        pos, canvas = compute_layout([], [])
        assert pos == {}
        assert canvas["width"] == NODE_W + 2 * MARGIN_X
        assert canvas["height"] == MIN_CANVAS_H


class TestEdgeStyle:
    def test_done_edge(self):
        assert edge_style("completed", "inprogress") == "done"

    def test_active_edge(self):
        assert edge_style("inprogress", "available") == "active"

    def test_stuck_target(self):
        # stuck target wins regardless of source
        assert edge_style("completed", "stuck") == "stuck"
        assert edge_style("locked", "stuck") == "stuck"

    def test_locked_by_default(self):
        assert edge_style("locked", "locked") == "locked"
