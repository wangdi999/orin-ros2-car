# D1 Software Validation

**Status**: PASS — T032 completed on 2026-07-13
**Vehicle connection**: not used by this local-only gate
**Motion commands sent**: none

## Latest local evidence

| Scope | Command/evidence | Result |
|---|---|---:|
| Console regression | `npm test` | 46/46 passed |
| Console production build | `npm run build` | PASS (Vite 6.4.3, 35 modules transformed) |
| Driver safety policy | `python test\\test_driver_safety.py` | 7/7 passed |
| Navigation pure logic/contracts | `python -m unittest discover -s test -p "test*.py"` | 63/63 passed |
| Python syntax | `python -m compileall -q ...` for bringup/navigation nodes and launches | PASS |
| Deployment safety | deployment script with `-DryRun` and current IP | PASS; no copy, network command or runtime start |
| Evidence collector safety | collector with `-DryRun` and current IP | PASS; no network or evidence write |

The latest run used Python 3.13.5, Node.js 22.19.0, npm 10.9.3 and Windows PowerShell 5.1. The scoped Python and Node suites were rerun after the final runtime corrections. C++ gtests, generated interfaces and launch imports were separately validated on the Foxy target in T033.

## Gate conclusion

- Local implementation present: **YES**
- Latest automated regression result: **PASS (116 assertions/tests: 46 Node + 7 driver + 63 navigation)**
- Foxy build/test: **PASS (T033; 80/80)**
- Vehicle non-motion validation: **PASS (T034)**
- D1 local software gate / T032: **PASS**
