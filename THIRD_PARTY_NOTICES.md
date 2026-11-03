# Third-party notices

## catanatron

- **Used for:** the Hexchange rules engine (board, dice, production, building
  legality, robber, development cards, bank trades, termination) since engine
  version 2 — see `backend/arena/games/hexchange/RULES.md` §15.
- **Version:** 3.2.1 (PyPI `catanatron`).
- **Upstream:** <https://github.com/bcollazo/catanatron>
- **License:** GNU General Public License v3.0 (GPL-3.0) — upstream states:
  "This project is licensed under the GPL-3.0 license." The library is used
  unmodified as an installed dependency; Stack Theory's arena code
  (`backend/arena/games/hexchange/engine.py`) drives it through its public
  API and is a separate work.

  This program is distributed in the hope that it will be useful, but WITHOUT
  ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
  FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
  more details: <https://www.gnu.org/licenses/gpl-3.0.html>.

  A copy of the license is available upstream at
  <https://github.com/bcollazo/catanatron/blob/main/LICENSE>.
