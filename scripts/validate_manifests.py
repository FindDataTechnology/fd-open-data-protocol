#!/usr/bin/env python3
"""Validate datasource manifests against the new entity protocol schema.

This script loads all manifests from a directory, validates them against
the updated protocol schema, and generates a validation report.
"""

import json
import sys
from pathlib import Path
from typing import Optional

from fd_open_data_protocol.loader import load_catalog
from fd_open_data_protocol.schema import ENTITY_TYPE_VOCABULARY


def validate_manifest(manifest_path: Path) -> dict:
    """Validate a single manifest file.

    Returns dict with:
    - file: manifest path
    - valid: bool
    - errors: list of error messages
    - warnings: list of warning messages
    - entity_types: set of entity_types used in concepts
    - entities_declared: set of entity_types in entities[] field
    """
    result = {
        "file": str(manifest_path),
        "valid": True,
        "errors": [],
        "warnings": [],
        "entity_types": set(),
        "entities_declared": set(),
    }

    try:
        manifest = load_catalog(str(manifest_path))
    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Failed to load manifest: {e}")
        return result

    # Check entity_types in concepts
    for concept in manifest.concepts:
        result["entity_types"].add(concept.entity_type)
        if concept.entity_type not in ENTITY_TYPE_VOCABULARY:
            result["valid"] = False
            result["errors"].append(
                f"Invalid entity_type '{concept.entity_type}' in concept '{concept.concept}'. "
                f"Valid types: {', '.join(ENTITY_TYPE_VOCABULARY)}"
            )

    # Check entities[] field
    if hasattr(manifest, "entities") and manifest.entities:
        for entity_spec in manifest.entities:
            result["entities_declared"].add(entity_spec.entity_type)
            if entity_spec.entity_type not in ENTITY_TYPE_VOCABULARY:
                result["valid"] = False
                result["errors"].append(
                    f"Invalid entity_type '{entity_spec.entity_type}' in entities[]. "
                    f"Valid types: {', '.join(ENTITY_TYPE_VOCABULARY)}"
                )
            if entity_spec.coverage == "explicit" and not entity_spec.codes:
                result["valid"] = False
                result["errors"].append(
                    f"Entity '{entity_spec.entity_type}' has coverage='explicit' but missing 'codes' field"
                )

    # Check entity_definitions[] field
    if hasattr(manifest, "entity_definitions") and manifest.entity_definitions:
        for entity in manifest.entity_definitions:
            if entity.entity_type not in ENTITY_TYPE_VOCABULARY:
                result["valid"] = False
                result["errors"].append(
                    f"Invalid entity_type '{entity.entity_type}' in entity_definitions[]. "
                    f"Valid types: {', '.join(ENTITY_TYPE_VOCABULARY)}"
                )

    # Generate warnings for orphaned entity_types
    if result["entity_types"] and not result["entities_declared"]:
        result["warnings"].append(
            f"Manifest uses entity_types {result['entity_types']} in concepts but doesn't declare entities[]"
        )
    elif result["entity_types"] and result["entities_declared"]:
        missing = result["entity_types"] - result["entities_declared"]
        if missing:
            result["warnings"].append(
                f"Concepts reference entity_types {missing} not declared in entities[]"
            )

    # Convert sets to lists for JSON serialization
    result["entity_types"] = list(result["entity_types"])
    result["entities_declared"] = list(result["entities_declared"])

    return result


def validate_directory(directory: Path, recursive: bool = True) -> list[dict]:
    """Validate all manifests in a directory.

    Args:
        directory: Path to directory containing manifests
        recursive: Whether to search subdirectories

    Returns list of validation results.
    """
    results = []

    # Find all YAML files
    pattern = "**/*.yaml" if recursive else "*.yaml"
    for yaml_file in directory.glob(pattern):
        if yaml_file.is_file():
            result = validate_manifest(yaml_file)
            results.append(result)

    return results


def generate_report(results: list[dict]) -> dict:
    """Generate a summary report from validation results.

    Returns dict with:
    - total: total manifests checked
    - valid: number of valid manifests
    - invalid: number of invalid manifests
    - warnings: total warnings
    - errors: total errors
    - details: list of all results
    """
    valid_count = sum(1 for r in results if r["valid"])
    invalid_count = len(results) - valid_count
    warning_count = sum(len(r["warnings"]) for r in results)
    error_count = sum(len(r["errors"]) for r in results)

    return {
        "total": len(results),
        "valid": valid_count,
        "invalid": invalid_count,
        "warnings": warning_count,
        "errors": error_count,
        "details": results,
    }


def main():
    """Main validation routine."""
    if len(sys.argv) < 2:
        print("Usage: python validate_manifests.py <directory> [--output report.json]")
        print("\nValidates all YAML manifests in the given directory.")
        sys.exit(1)

    directory = Path(sys.argv[1])
    if not directory.exists() or not directory.is_dir():
        print(f"Error: Directory '{directory}' does not exist")
        sys.exit(1)

    # Check for --output flag
    output_file = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]

    print(f"Validating manifests in {directory}...")
    results = validate_directory(directory)
    report = generate_report(results)

    # Print summary
    print(f"\n=== Validation Summary ===")
    print(f"Total manifests: {report['total']}")
    print(f"Valid: {report['valid']}")
    print(f"Invalid: {report['invalid']}")
    print(f"Warnings: {report['warnings']}")
    print(f"Errors: {report['errors']}")

    # Print details for invalid manifests
    if report["invalid"] > 0:
        print(f"\n=== Invalid Manifests ===")
        for result in results:
            if not result["valid"]:
                print(f"\n{result['file']}:")
                for error in result["errors"]:
                    print(f"  ERROR: {error}")

    # Print warnings
    if report["warnings"] > 0:
        print(f"\n=== Warnings ===")
        for result in results:
            if result["warnings"]:
                print(f"\n{result['file']}:")
                for warning in result["warnings"]:
                    print(f"  WARNING: {warning}")

    # Write report if requested
    if output_file:
        with open(output_file, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport written to {output_file}")

    # Exit with error code if any invalid manifests
    sys.exit(1 if report["invalid"] > 0 else 0)


if __name__ == "__main__":
    main()
