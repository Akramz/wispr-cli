import json
import sys

import click

from . import client


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def result_text(res: dict) -> str:
    if "structuredContent" in res:
        return json.dumps(res["structuredContent"], indent=2, ensure_ascii=False)
    parts = [c.get("text", json.dumps(c)) for c in res.get("content", [])]
    return "\n".join(parts)


@click.group()
def cli():
    """Read your Wispr Flow data via the Wispr MCP server."""


@cli.command()
@click.option(
    "--no-browser",
    is_flag=True,
    help="For machines without a browser: open the URL anywhere, then paste back the page address you land on.",
)
def login(no_browser):
    """Sign in with your Wispr account in the browser."""

    def show(url):
        click.echo(f"Sign in at:\n  {url}", err=True)
        if not no_browser:
            click.launch(url)

    def paste():
        return click.prompt(
            "After signing in, the browser lands on a page that fails to load. Paste its full address",
            err=True,
        )

    client.browser_login(show, paste if no_browser else None)
    click.echo(f"Logged in. Tokens saved to {client.STATE}", err=True)


@cli.command()
def logout():
    """Forget saved tokens."""
    state = client.load()
    for k in ("access_token", "refresh_token", "expires_at"):
        state.pop(k, None)
    client.save(state)
    click.echo("Logged out.", err=True)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Print full tool schemas.")
def tools(as_json):
    """List the tools the Wispr server offers."""
    ts = client.MCP().tools()
    if as_json:
        click.echo(json.dumps(ts, indent=2))
        return
    for t in ts:
        schema = t.get("inputSchema", {})
        req = set(schema.get("required", []))
        args = " ".join(f"{k}=" if k in req else f"[{k}=]" for k in schema.get("properties", {}))
        click.echo(f"{t['name']} {args}".rstrip())
        if t.get("description"):
            click.echo(f"    {t['description'].strip().splitlines()[0]}")


@cli.command()
@click.argument("tool")
@click.argument("args", nargs=-1)
@click.option("--raw", is_flag=True, help="Print the full MCP result as JSON.")
def call(tool, args, raw):
    """Call TOOL with key=value args (values parsed as JSON when possible)."""
    kwargs = {}
    for a in args:
        if "=" not in a:
            raise click.BadParameter(f"expected key=value, got {a!r}")
        k, v = a.split("=", 1)
        kwargs[k] = parse_value(v)
    res = client.MCP().call(tool, kwargs)
    click.echo(json.dumps(res, indent=2, ensure_ascii=False) if raw else result_text(res))
    if res.get("isError"):
        sys.exit(1)
