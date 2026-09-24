import pytest

from examples import browser, coffee, processors


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


def test_processors_example_runs(capsys: pytest.CaptureFixture[str]) -> None:
    processors.main()

    assert capsys.readouterr().out.splitlines() == [
        "Flow(in_category >> search >> where >> price_between >> top)",
        "Studio Headphones (Sonic) $149.00 4.7*",
        "Travel Headphones (Sonic) $89.00 4.2*",
        (
            "InvalidProcessorsError: Processors of step 'first' name unknown parameters ['limt'], "
            "available parameters: limit"
        ),
    ]
