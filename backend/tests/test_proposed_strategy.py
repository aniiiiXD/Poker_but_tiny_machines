from experiments.aggression_bluff_bot import Agent, hand_category


def observation(hole, board, *, to_call=0, pot=200, stack=1000, raises=0):
    actions = ['fold', 'call', 'raise'] if to_call else ['check', 'raise']
    return {'hand': 1, 'street': 'flop' if board else 'preflop', 'seat': 0, 'button': 1,
            'hole_cards': hole, 'board': board, 'pot': pot, 'stack': stack, 'to_call': to_call,
            'min_raise': 40, 'max_raise': 1000, 'legal_actions': actions, 'players': [],
            'history': [{'seat': i + 1, 'street': 'flop' if board else 'preflop', 'action': 'raise',
                         'amount': 50} for i in range(raises)]}


def test_hand_categories_include_wheel_and_flush():
    assert hand_category(['As', 'Ad', 'Kc', 'Kh', '2d']) == 2
    assert hand_category(['As', 'Ad', 'Ac', 'Kh', '2d']) == 3
    assert hand_category(['As', '2d', '3c', '4h', '5s']) == 4
    assert hand_category(['As', 'Ts', '8s', '4s', '2s']) == 5
    assert hand_category(['As', 'Ad', 'Ac', 'Kh', 'Kd']) == 6
    assert hand_category(['As', '2s', '3s', '4s', '5s']) == 8


def test_two_pair_folds_to_super_aggressive_bet():
    obs = observation(['As', 'Kd'], ['Ac', 'Kh', '2d'], to_call=450, raises=2)
    assert Agent().act(obs) == {'action': 'fold'}


def test_three_of_kind_plays_aggressively():
    obs = observation(['As', 'Ad'], ['Ac', 'Kh', '2d'], to_call=50)
    assert Agent().act(obs) == {'action': 'raise', 'amount': 40}


def test_bot_returns_legal_actions_and_reproducible_choices():
    one, two = Agent(), Agent()
    cases = [observation(['As', 'Kd'], [], to_call=20),
             observation(['3s', '7d'], ['Ac', 'Kh', '2d']),
             observation(['As', 'Kd'], ['Ac', 'Kh', '2d'], to_call=20)]
    for obs in cases * 30:
        a, b = one.act(obs), two.act(obs)
        assert a == b
        assert a['action'] in obs['legal_actions']
        if a['action'] == 'raise':
            assert obs['min_raise'] <= a['amount'] <= obs['max_raise']


class ScriptedRandom:
    def __init__(self, values):
        self.values = iter(values)

    def random(self):
        return next(self.values)


def test_random_guess_and_bluff_follow_threshold():
    weak = observation(['3s', '7d'], ['Ac', 'Kh', '2d'])
    bot = Agent()
    bot.rng = ScriptedRandom([0.1, 0.7])
    assert bot.act(weak)['action'] == 'raise'
    bot.rng = ScriptedRandom([0.1, 0.3])
    assert bot.act(weak)['action'] == 'check'

    pair = observation(['As', '7d'], ['Ac', 'Kh', '2d'], to_call=25, pot=150)
    bot.rng = ScriptedRandom([0.1, 0.7])
    assert bot.act(pair)['action'] == 'call'
    bot.rng = ScriptedRandom([0.1, 0.3])
    assert bot.act(pair)['action'] == 'fold'
