"""Deterministic no-limit Hold'em tables using PokerKit for the rules."""
from __future__ import annotations

import random
from functools import lru_cache

from pokerkit import Automation, NoLimitTexasHoldem

from .sandbox import SandboxDown

_AUTOMATIONS = (Automation.ANTE_POSTING, Automation.BET_COLLECTION,
                Automation.BLIND_OR_STRADDLE_POSTING, Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
                Automation.HAND_KILLING, Automation.CHIPS_PUSHING, Automation.CHIPS_PULLING)
_PAYOUTS = (8, 5, 3, 2, 1, 0, 0, 0)


def _icm(stacks: list[int], payouts: list[int]) -> list[float]:
    """Exact independent chip model, assigning each surviving player expected payout."""
    n = len(stacks)
    @lru_cache(None)
    def walk(mask: int, place: int) -> tuple[float, ...]:
        result = [0.0] * n
        total = sum(stacks[i] for i in range(n) if mask & (1 << i))
        if not total or place >= len(payouts):
            return tuple(result)
        for i in range(n):
            if not mask & (1 << i):
                continue
            probability = stacks[i] / total
            result[i] += probability * payouts[place]
            sub = walk(mask ^ (1 << i), place + 1)
            for j in range(n):
                result[j] += probability * sub[j]
        return tuple(result)
    return list(walk((1 << n) - 1, 0))


