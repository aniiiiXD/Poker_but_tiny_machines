# Campus Arena — implementation contract

New standalone workspace. No changes to Passkarwado. Working brand: Campus Arena.
Real online Python pokerbot platform inspired by Sequoia's format, no affiliation.
Backend Python FastAPI/SQLite/PokerKit at127.0.0.1:8001. Frontend React/Vite at127.0.0.1:5173 proxies /api to backend. Backend own folder. No paid model API calls.

## Product / design
Beautiful public-facing student tournament site plus actual arena workspace. Calm pale blue/white canvas, deep cobalt, dark navy poker table, coral accents on card suits only. Display sans strong expressive type; readable UI. Visual centerpiece: actual poker-table replay with cards/bots, not stock hero. Responsive mobile/2560. No fake sponsor logos/users/live claims. Mark seeded games Exhibition / baseline bots. Website should attract students and sponsors, with real signup/submit/practice/ranked event flows, not dead buttons.

## API: JSON unless stated
Errors {detail:string}. Auth HTTP-only cookie, fetch credentials same-origin.
GET /api/health -> {status, sandbox_available:bool, sandbox_image:bool}
POST /api/auth/register {name,email,password,college} -> {user}
POST /api/auth/login {email,password} -> {user}
POST /api/auth/logout -> {ok:true}
GET /api/me -> {user:{id,name,email,college,role,team_id}|null,team:{id,name,join_code,members:[{id,name}]}|null}
POST /api/team {name} -> team
POST /api/team/join {code} -> team
GET /api/events -> {events:[{id,title,description,status,variant,build_starts_at,build_ends_at,round_interval_seconds,round_count,tables_per_round,max_hands,decision_ms,entry_count,joined,sponsor_name:null|string,exhibition:bool}]}
GET /api/events/{id} -> {event: same,rounds:[{id,number,status,starts_at,finished_at,entries_count}], leaderboard:[{rank,team_id,team_name,college,total_score,round_scores:number[],is_baseline:bool}],entries:[{team_id,team_name}],rules:{...}}
POST /api/events/{id}/join -> {ok:true} // team needed; choose actual bot before round freeze
GET /api/starter -> {source:string,interface:string,guide:string}
GET /api/starter/download -> zip
GET /api/submissions -> {submissions:[{id,name,created_at,status,sha256,source,active,error}]}
POST /api/submissions {name,source} -> submission // validates AST only no host execution. status accepted; newest accepted active; cooldown5min configurable. Return429 detail if too soon.
POST /api/practice {submission_id?:string,hands?:number} -> {job_id:string} // null = baseline demo, custom requires ownteam and Docker. max30hands.
GET /api/jobs/{id} -> {id,status:'queued'|'running'|'completed'|'failed',progress:number,error:null|string,result:null|{scores:[{name,points,chips,faults}],replay_id:string,hands:int}}
GET /api/replays -> {replays:[{id,title,created_at,hand_count,source:'practice'|'exhibition'|'tournament'}]}
GET /api/replays/{id} -> {id,title,frames:[{hand:int,street:string,board:string[],pot:int,actor:int|null,action:string,seats:[{name:string,stack:int,bet:int,folded:bool,cards:string[]}],note?:string}],summary:{...}}
GET /api/leaderboard -> {leaderboard:[{rank,team_id,team_name,college,total_score,events_played,is_baseline}]}
POST /api/sponsor-inquiries {name,email,company,message} -> {ok:true}
GET /api/profile -> {user,team,stats:{submissions,practice_runs,events},recent_submissions:[...]}
ADMIN (not necessary frontend): POST /api/admin/events fields event config; POST /api/admin/events/{id}/start to start build; POST /api/admin/events/{id}/round to queue next scored round early local operator only, must joined teams accepted bots; GET /api/admin/inquiries.

## Bot contract
class Agent:
  def act(self, observation: dict) -> dict:
    return {"action":"check"} # fold/check/call/raise; raise amount=total street contribution
observation: {hand,street,seat,button,hole_cards:[str],board:[str],pot,stack,to_call,min_raise,max_raise,legal_actions:[str],players:[{seat,stack,bet,folded}],history:[{seat,action,amount,street}]}
No opponent hole cards, deck, identities or engine seed ever shared. Observations anonymous.
Executor objects expose reset() -> None and act(observation)->dict, optionally .name string. Engine handles invalid actions/errors as check if available else fold, records faults. Sandbox executor enforces deadline. Reset at each table. Engine all cards delivered explicitly from seeded private deck (determinism), not PokerKit global RNG.
Engine function play_table(bots:list, seed:int, max_hands:int=200, starting_stack:int=2000, capture:bool=False) -> {points:list[float],chips:list[int],faults:list[int],frames:list[dict],hands:int}. 8 bots usual but support2..8. Blinds10/20 double every25 hands; positions rotate. Finishes points [8,5,3,2,1,0,0,0] topdown, ICM remainder if hand cap. Return order matches bots. Replay all hole cards only after table finished; no runtime leaks.
Baselines factory make_baselines(count:int=8) -> bot objects .name .reset .act. Starter safe real strategy.

## Engine additions (Sequoia-format parity)
play_table result also carries errors:list[str|None] — first fault reason per bot (timeout, crash, illegal action), surfaced as `error` in practice scores and in replay summaries. SandboxDown(BotError) marks infrastructure failure (daemon down, spawn/startup transport failure): engine aborts the table, score_round preflights sandbox_status() and fails the round unscored for retry; never score a round of dead sandboxes. GET /api/submissions includes cooldown_remaining; POST 429 sets Retry-After. Starter kit ships a standalone simulator (simulate.py: seeded deck, side pots, ICM settlement, platform observation contract) and icm.py calculator; /api/starter/download includes both.

## Production subsystems
Accounts carry email verification (mailer: SMTP via ARENA_SMTP_* or DATA/outbox fallback; tokens stored as sha256, single-use, 24h/1h TTLs); submissions are gated on verified email; /api/auth/verify|verify/resend|forgot|reset, reset rotates password and kills sessions. Worker is standalone: `python -m arena.worker [--workers N] [--once]`, atomic job claims under BEGIN IMMEDIATE, coordinator/exec split, ARENA_WORKERS pool, ARENA_EMBEDDED_WORKER=0 for API-only mode. Events pin sandbox_digest (image id captured at creation, passed to every ContainerBot). Every scored table writes hand_logs (seed, table_index, per-hand actions/board/busted); admin endpoints /api/admin/hand-logs[/id]. Scoring is hash-chained append-only: score_events with prev_hash/hash (db.append_score_event, db.verify_score_chain); corrections via POST /api/admin/scores/correct append, never mutate; GET /api/admin/score-events returns chain_valid. Deployment: DEPLOY.md + deploy/ (systemd api+worker@.service, Caddyfile, backup.sh).
