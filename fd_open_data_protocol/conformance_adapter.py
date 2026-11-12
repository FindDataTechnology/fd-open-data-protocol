"""Conformance adapter for the open-data vocabulary (task 7.3).

The protocol library has no storage of its own — its "ontology" is a versioned
YAML vocabulary — so the sandbox wires the kernel to an in-memory store whose
closed vocabulary *is* the shipped release. That is enough to run every check
that does not need a database, and it exercises the parts this library actually
owns: closed sets, additive releases and stable URIs.

The adapter lives here (not in the library's runtime path) because it needs the
kernel: the library itself keeps the kernel optional so it still installs in
environments that never see this workspace.
"""

from __future__ import annotations

from fd_ontology_kernel.contracts import Unit
from fd_ontology_kernel.kernel import AdapterDeclaration, Kernel
from fd_ontology_kernel.memory import (
    MemoryJournal,
    MemoryProposalBox,
    MemoryPublicationStore,
    MemoryRegistry,
    MemoryUnitStore,
)
from fd_ontology_kernel.vocab import Entry, Vocabulary, VocabularySet

from .vocabulary import load_vocabulary, to_kernel_vocabulary

DECLARATION = AdapterDeclaration(
    system="fd-open-data-protocol",
    kernel_contract="1.0",
    manifest_shape=2,
)


def _contract_vocabulary() -> Vocabulary:
    """The shipped release, renamed onto the kernel's two contract set names.

    The kernel contract asks every surface for ``entity_types`` and
    ``relationship_kinds``; this registry calls them ``entity-type`` and
    ``relation-type``. Renaming here (rather than special-casing the kernel) keeps
    one vocabulary and one closed-set rule.
    """
    registry = load_vocabulary()
    base = to_kernel_vocabulary(registry)
    sets = dict(base.sets)

    def _renamed(source: str, target: str) -> VocabularySet | None:
        hold = sets.get(source)
        if hold is None:
            return None
        return VocabularySet(
            name=target,
            values=hold.values,
            entries={
                entry_id: Entry(
                    id=entry_id,
                    set_name=target,
                    label_en=entry.label_en,
                    label_zh=entry.label_zh,
                    description=entry.description,
                    superseded_by=entry.superseded_by,
                )
                for entry_id, entry in hold.entries.items()
            },
        )

    entity_types = _renamed("entity-type", "entity_types")
    relationship_kinds = _renamed("relation-type", "relationship_kinds")
    if entity_types is not None:
        sets["entity_types"] = entity_types
    if relationship_kinds is not None:
        sets["relationship_kinds"] = relationship_kinds

    return Vocabulary(release=base.release, sets=sets)


class _VocabularySource:
    def __init__(self, vocabulary: Vocabulary) -> None:
        self._vocabulary = vocabulary

    def load(self, *, scope_id: str) -> Vocabulary:
        return self._vocabulary


def _sandbox() -> Kernel:
    vocabulary = _contract_vocabulary()
    relationship_hold = vocabulary.sets.get("relationship_kinds")
    return Kernel(
        units=MemoryUnitStore(),
        events=MemoryJournal(),
        vocabulary=_VocabularySource(vocabulary),
        proposals=MemoryProposalBox(),
        publications=MemoryPublicationStore(),
        distribution=MemoryRegistry(),
        relationship_kinds=tuple(relationship_hold.values) if relationship_hold else (),
        # This vocabulary has no clause concept; the clause-parent rule is
        # vacuous here and the suite reports it as skipped, not as passed.
        clause_kinds=(),
        manifest_shape=DECLARATION.manifest_shape,
        declaration=DECLARATION,
    )


def build():
    """Factory named by ``adapters.json``."""
    from fd_ontology_kernel.conformance.spec import AdapterSpec

    return AdapterSpec(
        name="fd-open-data-protocol",
        system=DECLARATION.system,
        declaration=DECLARATION,
        sandbox=_sandbox,
        notes="YAML vocabulary surface; sandbox is an in-memory store over the shipped release",
    )