def play_table(bots: list, seed: int, max_hands: int = 200, starting_stack: int = 2000, capture: bool = False) -> dict:
    n = len(bots)
    if not 2 <= n <= 8 or max_hands < 1 or starting_stack < 1:
        raise ValueError('Expected 2–8 bots, positive max_hands and starting_stack')
    rng = random.Random(seed)
    stacks = [starting_stack] * n
    faults = [0] * n
    errors = [None] * n
    points = [0.0] * n
    frames = []
    hand_log = []
    reset_failed = [False] * n
    for i, bot in enumerate(bots):
        try:
            bot.reset()
        except SandboxDown:
            # Infrastructure, not a bot fault: never score a doomed table.
            raise
        except Exception as exc:
            faults[i] += 1
            reset_failed[i] = True
            errors[i] = str(exc)[:200]
    button = n - 1
    hands = 0
    for hand in range(1, max_hands + 1):
        alive = [i for i in range(n) if stacks[i] > 0]
        if len(alive) <= 1:
            break
        # Button advances to the next surviving seat, including across eliminations.
        button = next((button + k) % n for k in range(1, n + 1) if (button + k) % n in alive)
        if len(alive) == 2:
            # PokerKit reverses the two blind indices heads-up: index 1 is
            # the button/small blind and acts first preflop.
            order = [i for i in alive if i != button] + [button]
        else:
            order = sorted(alive, key=lambda i: (i - button - 1) % n)
        blind = 10 * (2 ** ((hand - 1) // 25))
        state = NoLimitTexasHoldem.create_state(_AUTOMATIONS, True, 0, (blind, blind * 2), blind * 2,
                                                [stacks[i] for i in order], len(order))
        deck = [r + s for r in '23456789TJQKA' for s in 'cdhs']
        rng.shuffle(deck)
        deck_iter = iter(deck)
        hole = {}
        while state.can_deal_hole():
            local = state.hole_dealee_index
            cards = [next(deck_iter), next(deck_iter)]
            hole[order[local]] = cards
            state.deal_hole(''.join(cards))
        history = []
        hand_frames = []
        def street():
            count = len(list(state.get_board_cards(0)))
            return 'river' if count >= 5 else 'turn' if count == 4 else 'flop' if count >= 3 else 'preflop'
        def snapshot(actor, action, frame_street=None):
            if not capture:
                return
            board = [repr(c) for c in state.get_board_cards(0)]
            local_by_global = {seat: j for j, seat in enumerate(order)}
            seats = []
            for seat in range(n):
                j = local_by_global.get(seat)
                seats.append({'name': str(getattr(bots[seat], 'name', f'Bot {seat + 1}')),
                              'stack': int(state.stacks[j]) if j is not None else 0,
                              'bet': int(state.bets[j]) if j is not None else 0,
                              'folded': not state.statuses[j] if j is not None else True,
                              'cards': hole.get(seat, [])})
            hand_frames.append({'hand': hand, 'street': frame_street or street(), 'board': board,
                                'pot': int(state.total_pot_amount), 'actor': actor,
                                'action': action, 'seats': seats})
        snapshot(None, 'Hand dealt')
        while state.status:
            if state.can_burn_card():
                state.burn_card(next(deck_iter))
            elif state.can_deal_board():
                state.deal_board(''.join(next(deck_iter) for _ in range(state.board_dealing_count)))
                snapshot(None, 'Board dealt')
            elif state.actor_index is not None:
                j = state.actor_index
                seat = order[j]
                to_call = int(state.checking_or_calling_amount or 0)
                legal = []
                if state.can_fold(): legal.append('fold')
                if state.can_check_or_call(): legal.append('check' if to_call == 0 else 'call')
                if state.can_complete_bet_or_raise_to(): legal.append('raise')
                minimum = state.min_completion_betting_or_raising_to_amount if 'raise' in legal else None
                maximum = state.max_completion_betting_or_raising_to_amount if 'raise' in legal else None
                observation = {'hand': hand, 'street': street(), 'seat': seat, 'button': button,
                    'hole_cards': hole[seat][:], 'board': [repr(c) for c in state.get_board_cards(0)],
                    'pot': int(state.total_pot_amount), 'stack': int(state.stacks[j]), 'to_call': to_call,
                    'min_raise': int(minimum) if minimum is not None else None,
                    'max_raise': int(maximum) if maximum is not None else None, 'legal_actions': legal[:],
                    'players': [{'seat': order[k], 'stack': int(state.stacks[k]), 'bet': int(state.bets[k]),
                                 'folded': not state.statuses[k]} for k in range(len(order))],
                    'history': [dict(item) for item in history]}
                try:
                    if reset_failed[seat]:
                        raise ValueError('reset failed')
                    decision = bots[seat].act(observation)
                    if not isinstance(decision, dict): raise ValueError('invalid response')
                    action = decision.get('action')
                    if action not in legal: raise ValueError('illegal action')
                    amount = decision.get('amount')
                    if action == 'raise' and (type(amount) is not int or not state.can_complete_bet_or_raise_to(amount)):
                        raise ValueError('illegal raise')
                except Exception as exc:
                    faults[seat] += 1
                    if errors[seat] is None:
                        errors[seat] = str(exc)[:200]
                    action = 'check' if 'check' in legal else 'fold'
                    amount = None
                action_street = street()
                if action == 'fold': state.fold()
                elif action in ('check', 'call'): state.check_or_call()
                else: state.complete_bet_or_raise_to(amount)
                history.append({'seat': seat, 'action': action, 'amount': amount if action == 'raise' else None,
                                'street': action_street})
                snapshot(seat, f'{action.title()}' + (f' to {amount}' if action == 'raise' else ''), action_street)
            else:
                raise RuntimeError('PokerKit stalled without an operation')
        for j, seat in enumerate(order): stacks[seat] = int(state.stacks[j])
        # Simultaneous eliminations finish in starting-stack order, sharing ties.
        busted = [seat for seat in order if stacks[seat] == 0]
        if busted:
            # Elimination payout slots are occupied from the bottom up.
            prior_alive = len(order)
            for initial in sorted({int(state.starting_stacks[order.index(i)]) for i in busted}):
                group = [i for i in busted if int(state.starting_stacks[order.index(i)]) == initial]
                values = [_PAYOUTS[pos - 1] for pos in range(prior_alive - len(group) + 1, prior_alive + 1)]
                for seat in group: points[seat] = sum(values) / len(group)
                prior_alive -= len(group)
        snapshot(None, 'Hand complete')
        frames.extend(hand_frames)
        hand_log.append({
            'hand': hand,
            'blinds': [blind, blind * 2],
            'board': [repr(card) for card in state.get_board_cards(0)],
            'actions': [dict(item) for item in history],
            'busted': busted,
        })
        hands = hand
    alive = [i for i in range(n) if stacks[i] > 0]
    equity = _icm([stacks[i] for i in alive], list(_PAYOUTS[:len(alive)]))
    for i, value in zip(alive, equity): points[i] = value
    return {'points': points, 'chips': stacks, 'faults': faults, 'errors': errors, 'log': hand_log, 'frames': frames, 'hands': hands}
