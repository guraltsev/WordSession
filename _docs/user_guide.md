# Word Session user guide

The user guide is part of the application, so that it always matches the
version a user has installed:

- Source: [`src/word_session/web/static/help.html`](../src/word_session/web/static/help.html)
  (open it directly in a browser to read it from the repository).
- In the running app: **Help** in the tray menu, **Help** in the manager's
  top bar, or `http://127.0.0.1:<port>/help.html`. The page needs no
  sign-in.

The manager's **?** links point at section ids in that file
(`help.html#<id>`). `tests/api/test_static.py` fails if a link points at a
missing id, so rename sections there and in the manager together.
