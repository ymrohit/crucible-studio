Trust, but verify.

Crucible Studio is a Gemma 4 + Cerebras coding agent that does the part normal LLM demos skip:
it proves the code before it ships.

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
