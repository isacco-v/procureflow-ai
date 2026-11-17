"""Print the mock extraction report. This command does not call a model provider."""

from app.documents.evaluate import evaluate_mock_extraction, render_report


def main() -> None:
    print(render_report(evaluate_mock_extraction()), end="")


if __name__ == "__main__":
    main()
