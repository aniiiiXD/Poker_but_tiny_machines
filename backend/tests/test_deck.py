"""Shared token engine: determinism, dealing, drawing, hands, and piles."""
import json

import pytest

from arena.games.common.deck import (
    RANKS,
    SUITS,
    Deck,
    Hand,
    Pile,
    contract_sort_key,
    standard_deck,
)


def test_standard_deck_is_52_unique_contract_cards():
    cards = standard_deck()
    assert len(cards) == 52
    assert len(set(cards)) == 52
    assert set(cards) == {rank + suit for rank in RANKS for suit in SUITS}
    assert cards[0] == "Ac" and cards[-1] == "Ks"


def test_contract_sort_key_orders_rank_then_suit():
    hand = ["Ks", "2h", "As", "Td", "Ac", "2c"]
    assert sorted(hand, key=contract_sort_key) == ["Ac", "As", "2c", "2h", "Td", "Ks"]
    assert len({contract_sort_key(card) for card in standard_deck()}) == 52


def test_same_seed_shuffles_identically():
    first = Deck(standard_deck(), seed=42)
    second = Deck(standard_deck(), seed=42)
    first.shuffle()
    second.shuffle()
    assert first.draw(52) == second.draw(52)


def test_different_seeds_shuffle_differently():
    orders = []
    for seed in (1, 2, 3):
        deck = Deck(standard_deck(), seed=seed)
        deck.shuffle()
        orders.append(deck.draw(52))
    pairs = [(orders[0], orders[1]), (orders[0], orders[2]), (orders[1], orders[2])]
    assert any(a != b for a, b in pairs)


def test_reseed_pins_the_stream_for_later_shuffles():
    first = Deck(standard_deck(), seed=1)
    second = Deck(standard_deck(), seed=999)
    first.draw(5)
    second.draw(5)  # both now hold the same remaining order
    first.reseed(31337)
    second.reseed(31337)
    first.shuffle()
    second.shuffle()
    assert first.draw(47) == second.draw(47)


def test_deck_copies_input_tokens():
    tokens = ["Ac", "Ad", "Ah"]
    deck = Deck(tokens, seed=0)
    tokens.append("As")
    assert deck.remaining == 3


def test_draw_pops_from_the_top_in_order():
    deck = Deck(["Ac", "Ad", "Ah"], seed=0)
    assert deck.draw(2) == ["Ac", "Ad"]
    assert deck.draw() == ["Ah"]


def test_overdraw_raises_and_leaves_deck_untouched():
    deck = Deck(["Ac", "Ad"], seed=0)
    with pytest.raises(ValueError):
        deck.draw(3)
    assert deck.remaining == 2
    assert deck.draw(2) == ["Ac", "Ad"]


def test_draw_until_empty_then_raises():
    deck = Deck(standard_deck(), seed=7)
    deck.shuffle()
    drawn: list[str] = []
    for _ in range(52):
        drawn.extend(deck.draw())
    assert len(drawn) == 52 and len(set(drawn)) == 52
    assert deck.remaining == 0
    with pytest.raises(ValueError):
        deck.draw()


def test_discard_returns_cards_and_they_can_be_drawn_again():
    deck = Deck(["Ac", "Ad", "Ah", "As"], seed=5)
    assert deck.draw(4) == ["Ac", "Ad", "Ah", "As"]
    assert deck.remaining == 0
    deck.discard(["Ac", "Ad"])
    deck.discard("Ah")  # a single card is accepted too
    assert deck.remaining == 3
    assert deck.draw(3) == ["Ac", "Ad", "Ah"]
    with pytest.raises(ValueError):
        deck.draw()


def test_deal_four_seats_conserves_all_52_cards():
    deck = Deck(standard_deck(), seed=11)
    deck.shuffle()
    hands = deck.deal(4)
    assert [len(hand) for hand in hands] == [13, 13, 13, 13]
    assert deck.remaining == 0
    combined = [card for hand in hands for card in hand.to_list()]
    assert len(combined) == 52 and len(set(combined)) == 52
    assert set(combined) == set(standard_deck())
    for hand in hands:
        assert hand.to_list() == sorted(hand.to_list(), key=contract_sort_key)


def test_deal_round_robin_gives_leftovers_to_early_seats():
    cards = standard_deck()[:10]
    hands = Deck(cards, seed=0).deal(3)
    assert [len(hand) for hand in hands] == [4, 3, 3]
    assert set(hands[0]) == {"Ac", "As", "2h", "3d"}  # deal positions 0, 3, 6, 9
    assert set(hands[1]) == {"Ad", "2c", "2s"}
    assert set(hands[2]) == {"Ah", "2d", "3c"}


def test_deal_requires_at_least_one_seat():
    with pytest.raises(ValueError):
        Deck(["Ac"], seed=0).deal(0)


def test_hand_add_keeps_contract_order_from_unsorted_input():
    hand = Hand(["Td", "2h"])  # unsorted input is normalized
    assert hand.to_list() == ["2h", "Td"]
    hand.add("As")
    assert hand.to_list() == ["As", "2h", "Td"]
    hand.add("2c")
    assert hand.to_list() == ["As", "2c", "2h", "Td"]
    assert "2h" in hand and "9d" not in hand
    assert len(hand) == 4


def test_hand_remove_missing_raises_keyerror():
    hand = Hand(["Ac"])
    hand.remove("Ac")
    assert len(hand) == 0
    with pytest.raises(KeyError):
        hand.remove("Ac")


def test_hand_counts_duplicates():
    hand = Hand(["Ac", "Ad", "Ac"])
    assert hand.count("Ac") == 2
    assert hand.count("Ad") == 1
    assert hand.count("Ah") == 0
    hand.remove("Ac")
    assert hand.count("Ac") == 1 and len(hand) == 2


def test_hand_sort_pluggable_key_becomes_default():
    hand = Hand(["2h", "As"])
    assert hand.to_list() == ["As", "2h"]  # contract default: rank before suit
    hand.sort(key=lambda card: SUITS.index(card[1]))
    assert hand.to_list() == ["2h", "As"]  # re-sorted by suit only
    hand.add("2c")
    assert hand.to_list() == ["2c", "2h", "As"]  # later adds follow the new key


def test_pile_add_take_all_size():
    pile = Pile()
    assert pile.size == 0
    pile.add(["Ac", "2d"])
    pile.add("5h")
    assert pile.size == 3
    assert pile.take_all() == ["Ac", "2d", "5h"]  # played order, bottom first
    assert pile.size == 0
    assert pile.take_all() == []


def test_everything_is_json_serializable():
    deck = Deck(standard_deck(), seed=3)
    deck.shuffle()
    payload = {
        "remaining": deck.remaining,
        "hands": [hand.to_list() for hand in deck.deal(4)],
        "pile": Pile(["Ac", "2d"]).take_all(),
    }
    assert json.loads(json.dumps(payload)) == payload
