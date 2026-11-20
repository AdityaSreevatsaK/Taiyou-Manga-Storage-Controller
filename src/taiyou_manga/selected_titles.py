"""Fixed, owner-approved English manga sources; no arbitrary URLs or run IDs."""

from __future__ import annotations

from dataclasses import dataclass

from .domain import ControllerError


@dataclass(frozen=True)
class SelectedTitle:
    slug: str
    name: str
    run_id: int
    main_chapters: int
    audited_pages: int
    prefix: str
    source_id: str

    @property
    def ranges(self) -> list[tuple[int, int]]:
        return [
            (start, min(start + 19, self.main_chapters))
            for start in range(1, self.main_chapters + 1, 20)
        ]

    @property
    def artifact_names(self) -> set[str]:
        return {f"{self.prefix}{start}-{end}" for start, end in self.ranges}


TITLES = {
    "maid-sama": SelectedTitle(
        "maid-sama", "Kaichou wa Maid-sama!", 44587087000, 85, 3415,
        "Manga-maid-sama-Original-Ch", "d5e2bd89-e300-4262-a799-fb4f79bdb777",
    ),
    "last-game": SelectedTitle(
        "last-game", "Last Game", 44587087000, 56, 2022,
        "Manga-last-game-Original-Ch", "32600d3f-a43a-4f90-8a4e-c4e09f35c99b",
    ),
    "love-so-life": SelectedTitle(
        "love-so-life", "Love So Life", 44597036262, 106, 3326,
        "LoveSoLife-Original-Ch", "911a12ae-1022-448e-9219-b7b294d7fb3e",
    ),
    "onizuka-sawarida": SelectedTitle(
        "onizuka-sawarida", "Onizuka-chan and Sawarida-kun", 44675324997, 49, 274,
        "Onizuka-Original-Ch", "96b87943-6458-4045-a029-d3185d5cea57",
    ),
}


def selected_title(slug: str) -> SelectedTitle:
    if slug not in TITLES:
        raise ControllerError("Title not approved for private selected manga import")
    return TITLES[slug]
