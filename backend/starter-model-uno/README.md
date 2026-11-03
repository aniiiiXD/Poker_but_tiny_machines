# UNO model starter (Stack Theory UNO v1 — rules prototype)

A bounded multi-file project template for the model track: `agent.py` plus a
local `weights.json` artifact. The runtime provides Python 3.12 and NumPy; no
network, no GPU. Package the folder as a ZIP (with `agent.py` at the root)
and upload it in the Workshop with the UNO game selected.

The starter scores every legal card with a linear model over hand-crafted
features (color match, face match, action card, wild, own color counts) and
plays the best above `play_threshold`, otherwise draws. Wilds are hoarded
while the hand is larger than `keep_wild_hand_max`; the challenge window uses
a second linear score. See `backend/arena/games/uno/RULES.md` for the exact
rules and observation schema.

Replace the features and weights with your own trained model — training
happens on your machine; only the inference artifact is submitted.
