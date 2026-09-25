import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("trace")
    parser.add_argument("--battle-id")
    parser.add_argument(
        "--output",
        default="artifacts/jev-confidence.png",
    )

    args = parser.parse_args()

    data = pd.read_json(args.trace, lines=True)

    if args.battle_id:
        data = data[
            data["battle_id"] == args.battle_id
        ]

    if data.empty:
        raise ValueError("No matching decisions found")

    data = data.sort_values("decision_number")

    jev_decisions = data[
        data["selection_source"] == "jev"
    ]

    fallback_decisions = data[
        data["selection_source"] != "jev"
    ]

    figure, axis = plt.subplots(
        figsize=(12, 6),
    )

    axis.plot(
        jev_decisions["decision_number"],
        jev_decisions["jev_confidence"],
        marker="o",
        label="Jev confidence",
    )

    axis.plot(
        jev_decisions["decision_number"],
        jev_decisions["selected_probability"],
        marker="s",
        label="Selected-action probability",
    )

    axis.plot(
        jev_decisions["decision_number"],
        jev_decisions["probability_margin"],
        marker="^",
        label="Top-two probability margin",
    )

    if not fallback_decisions.empty:
        axis.scatter(
            fallback_decisions["decision_number"],
            [0.02] * len(fallback_decisions),
            marker="x",
            color="red",
            s=90,
            label="Fallback decision",
        )

    for row in jev_decisions.itertuples():
        axis.annotate(
            row.selected_action_id,
            (
                row.decision_number,
                row.selected_probability,
            ),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=7,
            rotation=30,
        )

    axis.set_ylim(0, 1.05)
    axis.set_xlabel("Decision number")
    axis.set_ylabel("Probability / confidence")

    battle_names = data["battle_id"].unique()
    title = (
        battle_names[0]
        if len(battle_names) == 1
        else "Multiple battles"
    )

    axis.set_title(
        f"Jev decision confidence — {title}"
    )

    axis.grid(alpha=0.25)
    axis.legend()

    figure.tight_layout()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    figure.savefig(
        output,
        dpi=160,
        bbox_inches="tight",
    )

    print(f"Saved chart to {output}")


if __name__ == "__main__":
    main()