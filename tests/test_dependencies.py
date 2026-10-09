from collections.abc import Iterator
from contextlib import suppress
from functools import partial
from inspect import signature
from typing import Annotated, Any

import pytest

from pyflowstep import (
    Depends,
    Flow,
    InvalidDependencyError,
    MissingArgumentError,
    TooManyArgumentsError,
    UnexpectedKeywordArgumentError,
    override_dependencies,
    step,
    tap,
)
from pyflowstep.dependencies import Dependency, find_dependencies


class Counter:
    """A provider that counts its calls and hands out numbered objects."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return f"object-{self.calls}"


def get_prefix() -> str:
    return ">"


PREFIX = Depends(get_prefix)

type AnnotatedPrefix = Annotated[str, Depends(get_prefix)]


@step
def label(items: list[str], text: str, prefix: str = Depends(get_prefix)) -> list[str]:
    return [*items, f"{prefix}{text}"]


@step
def label_reused(items: list[str], prefix: str = PREFIX, text: str = "x") -> list[str]:
    return [*items, f"{prefix}{text}"]


class TestDeclaration:
    def test_depends_returns_a_marker(self) -> None:
        marker = Depends(get_prefix)
        assert isinstance(marker, Dependency)
        assert marker.provider is get_prefix

    def test_default_value_form(self) -> None:
        assert label("a")([]) == [">a"]

    def test_marker_kept_in_a_constant_is_reused(self) -> None:
        assert label_reused()([]) == [">x"]
        assert label_reused("b")([]) == [">b"]
        assert label_reused(text="c")([]) == [">c"]

    def test_find_dependencies(self) -> None:
        assert list(find_dependencies(label)) == []  # a factory has no dependencies left
        assert list(find_dependencies(label.__wrapped__)) == ["prefix"]  # type: ignore[attr-defined]
        assert find_dependencies(next) == {}  # a builtin without a signature

    def test_string_annotations(self) -> None:
        @step
        def later(items: "list[str]", prefix: "str" = Depends(get_prefix)) -> "list[str]":
            return [*items, prefix]

        assert later()([]) == [">"]

    def test_dependency_between_ordinary_parameters(self) -> None:
        @step
        def join(items: list[str], first: str, prefix: str = PREFIX, last: str = "z") -> list[str]:
            return [*items, f"{first}{prefix}{last}"]

        assert join("a")([]) == ["a>z"]
        assert join("a", "b")([]) == ["a>b"]
        assert join(last="b", first="a")([]) == ["a>b"]

    def test_keyword_only_and_var_positional(self) -> None:
        @step
        def collect(
            items: list[str], *texts: str, prefix: str = PREFIX, sep: str = ""
        ) -> list[str]:
            return [*items, *(f"{prefix}{sep}{text}" for text in texts)]

        assert collect("a", "b", sep="-")([]) == [">-a", ">-b"]

    def test_tap_with_dependency(self) -> None:
        seen: list[str] = []

        @tap
        def remember(_: object, text: str, prefix: str = PREFIX) -> None:
            seen.append(f"{prefix}{text}")

        subject = object()
        assert remember("a")(subject) is subject
        assert seen == [">a"]


class TestInvisibleArguments:
    def test_factory_signature_hides_dependencies(self) -> None:
        assert str(signature(label)) == "(text: str)"
        assert str(signature(label_reused)) == "(text: str = 'x')"

    def test_cannot_be_passed_positionally(self) -> None:
        with pytest.raises(TooManyArgumentsError):
            label("a", "!")

    def test_cannot_be_passed_by_keyword(self) -> None:
        with pytest.raises(UnexpectedKeywordArgumentError, match="'prefix'"):
            label("a", prefix="!")

    def test_other_arguments_are_still_validated(self) -> None:
        with pytest.raises(MissingArgumentError, match="'text'"):
            label()


class TestRunScope:
    def test_provider_is_called_once_per_run(self) -> None:
        counter = Counter()

        @step
        def use(items: list[str], obj: str = Depends(counter)) -> list[str]:
            return [*items, obj]

        flow = use() >> use() >> use()

        assert flow([]) == ["object-1"] * 3
        assert flow([]) == ["object-2"] * 3
        assert counter.calls == 2

    def test_object_is_shared_between_different_steps(self) -> None:
        counter = Counter()

        @step
        def first(items: list[str], obj: str = Depends(counter)) -> list[str]:
            return [*items, obj]

        @step
        def second(items: list[str], obj: str = Depends(counter)) -> list[str]:
            return [*items, obj.upper()]

        assert (first() >> second())([]) == ["object-1", "OBJECT-1"]

    def test_nested_flows_join_the_outer_run(self) -> None:
        counter = Counter()

        @step
        def use(items: list[str], obj: str = Depends(counter)) -> list[str]:
            return [*items, obj]

        @step
        def twice(items: list[str], inner: Flow[list[str]]) -> list[str]:
            return inner(inner(items))

        flow = Flow(Flow(use()), twice(use() >> use()))

        assert flow([]) == ["object-1"] * 5
        assert counter.calls == 1

    def test_running_an_action_directly_opens_its_own_run(self) -> None:
        counter = Counter()

        @step
        def use(items: list[str], obj: str = Depends(counter)) -> list[str]:
            return [*items, obj]

        (action,) = use().actions

        assert action([]) == ["object-1"]
        assert action([]) == ["object-2"]

    def test_unused_providers_are_never_called(self) -> None:
        counter = Counter()

        @step
        def use(items: list[str], obj: str = Depends(counter)) -> list[str]:
            return [*items, obj]

        use()
        Flow()([])

        assert counter.calls == 0

    def test_provider_errors_surface_when_the_flow_runs(self) -> None:
        def broken() -> str:
            msg = "no connection"
            raise ConnectionError(msg)

        @step
        def use(items: list[str], obj: str = Depends(broken)) -> list[str]:
            return [*items, obj]

        flow = use()  # building is fine

        with pytest.raises(ConnectionError, match="no connection"):
            flow([])


class TestSubDependencies:
    def test_providers_can_depend_on_providers(self) -> None:
        def get_host() -> str:
            return "smtp.example.com"

        def get_port() -> int:
            return 25

        def get_address(host: str = Depends(get_host), port: int = Depends(get_port)) -> str:
            return f"{host}:{port}"

        @step
        def use(items: list[str], address: str = Depends(get_address)) -> list[str]:
            return [*items, address]

        assert use()([]) == ["smtp.example.com:25"]

    def test_shared_sub_dependency_is_resolved_once(self) -> None:
        counter = Counter()

        def left(obj: str = Depends(counter)) -> str:
            return f"left:{obj}"

        def right(obj: str = Depends(counter)) -> str:
            return f"right:{obj}"

        @step
        def use(items: list[str], a: str = Depends(left), b: str = Depends(right)) -> list[str]:
            return [*items, a, b]

        assert use()([]) == ["left:object-1", "right:object-1"]
        assert counter.calls == 1

    def test_provider_parameters_with_defaults_are_left_alone(self) -> None:
        def get_greeting(name: str = "world", *extra: str, **options: str) -> str:
            return f"hello {name}"

        @step
        def use(items: list[str], greeting: str = Depends(get_greeting)) -> list[str]:
            return [*items, greeting]

        assert use()([]) == ["hello world"]

    def test_class_as_provider(self) -> None:
        class Settings:
            def __init__(self, prefix: str = PREFIX) -> None:
                self.prefix = prefix

        @step
        def use(items: list[str], settings: Settings = Depends(Settings)) -> list[str]:
            return [*items, settings.prefix]

        assert use()([]) == [">"]

    def test_callable_object_as_provider(self) -> None:
        class Greeter:
            def __call__(self, prefix: str = PREFIX) -> str:
                return f"{prefix}hello"

        @step
        def use(items: list[str], greeting: str = Depends(Greeter())) -> list[str]:
            return [*items, greeting]

        assert use()([]) == [">hello"]

    def test_partial_as_provider(self) -> None:
        def get_address(host: str, prefix: str = PREFIX) -> str:
            return f"{prefix}{host}"

        @step
        def use(
            items: list[str], address: str = Depends(partial(get_address, "example.com"))
        ) -> list[str]:
            return [*items, address]

        assert use()([]) == [">example.com"]

    def test_builtin_without_signature_as_provider(self) -> None:
        @step
        def use(items: list[Any], made: dict[str, int] = Depends(dict)) -> list[Any]:
            return [*items, made]

        assert use()([]) == [{}]


class TestCleanup:
    @pytest.fixture
    def log(self) -> list[str]:
        return []

    def make_session(self, log: list[str], name: str = "session") -> Any:
        def get_session() -> Iterator[str]:
            log.append(f"open {name}")
            try:
                yield name
            except ValueError as error:
                log.append(f"rollback {name}: {error}")
                raise
            finally:
                log.append(f"close {name}")

        return get_session

    def test_generator_is_cleaned_up_when_the_run_ends(self, log: list[str]) -> None:
        get_session = self.make_session(log)

        @tap
        def use(_: object, text: str, session: str = Depends(get_session)) -> None:
            log.append(f"{text} with {session}")

        (use("save") >> use("audit"))(None)

        assert log == ["open session", "save with session", "audit with session", "close session"]

    def test_each_run_gets_a_fresh_generator(self, log: list[str]) -> None:
        get_session = self.make_session(log)

        @tap
        def use(_: object, session: str = Depends(get_session)) -> None:
            log.append("use")

        flow = use()
        flow(None)
        flow(None)

        assert log == ["open session", "use", "close session"] * 2

    def test_cleanup_runs_in_reverse_order(self, log: list[str]) -> None:
        outer, inner = self.make_session(log, "outer"), self.make_session(log, "inner")

        @tap
        def use(_: object, a: str = Depends(outer), b: str = Depends(inner)) -> None:
            log.append("use")

        use()(None)

        assert log == ["open outer", "open inner", "use", "close inner", "close outer"]

    def test_step_error_is_thrown_into_the_provider_and_re_raised(self, log: list[str]) -> None:
        get_session = self.make_session(log)

        @tap
        def use(_: object, session: str = Depends(get_session)) -> None:
            log.append("use")

        @tap
        def fail(_: object) -> None:
            msg = "bad order"
            raise ValueError(msg)

        @tap
        def never(_: object) -> None:
            log.append("never")

        with pytest.raises(ValueError, match="bad order"):
            (use() >> fail() >> never())(None)

        assert log == ["open session", "use", "rollback session: bad order", "close session"]

    def test_provider_cannot_swallow_a_step_error(self) -> None:
        def swallowing() -> Iterator[str]:
            with suppress(ValueError):
                yield "session"

        @tap
        def fail(_: object, session: str = Depends(swallowing)) -> None:
            msg = "bad order"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="bad order"):
            fail()(None)

    def test_cleanup_error_propagates(self) -> None:
        def failing_cleanup() -> Iterator[str]:
            yield "session"
            msg = "commit failed"
            raise RuntimeError(msg)

        @tap
        def use(_: object, session: str = Depends(failing_cleanup)) -> None: ...

        with pytest.raises(RuntimeError, match="commit failed"):
            use()(None)

    def test_scope_is_reset_after_a_failed_run(self, log: list[str]) -> None:
        get_session = self.make_session(log)

        @tap
        def use(_: object, fail: bool, session: str = Depends(get_session)) -> None:  # noqa: FBT001
            if fail:
                raise KeyError(session)

        with pytest.raises(KeyError):
            use(True)(None)  # noqa: FBT003
        use(False)(None)  # noqa: FBT003

        assert log == ["open session", "close session", "open session", "close session"]

    def test_generator_with_sub_dependency(self, log: list[str]) -> None:
        def get_session(prefix: str = PREFIX) -> Iterator[str]:
            log.append("open")
            yield f"{prefix}session"
            log.append("close")

        @step
        def use(items: list[str], session: str = Depends(get_session)) -> list[str]:
            return [*items, session]

        assert use()([]) == [">session"]
        assert log == ["open", "close"]


class TestOverrides:
    def test_override_replaces_the_provider(self) -> None:
        with override_dependencies({get_prefix: lambda: "#"}):
            assert label("a")([]) == ["#a"]

    def test_override_is_restored_on_exit(self) -> None:
        with override_dependencies({get_prefix: lambda: "#"}):
            pass
        assert label("a")([]) == [">a"]

    def test_override_is_restored_after_an_error(self) -> None:
        with pytest.raises(RuntimeError), override_dependencies({get_prefix: lambda: "#"}):
            raise RuntimeError

        assert label("a")([]) == [">a"]

    def test_nested_overrides_add_up(self) -> None:
        def get_suffix() -> str:
            return "<"

        @step
        def wrap(
            items: list[str], prefix: str = PREFIX, suffix: str = Depends(get_suffix)
        ) -> list[str]:
            return [*items, f"{prefix}{suffix}"]

        with override_dependencies({get_prefix: lambda: "#"}):
            with override_dependencies({get_suffix: lambda: "$"}):
                assert wrap()([]) == ["#$"]
            assert wrap()([]) == ["#<"]

    def test_inner_override_wins(self) -> None:
        with (
            override_dependencies({get_prefix: lambda: "#"}),
            override_dependencies({get_prefix: lambda: "@"}),
        ):
            assert label("a")([]) == ["@a"]

    def test_override_applies_to_sub_dependencies(self) -> None:
        def get_address(prefix: str = PREFIX) -> str:
            return f"{prefix}host"

        @step
        def use(items: list[str], address: str = Depends(get_address)) -> list[str]:
            return [*items, address]

        with override_dependencies({get_prefix: lambda: "#"}):
            assert use()([]) == ["#host"]

    def test_override_can_have_its_own_dependencies(self) -> None:
        def get_other() -> str:
            return "other"

        def fake(other: str = Depends(get_other)) -> str:
            return f"fake-{other}-"

        with override_dependencies({get_prefix: fake}):
            assert label("a")([]) == ["fake-other-a"]

    def test_generator_override_is_cleaned_up(self) -> None:
        log: list[str] = []

        def fake() -> Iterator[str]:
            log.append("open")
            yield "#"
            log.append("close")

        with override_dependencies({get_prefix: fake}):
            assert label("a")([]) == ["#a"]

        assert log == ["open", "close"]

    def test_flow_built_before_the_override_uses_it(self) -> None:
        flow = label("a")

        with override_dependencies({get_prefix: lambda: "#"}):
            assert flow([]) == ["#a"]


class TestInvalidDeclarations:
    @pytest.mark.parametrize("provider", [None, 5, "get_prefix"])
    def test_provider_must_be_callable(self, provider: Any) -> None:
        with pytest.raises(InvalidDependencyError, match="must be callable"):
            Depends(provider)

    def test_subject_cannot_be_injected(self) -> None:
        def bad(items: str = PREFIX, text: str = "") -> str:
            return items

        with pytest.raises(InvalidDependencyError, match="'bad' cannot inject its subject 'items'"):
            step(bad)

    def test_positional_only_parameter_cannot_be_injected(self) -> None:
        def bad(items: list[str], prefix: str = PREFIX, /) -> list[str]:
            return items

        with pytest.raises(
            InvalidDependencyError, match="'bad' cannot inject positional-only parameter 'prefix'"
        ):
            step(bad)

    @pytest.mark.parametrize(
        "annotation",
        [Annotated[str, Depends(get_prefix)], AnnotatedPrefix, "AnnotatedPrefix"],
    )
    def test_annotated_form_is_rejected_on_a_step(self, annotation: Any) -> None:
        def bad(items: list[str], prefix: str) -> list[str]:
            return items

        bad.__annotations__["prefix"] = annotation

        with pytest.raises(InvalidDependencyError) as error:
            step(bad)

        assert str(error.value) == (
            "Step 'bad' uses Depends inside Annotated for 'prefix'; write it as the default "
            "value, `prefix: <type> = Depends(get_prefix)`, so type checkers see the parameter "
            "as optional"
        )

    def test_annotated_form_is_rejected_on_variadic_parameters(self) -> None:
        def bad(items: list[str], *prefix: AnnotatedPrefix) -> list[str]:
            return items

        with pytest.raises(InvalidDependencyError, match="uses Depends inside Annotated"):
            step(bad)

    def test_annotated_form_is_rejected_on_a_provider(self) -> None:
        def get_mailer(prefix: AnnotatedPrefix) -> str:
            return prefix

        def send(order: str, mailer: str = Depends(get_mailer)) -> str:
            return order

        with pytest.raises(
            InvalidDependencyError,
            match="Provider 'get_mailer' uses Depends inside Annotated for 'prefix'",
        ):
            step(send)

    def test_provider_with_a_required_plain_parameter(self) -> None:
        def get_mailer(host: str) -> str:
            return host

        def send(order: str, mailer: str = Depends(get_mailer)) -> str:
            return order

        with pytest.raises(
            InvalidDependencyError, match="'get_mailer' has a required parameter 'host'"
        ):
            step(send)

    def test_nested_provider_with_a_required_plain_parameter(self) -> None:
        def get_host(region: str) -> str:
            return region

        def get_mailer(host: str = Depends(get_host)) -> str:
            return host

        def send(order: str, mailer: str = Depends(get_mailer)) -> str:
            return order

        with pytest.raises(
            InvalidDependencyError, match="'get_host' has a required parameter 'region'"
        ):
            step(send)

    def test_provider_with_positional_only_dependency(self) -> None:
        def get_mailer(prefix: str = PREFIX, /) -> str:
            return prefix

        def send(order: str, mailer: str = Depends(get_mailer)) -> str:
            return order

        with pytest.raises(
            InvalidDependencyError, match="'get_mailer' cannot inject positional-only"
        ):
            step(send)

    def test_circular_providers(self) -> None:
        def get_a(b: str = Depends(lambda: "")) -> str:
            return b

        def get_b(a: str = Depends(get_a)) -> str:
            return a

        get_a.__defaults__ = (Depends(get_b),)

        def use(order: str, a: str = Depends(get_a)) -> str:
            return order

        with pytest.raises(
            InvalidDependencyError, match="Circular dependency: get_a -> get_b -> get_a"
        ):
            step(use)

    def test_self_referencing_provider(self) -> None:
        def get_a(a: str = "") -> str:
            return a

        get_a.__defaults__ = (Depends(get_a),)

        def use(order: str, a: str = Depends(get_a)) -> str:
            return order

        with pytest.raises(InvalidDependencyError, match="Circular dependency: get_a -> get_a"):
            step(use)

    def test_invalid_dependency_error_is_a_type_error(self) -> None:
        assert issubclass(InvalidDependencyError, TypeError)
