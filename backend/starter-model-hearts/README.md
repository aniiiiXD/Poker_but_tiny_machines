# Hearts model starter (Stack Theory Hearts v1)

A bounded multi-file project template for the model track: `agent.py` plus a
local `weights.json` artifact. The runtime provides Python 3.12 and NumPy;
no network, no GPU. Package the folder as a ZIP (with `agent.py` at the
root) and upload it in the Workshop with the Hearts game selected.

The starter scores every legal card with a linear cost model (rank strength,
hearts, the Q♠, whether the card would win the trick, and the points already
in the trick) and plays the cheapest; during the pass it sheds the three
highest-scoring dangers. Replace the hand-crafted features and weights with
your own trained model — training happens on your machine; only the
inference artifact is submitted.
