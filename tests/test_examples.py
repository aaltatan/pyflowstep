import pytest

from examples import browser, coffee, dependencies, processing


def test_browser_example_runs(capsys: pytest.CaptureFixture[str]) -> None:
    browser.main()
    output = capsys.readouterr().out

    assert "--- search (Python) ---" in output
    assert "Waiting for #dashboard (10.0s)" in output
    assert '"$schema"' in output


def test_coffee_example_runs(capsys: pytest.CaptureFixture[str]) -> None:
    coffee.main()

    assert capsys.readouterr().out.splitlines() == [
        "M espresso, 2 shot(s) -> $3.30",
        "L espresso, 1 shot(s), 200ml whole milk, 1x vanilla syrup -> $3.65",
        "S espresso, 2 shot(s), 150ml oat milk, 2x chocolate syrup, whipped cream, cocoa -> $3.36",
        "M espresso, 1 shot(s), 200ml whole milk -> $1.25",
    ]


def test_dependencies_example_runs(capsys: pytest.CaptureFixture[str]) -> None:
    dependencies.main()

    assert capsys.readouterr().out.splitlines() == [
        "Flow(discount >> save >> charge >> send_email >> audit)",
        "",
        "--- a normal run: one session, shared by `save` and `audit` ---",
        "  session opened",
        "  mail via smtp.example.com: shop@example.com -> ada@example.com: receipt for order o-1 ($45.00)",
        "  session committed: order o-1, audit o-1 fulfilled",
        "  session closed",
        "  -> paid",
        "",
        "--- a failing run: the same flow, a fresh session, rolled back ---",
        "  session opened",
        "  session rolled back",
        "  session closed",
        "  -> ValueError: nothing to charge for order o-2",
        "",
        "--- in a test: swap the mailer for a fake ---",
        "  session opened",
        "  (fake mailer) would send 'receipt for order o-3 ($18.00)' to eve@example.com",
        "  session committed: order o-3, audit o-3 fulfilled",
        "  session closed",
        "",
        "--- JSON can neither see nor set a dependency ---",
        "  schema arguments: ['template']",
        (
            "  UnexpectedKeywordArgumentError: got an unexpected keyword argument 'mailer' "
            "for step 'send_email' (at $[0])"
        ),
    ]


def test_processing_example_runs(capsys: pytest.CaptureFixture[str]) -> None:
    processing.main()

    assert capsys.readouterr().out.splitlines() == [
        "Flow(in_category >> search >> where >> exclude >> price_between >> top)",
        "Pro Headphones (Sonic) $349.00 4.9*",
        "Studio Headphones (Sonic) $149.00 4.7*",
        "exclude expects: [{'type': 'string'}]",
        (
            "ProcessArgumentError: Argument 'limit' with value 'two' failed to process, "
            "invalid literal for int() with base 10: 'two' (at $[1])"
        ),
    ]
