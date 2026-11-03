# Hexchange model starter (Stack Theory Hexchange v1)

A bounded multi-file project template for the model track: `agent.py` plus a
local `weights.json` artifact. The runtime provides Python 3.12 and NumPy;
no network, no GPU. Package the folder as a ZIP (with `agent.py` at the
root) and upload it in the Workshop with the Hexchange game selected.

The starter scores four goals (settlement / road / city / dev card) and the
accept/reject trade decision with tiny linear models over public features:
affordability, build-space left, pip potential, and offer shape. Replace the
hand-crafted features and weights with your own trained model — training
happens on your machine; only the inference artifact is submitted.

Remember the visibility freeze: you see the board, buildings, roads, resource
*counts*, offers, and the robber — never opponent resource identities, the dev
deck, or anyone's hidden development cards.
