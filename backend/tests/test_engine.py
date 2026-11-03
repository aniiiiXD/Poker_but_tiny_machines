import pytest

from arena.baselines import make_baselines
from arena.engine import _icm, play_table
from arena.sandbox import SandboxDown


class AllIn:
    name = 'All-in'
    def reset(self):
        self.observations = []
    def act(self, observation):
        self.observations.append(observation)
        if 'raise' in observation['legal_actions']:
            return {'action': 'raise', 'amount': observation['max_raise']}
        if 'call' in observation['legal_actions']:
            return {'action': 'call'}
        return {'action': 'check'}


class Broken:
    name = 'Broken'
    def reset(self): pass
    def act(self, observation): raise RuntimeError('crash')


def test_reproducibility_conservation_and_privacy():
    bots = [AllIn() for _ in range(5)]
    first = play_table(bots, 100, max_hands=10, capture=True)
    assert first == play_table([AllIn() for _ in range(5)], 100, max_hands=10, capture=True)
    assert sum(first['chips']) == 10000
    assert abs(sum(first['points']) - 19) < 1e-8
    assert first['frames'] and any(frame['seats'][0]['cards'] for frame in first['frames'])
    for bot in bots:
        for obs in bot.observations:
            assert set(obs) == {'hand', 'street', 'seat', 'button', 'hole_cards', 'board', 'pot', 'stack', 'to_call', 'min_raise', 'max_raise', 'legal_actions', 'players', 'history'}
            assert all(set(p) == {'seat', 'stack', 'bet', 'folded'} for p in obs['players'])
            assert len(obs['hole_cards']) == 2


def test_fault_fallback_and_normal_baselines():
    result = play_table([Broken(), *make_baselines(3)], 33, max_hands=8, capture=True)
    assert result['faults'][0] > 0
    assert result['faults'][1:] == [0, 0, 0]
    assert sum(result['chips']) == 8000
    assert any(f['actor'] == 0 and f['action'] in ('Check', 'Fold') for f in result['frames'])


def test_icm_equal_and_unequal():
    assert _icm([100, 100], [8, 5]) == [6.5, 6.5]
    assert _icm([300, 100], [8, 5]) == [7.25, 5.75]


def test_heads_up_button_posts_small_blind_and_acts_first():
    bots = [AllIn(), AllIn()]
    result = play_table(bots, 8, max_hands=1, capture=True)
    first = next(frame for frame in result['frames'] if frame['actor'] is not None)
    button = next(obs['button'] for bot in bots for obs in bot.observations)
    assert first['actor'] == button
    initial = result['frames'][0]
    assert initial['seats'][button]['bet'] == 10
    assert initial['seats'][1 - button]['bet'] == 20


def test_reset_failure_isolated_and_faulted():
    class ResetBroken(Broken):
        def reset(self): raise RuntimeError('reset failed')
        def act(self, observation): raise AssertionError('must not call')
    result = play_table([ResetBroken(), *make_baselines(2)], 42, max_hands=4)
    assert result['faults'][0] >= 1
    assert result['faults'][1:] == [0, 0]
    assert sum(result['chips']) == 6000


def test_first_error_is_captured_for_practice_feedback():
    result = play_table([Broken(), *make_baselines(3)], 33, max_hands=4)
    assert result['faults'][0] > 0
    assert result['errors'][0] == 'crash'
    assert result['errors'][1:] == [None, None, None]


def test_sandbox_down_aborts_table_instead_of_scoring_folds():
    class Down:
        name = 'Down'
        def reset(self): raise SandboxDown('Unable to start Docker sandbox')
        def act(self, observation): raise AssertionError('must not be called')
    with pytest.raises(SandboxDown):
        play_table([Down(), *make_baselines(3)], 5, max_hands=4)


def test_known_all_in_hand_and_equal_stack_elimination_tie(monkeypatch):
    # In the first three-handed deal, seats 1, 2, 0 receive AA, KK, QQ.
    cards = ['Ac', 'Ad', 'Kc', 'Kd', 'Qc', 'Qd', '2c', '3c', '4d', '8h', '5s', '9c', '6s', 'Th']
    def ordered_deck(_rng, deck):
        deck[:] = cards + [card for card in deck if card not in cards]
    monkeypatch.setattr('arena.engine.random.Random.shuffle', ordered_deck)
    result = play_table([AllIn(), AllIn(), AllIn()], 1, max_hands=1, capture=True)
    assert result['chips'] == [0, 6000, 0]
    assert result['points'] == [4, 8, 4]  # tied second/third share (5 + 3) / 2
    assert result['frames'][-1]['board'] == ['3c', '4d', '8h', '9c', 'Th']


def test_unequal_all_ins_distribute_main_and_side_pots(monkeypatch):
    decks = [
        ['Ac','Ad','Kc','Kd','Qc','Qd','2c','3c','4d','8h','5s','9c','6s','Th'],
        ['Qc','Qd','Ac','Ad','Kc','Kd','2c','3c','4d','8h','5s','9c','6s','Th'],
    ]
    def ordered_deck(_rng, deck):
        prefix = decks.pop(0)
        deck[:] = prefix + [card for card in deck if card not in prefix]
    monkeypatch.setattr('arena.engine.random.Random.shuffle', ordered_deck)
    class Scripted(AllIn):
        def act(self, observation):
            if observation['hand'] == 1:
                if 'raise' in observation['legal_actions'] and not any(h['action'] == 'raise' for h in observation['history']):
                    return {'action': 'raise', 'amount': 200}
                return {'action': 'call' if 'call' in observation['legal_actions'] else 'check'}
            return super().act(observation)
    result = play_table([Scripted(), Scripted(), Scripted()], 1, max_hands=2)
    assert result['chips'] == [5400, 600, 0]
    assert sum(result['chips']) == 6000


def test_all_in_runout_frames_label_the_visible_board():
    result = play_table([AllIn(), AllIn()], 8, max_hands=1, capture=True)
    boards = [frame for frame in result['frames'] if frame['action'] == 'Board dealt']
    assert [(len(frame['board']), frame['street']) for frame in boards] == [(3, 'flop'), (4, 'turn'), (5, 'river')]
    assert result['frames'][-1]['action'] == 'Hand complete'
    assert result['frames'][-1]['street'] == 'river'


def test_hand_log_records_every_hand_without_capture():
    result = play_table([AllIn(), AllIn()], 8, max_hands=3, capture=False)
    assert len(result['log']) == 1  # all-in runout ends in one hand
    entry = result['log'][0]
    assert entry['blinds'] == [10, 20]
    assert len(entry['board']) == 5
    assert entry['actions'] and {'seat', 'action', 'amount', 'street'} == set(entry['actions'][0])
    assert isinstance(entry['busted'], list)


def test_hand_log_spans_multiple_hands():
    class FoldBot:
        name = 'Folder'
        def reset(self): pass
        def act(self, observation):
            return {'action': 'fold'} if 'fold' in observation['legal_actions'] else {'action': 'check'}
    result = play_table([FoldBot(), *make_baselines(3)], 5, max_hands=6, capture=False)
    assert result['hands'] >= 2
    assert len(result['log']) == result['hands']
    assert [entry['hand'] for entry in result['log']] == sorted(entry['hand'] for entry in result['log'])


def test_sandbox_down_during_a_decision_aborts_table():
    class DiesDuringPlay:
        name = 'Down'
        def reset(self): pass
        def act(self, observation): raise SandboxDown('Docker became unavailable')
    with pytest.raises(SandboxDown):
        play_table([DiesDuringPlay(), AllIn()], 5, max_hands=1)
