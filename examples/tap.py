from pyflowstep import step, tap


@step
def add_step(n: int, x: int) -> int:
    return n + x


@tap
def add_tap(n: int, x: int) -> int:
    return n + x


@tap
def log(n: int, label: str) -> None:
    print(f"{label}: {n}")


def main() -> None:
    print(f"{(add_step(1) >> add_step(10))(0) = }")  # 11
    print(f"{(add_tap(1) >> add_tap(10))(0) = }")  # 0: both results were thrown away
    print("#" * 100)
    (add_step(1) >> log("after add") >> add_step(10) >> log("end"))(0)


if __name__ == "__main__":
    main()
