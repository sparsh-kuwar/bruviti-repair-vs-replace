# Browser tests (end-to-end)

Real browsers drive the real page against a real server process. They check:
- the three brief examples;
- the cost breakdown;
- keyboard operation and visible focus;
- layouts from 360 to 1920 px and 200% text zoom;
- an axe-core accessibility audit;
- the names and roles a screen reader announces;
- that nothing is loaded from outside the machine.

They are separate from the main offline suite, which is all the service needs.

```sh
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium firefox webkit     # one-time download (~500 MB)
python -m pytest e2e -q                                  # all three engines
E2E_BROWSERS=webkit python -m pytest e2e -q              # one engine
python scripts/test_report.py --with-e2e                 # also refresh TESTING.md §5b
```

The fixture starts its own server on a free port, so nothing needs to be running.
WebKit follows macOS: Tab skips buttons unless Option is held, so the keyboard
tests press Alt+Tab in WebKit, as a Safari user would.
