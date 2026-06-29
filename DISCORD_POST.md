Trust, but verify.

Crucible Studio is a Gemma 4 + Cerebras coding agent that does the part normal LLM demos skip:
it proves the code before it ships.

The Cerebras speed is the unlock: instead of spending the latency budget on one unverified answer,
Crucible spends it on spec -> blind tests -> implementation -> runtime gauntlet -> counterexample repair,
live enough for judges to interact with.

Headline:

- hard recent LeetCode: vanilla Gemma 4 31B 39.2% -> Crucible 52.5% pass@1 (+13.3 points)
- SWE-bench Lite: resolves real official-harness instances end-to-end, including pallets__flask-4045
  and 4 distinct curated single-file Lite instances across runs
- runnable products: vanilla 0/4 -> Crucible 4/4, boot-verified in Docker
- speed: Cerebras makes multi-agent verification feel interactive, not like an offline benchmark harness

Same task, two paths:

- vanilla Gemma streams code fast
- Crucible turns the prompt into a spec, writes blind adversarial tests, runs a real oracle gauntlet,
  catches the counterexample, patches the bug, and only then returns verified code

The important bit: the model never grades itself.

Adversary cannot see the code.
Implementer cannot see the tests.
The verdict comes from execution: parse, typecheck, smoke, examples, properties, and differential checks.

In the demo, judges can paste broken code, click Run, then inspect:

- the generated tests
- the exact counterexample
- the repair trail
- the final fixed implementation

This is built for the failure mode we all know: code that looks right, demos well, and silently breaks
on state, ordering, idempotency, or boundary cases.

Demo video:
https://github.com/ymrohit/crucible-studio/blob/main/Crucible.mp4

Repo:
https://github.com/ymrohit/crucible-studio

Track: g4hackathon-multiverse-agents
