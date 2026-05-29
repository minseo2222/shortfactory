"""Self-generated Kdenlive/MLT XML skeleton helpers.

This module never reads or mutates external ``.kdenlive`` files. It only builds
the local handoff XML from a validated F manifest.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from shorts_pipeline.models import FKdenliveManifest


def build_kdenlive_mlt_tree(manifest: FKdenliveManifest) -> ET.ElementTree:
    """Build a deterministic vertical 1080x1920 30fps MLT XML skeleton."""
    total_out = max(manifest.total_frames - 1, 0)
    root = ET.Element(
        "mlt",
        {
            "LC_NUMERIC": "C",
            "version": "7.0.0",
            "root": ".",
        },
    )
    ET.SubElement(
        root,
        "profile",
        {
            "description": "shortfactory_vertical_1080x1920_30fps",
            "width": str(manifest.canvas_width),
            "height": str(manifest.canvas_height),
            "progressive": "1",
            "frame_rate_num": str(manifest.fps),
            "frame_rate_den": "1",
            "sample_aspect_num": "1",
            "sample_aspect_den": "1",
            "display_aspect_num": "9",
            "display_aspect_den": "16",
            "colorspace": "709",
        },
    )

    for scene in manifest.scenes:
        producer_id = f"image_{scene.scene_id}"
        producer = ET.SubElement(
            root,
            "producer",
            {
                "id": producer_id,
                "in": "0",
                "out": str(scene.duration_frames - 1),
            },
        )
        ET.SubElement(producer, "property", {"name": "mlt_service"}).text = "qimage"
        ET.SubElement(producer, "property", {"name": "resource"}).text = scene.image_path
        ET.SubElement(producer, "property", {"name": "length"}).text = str(
            scene.duration_frames
        )

    for scene in manifest.scenes:
        producer_id = f"text_{scene.scene_id}"
        producer = ET.SubElement(
            root,
            "producer",
            {
                "id": producer_id,
                "in": "0",
                "out": str(scene.duration_frames - 1),
            },
        )
        ET.SubElement(producer, "property", {"name": "mlt_service"}).text = "qimage"
        ET.SubElement(producer, "property", {"name": "resource"}).text = (
            scene.text_overlay_path
        )
        ET.SubElement(producer, "property", {"name": "length"}).text = str(
            scene.duration_frames
        )

    image_playlist = ET.SubElement(root, "playlist", {"id": "image_track"})
    for scene in manifest.scenes:
        ET.SubElement(
            image_playlist,
            "entry",
            {
                "producer": f"image_{scene.scene_id}",
                "in": "0",
                "out": str(scene.duration_frames - 1),
            },
        )

    text_playlist = ET.SubElement(root, "playlist", {"id": "text_overlay_track"})
    for scene in manifest.scenes:
        ET.SubElement(
            text_playlist,
            "entry",
            {
                "producer": f"text_{scene.scene_id}",
                "in": "0",
                "out": str(scene.duration_frames - 1),
            },
        )

    tractor = ET.SubElement(
        root,
        "tractor",
        {
            "id": "tractor0",
            "in": "0",
            "out": str(total_out),
        },
    )
    multitrack = ET.SubElement(tractor, "multitrack")
    ET.SubElement(multitrack, "track", {"producer": "image_track"})
    ET.SubElement(multitrack, "track", {"producer": "text_overlay_track"})

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    return tree


def write_kdenlive_project_xml(path: Path, manifest: FKdenliveManifest) -> Path:
    """Write the self-generated Kdenlive/MLT XML skeleton to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = build_kdenlive_mlt_tree(manifest)
    tree.write(path, encoding="utf-8", xml_declaration=True, short_empty_elements=True)
    return path
