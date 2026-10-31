# Implementation references

- Sequoia No Limit rules: https://pokerbot.sequoiacap.com/rules.html
  Used to understand Python agent submission, offline decisions, development
  assistance, timing, table simulation and weighted round format. This project
  uses its own SDK and an announced Hold'em variant, not their private kit.
- PokerKit simulation: https://pokerkit.readthedocs.io/en/stable/simulation.html
- PokerKit source: https://github.com/uoftcprg/pokerkit
- Docker container controls: https://docs.docker.com/reference/cli/docker/container/run/
- FastAPI authentication guidance: https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
  This pilot implements server-stored revocable opaque sessions rather than JWTs.
