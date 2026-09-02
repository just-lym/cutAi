from app.services.executor import apply_operations


def _timeline() -> dict:
    return {
        "duration_ms": 10000,
        "markers": [{"id": "inside", "at_ms": 4500}, {"id": "after", "at_ms": 9000}],
        "volume_changes": [
            {"id": "volume", "start_ms": 3000, "end_ms": 8000, "volume": 0.8},
            {"id": "open", "start_ms": 5000, "end_ms": -1, "volume": 0.5},
        ],
        "tracks": [
            {
                "id": "video-main",
                "clips": [
                    {
                        "id": "clip",
                        "asset_id": "asset",
                        "timeline_start_ms": 1000,
                        "timeline_end_ms": 9000,
                        "source_in_ms": 2000,
                        "source_out_ms": 18000,
                        "speed": 2.0,
                    }
                ],
            },
            {
                "id": "subtitles",
                "cues": [
                    {"id": "left", "start_ms": 2500, "end_ms": 4500, "text": "left"},
                    {"id": "span", "start_ms": 3000, "end_ms": 8000, "text": "span"},
                    {"id": "right", "start_ms": 5000, "end_ms": 7500, "text": "right"},
                ],
            },
        ],
    }


def test_delete_range_trims_and_splits_overlapping_items() -> None:
    result = apply_operations(_timeline(), [{"type": "DELETE_RANGE", "start_ms": 4000, "end_ms": 6000}])

    clips = result["tracks"][0]["clips"]
    assert len(clips) == 2
    assert clips[0]["timeline_end_ms"] == 4000
    assert clips[0]["source_out_ms"] == 8000
    assert clips[1]["timeline_start_ms"] == 4000
    assert clips[1]["timeline_end_ms"] == 7000
    assert clips[1]["source_in_ms"] == 12000
    assert result["tracks"][1]["cues"] == [
        {"id": "left", "start_ms": 2500, "end_ms": 4000, "text": "left"},
        {"id": "span", "start_ms": 3000, "end_ms": 6000, "text": "span"},
        {"id": "right", "start_ms": 4000, "end_ms": 5500, "text": "right"},
    ]
    assert result["markers"] == [{"id": "after", "at_ms": 7000}]
    assert result["volume_changes"][0]["end_ms"] == 6000
    assert result["volume_changes"][1]["start_ms"] == 4000
    assert result["volume_changes"][1]["end_ms"] == -1
    assert result["duration_ms"] == 8000


def test_multiple_delete_ranges_use_original_timeline_coordinates() -> None:
    timeline = {"duration_ms": 10000, "tracks": [{"id": "video-main", "clips": []}]}
    result = apply_operations(
        timeline,
        [
            {"type": "DELETE_RANGE", "start_ms": 1000, "end_ms": 2000},
            {"type": "DELETE_RANGE", "start_ms": 7000, "end_ms": 9000},
        ],
    )

    assert result["duration_ms"] == 7000
