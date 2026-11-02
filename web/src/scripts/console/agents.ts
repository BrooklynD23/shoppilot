// The team on the console stage. Each mascot is one real backend module, never a made-up role.
// Order = left to right on the stage. `mat` names a --mat-* token in src/styles/tokens.css.
export type AgentId = 'guard' | 'router' | 'planner' | 'forecaster' | 'validator' | 'judge' | 'executor';

export interface Agent {
  id: AgentId;
  name: string;
  kind: string;   // what it really is: a model or plain code
  does: string;   // one sentence, shown in the Team tab
  code: string;   // where it lives in the repo
  mat: string;
}

export const AGENTS: readonly Agent[] = [
  { id: 'guard', name: 'Guard', kind: 'Rules + Haiku', does: 'Screens every inbox email before the planner can read it.', code: 'app/safety/inbound_guard.py', mat: 'tin' },
  { id: 'router', name: 'Router', kind: 'Haiku', does: 'Checks the request is shop work, or declines it.', code: 'app/agent/planner.py, route()', mat: 'tissue' },
  { id: 'planner', name: 'Planner', kind: 'Haiku', does: 'Reads the store, drafts typed steps, asks when unsure.', code: 'app/agent/planner.py', mat: 'kraft' },
  { id: 'forecaster', name: 'Forecaster', kind: 'Statistics', does: 'Forecasts demand and flags odd orders.', code: 'app/ml/forecast.py, app/ml/anomaly.py', mat: 'dusk' },
  { id: 'validator', name: 'Validator', kind: 'Code', does: 'Checks every step against policy and money caps.', code: 'app/agent/validator.py, app/safety/policy.py', mat: 'graphite' },
  { id: 'judge', name: 'Judge', kind: 'Haiku', does: 'Reviews the finished plan. It can only add warnings.', code: 'app/agent/planner.py, judge()', mat: 'sage' },
  { id: 'executor', name: 'Executor', kind: 'Code', does: 'Runs approved steps one by one and logs each one.', code: 'app/agent/executor.py', mat: 'walnut' },
];

export const AGENT_IDS = AGENTS.map((a) => a.id);

/** Narrower stages keep the 2D portraits and never fetch the 3D chunk. Below this the 3D state words collide:
 *  the outer mascots sit ~94 px apart at 760, and "Waiting for you" (113 px) next to "Warning" (76 px) needs 95.
 *  Keep in sync with the container query in page-console.css. */
export const STAGE_3D_MIN_PX = 800;
export const agentName = (id: AgentId) => AGENTS.find((a) => a.id === id)?.name ?? id;
