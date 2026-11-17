"""Print the live-experiment procedure. This command does not call OpenAI."""

from app.experiments import build_procedure, render_procedure, verify_case_b_fixtures


def main() -> None:
    problems = verify_case_b_fixtures()
    print(render_procedure(build_procedure(), problems), end="")
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
