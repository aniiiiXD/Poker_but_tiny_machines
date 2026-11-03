# Rummy model starter (Stack Theory Rummy v1)

A bounded multi-file project template for the model track: `agent.py` plus a
local `weights.json` artifact. The runtime provides Python 3.12 and NumPy;
no network, no GPU. Package the folder as a ZIP (with `agent.py` at the
root) and upload it in the Workshop with the Rummy game selected.

## How it plays

- Every card gets a linear **keep score** from hand-crafted features (face
  points, rank mates, suit neighbors, joker flag) dotted with `weights.json`
  — that is the whole model.
- **Draw:** take the public discard top when its keep score clears
  `take_threshold`, otherwise pull from the stock.
- **Discard:** shed the lowest-scoring natural card, so jokers and connected
  cards survive.
- **Declare:** a bounded meld search verifies that all 14 cards form at
  least two sequences (one pure) before declaring — this template can never
  make a wrong show, it only misses some winnable hands. That search is
  where your own model should improve things.

Replace the features and weights with your own trained model — training
happens on your machine; only the inference artifact is submitted.
