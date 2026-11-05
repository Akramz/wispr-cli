# wispr-cli

`wispr` reads your [Wispr Flow](https://wisprflow.ai) meetings, transcripts, notes and calendar
from the terminal, through Wispr's MCP server (`https://api.wisprflow.ai/connect/mcp`). It is
built for coding agents (Claude Code, Copilot CLI, Codex) and works the same for people.

wispr-cli is an independent project. It is not made or supported by Wispr.

## Install

Needs [uv](https://docs.astral.sh/uv/):

```console
uv tool install git+https://github.com/Akramz/wispr-cli
wispr login
```

`wispr login` opens your browser to sign in to Wispr. On a machine without a browser (an ssh
session), run `wispr login --no-browser`: open the printed link on any computer, sign in, then
paste back the address of the page you land on. That page fails to load; that is expected.

Upgrade with `uv tool upgrade wispr-cli`.

## Use

```console
wispr tools                                              # what the server offers
wispr call search_meetings since=2026-11-01 limit=10     # recent meetings
wispr call get_meeting meeting_id=<id> 'view_transcript={}'
wispr call search_scratchpad_notes query=ideas
wispr call list_upcoming_meetings window_hours=48
```

`wispr call <tool> key=value ...` passes each value as JSON when it parses, else as a string.
It prints the tool's result; `--raw` prints the whole MCP response. Times are UTC.

The server covers meetings (with transcripts), scratchpad notes, calendar events and folders.
It does not offer your dictation history.

## Credentials

There is no API key. `wispr login` registers an OAuth client for this machine and stores its
tokens in `~/.config/wispr/auth.json` (mode 600). They refresh on their own. Set
`WISPR_CONFIG` to keep them elsewhere. `wispr logout` forgets them. Sign in once on each
machine rather than copying the file: the refresh token rotates, so two machines sharing one
file log each other out.
