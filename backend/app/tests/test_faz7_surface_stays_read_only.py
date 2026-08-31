"""Faz 16 (Yayina alma) checkpoint: before any production cutover, lock in
that the whole Faz 7 HTTP surface is exactly as read-only as it looks today.

kokpit.py, biz.py, hubs.py and promotions.py were all added or grew new
routes during the Faz 7 rebuild, and none of them needed app.core.deps'
require_admin -- every one of them is a public GET with no database write.
That is a fact worth pinning down with a test, not just a grep someone ran
once: a future PR adding, say, a POST /promotions/refresh could slip past
review without ever tripping test_operator_auth.py, because that suite only
knows about the routes it was written against.

Same reasoning for the three CLI-only maintenance commands added this phase
(mark-legacy-campaigns-superseded, evaluate-golden, check-data-quality):
they are invoked only via `python -m app.cli` from GitHub Actions
workflow_dispatch/cron, deliberately never given an HTTP route. If one ever
gained one, it would need require_admin exactly like /admin/status and
POST /editions/{date}/rebuild -- this test fails loudly the moment that
happens, rather than the gap being discovered in production.
"""
from app.api.v1 import biz, hubs, kokpit, promotions, signals
from app.api.v1.router import api_router

READ_ONLY_ROUTERS = {
    "kokpit": kokpit.router,
    "biz": biz.router,
    "hubs": hubs.router,
    "promotions": promotions.router,
    # Sinyaller composes six other read-only surfaces into one feed; it must
    # never gain a way to write to any of them.
    "signals": signals.router,
}

# CLI commands that must stay reachable only via `python -m app.cli`, never
# over HTTP -- each does something a public request should never be able to
# trigger for free (mutates production data or costs an LLM call per record).
CLI_ONLY_COMMANDS = (
    "mark-legacy-campaigns-superseded",
    "evaluate-golden",
    "check-data-quality",
)


def test_the_faz7_routers_are_still_entirely_get():
    for name, router in READ_ONLY_ROUTERS.items():
        for route in router.routes:
            assert route.methods == {"GET"}, (
                f"{name} gained a non-GET route ({route.path} {route.methods}) -- "
                "a mutating endpoint here needs app.core.deps.require_admin, "
                "the same guard test_operator_auth.py checks for /admin and "
                "POST /editions/{date}/rebuild."
            )


def test_cli_only_commands_have_no_http_route():
    all_paths = {route.path for route in api_router.routes}
    for command in CLI_ONLY_COMMANDS:
        slug = command.replace("-", "_")
        assert not any(slug in path for path in all_paths), (
            f"{command} now has an HTTP route -- it needs require_admin before "
            "this can be true; it was designed to run only from GitHub Actions."
        )
